"""
sat-passes/code.py — Upcoming satellite pass display for Adafruit MagTag
Shows the next N passes across a configurable list of satellites via N2YO API.

Hardware: Adafruit MagTag (ESP32-S2, 2.9" e-ink 296×128, 4 buttons, NeoPixels)
Firmware: CircuitPython 8+
Libraries needed (copy to CIRCUITPY/lib/):
  - adafruit_magtag/  (adafruit-circuitpython-magtag bundle)
  - adafruit_requests.mpy
  - adafruit_connection_manager.mpy

Configuration: copy settings.toml.example → settings.toml, fill in values.
All settings are read from settings.toml via os.getenv() (CircuitPython 8+ idiom).
"""

import os
import time
import terminalio
from adafruit_magtag.magtag import MagTag
from satellites import SATELLITES

# ── Config ────────────────────────────────────────────────────────────────────

REFRESH_INTERVAL_S = 3600       # re-fetch from N2YO every hour
DAYS_AHEAD        = 1           # how many days of passes to request
MIN_ELEVATION_DEG = 10          # ignore passes that barely peek over horizon
MAX_PASSES_SHOWN  = 4           # number of pass rows on display

N2YO_BASE = "https://api.n2yo.com/rest/v1/satellite"

BATTERY_EMPTY_V = 3.20          # approximate 0% for a single-cell LiPo
BATTERY_FULL_V  = 4.20          # approximate 100% for a single-cell LiPo

# ── Time tracking (set by sync_time) ─────────────────────────────────────────

_boot_unix  = 0     # Unix timestamp captured at last sync
_boot_mono  = 0.0   # time.monotonic() captured at last sync
_utc_offset = 0     # DST-aware UTC offset in seconds (e.g. -21600 for MDT)


def now_unix():
    """Current Unix timestamp, derived from boot reference + monotonic elapsed."""
    return int(_boot_unix + (time.monotonic() - _boot_mono))


# ── Helpers ───────────────────────────────────────────────────────────────────

def sync_time(magtag):
    """
    Sync via magtag.network.get_local_time(), which uses the Adafruit IO
    strftime endpoint. Reads ADAFRUIT_AIO_USERNAME / ADAFRUIT_AIO_KEY from
    settings.toml automatically. The reply includes the DST-aware UTC offset
    (%z), so no local DST math is needed.
    Reply format: "YYYY-MM-DD HH:MM:SS.mmm yday wday +HHMM TZabbr"
    """
    global _boot_unix, _boot_mono, _utc_offset
    print("Syncing time via Adafruit IO...")
    try:
        timezone = os.getenv("TIMEZONE", "UTC")
        reply = magtag.network.get_local_time(location=timezone)
        # e.g. "2026-08-25 10:51:00.000 237 2 -0600 MDT"
        fields = reply.split(" ")

        # Parse DST-aware UTC offset from %z field (e.g. "-0600")
        tz_str = fields[4]
        sign = -1 if tz_str[0] == "-" else 1
        _utc_offset = sign * (int(tz_str[1:3]) * 3600 + int(tz_str[3:5]) * 60)

        # Parse local datetime components
        y, mo, d = (int(x) for x in fields[0].split("-"))
        h, mi, s = (int(x) for x in fields[1].split(".")[0].split(":"))

        # Convert local time-of-day to UTC, handling midnight rollover
        utc_tod = h * 3600 + mi * 60 + s - _utc_offset
        day_adj = 0
        if utc_tod >= 86400:
            utc_tod -= 86400; day_adj = 1
        elif utc_tod < 0:
            utc_tod += 86400; day_adj = -1

        # Days since Unix epoch via Julian Day Number (Gregorian calendar).
        # Avoids time.time() entirely — no CircuitPython epoch ambiguity.
        a = (14 - mo) // 12
        yy = y + 4800 - a
        m = mo + 12 * a - 3
        jdn = (d + day_adj + (153 * m + 2) // 5
               + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045)
        _boot_unix = (jdn - 2440588) * 86400 + utc_tod
        _boot_mono = time.monotonic()

        tz_abbr = fields[5] if len(fields) > 5 else tz_str
        print(f"  Synced: {tz_abbr} (UTC{_utc_offset // 3600:+d}), unix={_boot_unix}")
    except Exception as e:
        print(f"  Time sync failed: {e}")
    return _utc_offset


def n2yo_url(norad_id):
    """Build a radiopasses URL for the given NORAD ID."""
    lat = os.getenv("LATITUDE", "0")
    lon = os.getenv("LONGITUDE", "0")
    alt = os.getenv("ALTITUDE_KM", "0")
    key = os.getenv("N2YO_API_KEY", "")
    return (
        f"{N2YO_BASE}/radiopasses/{norad_id}"
        f"/{lat}/{lon}/{alt}"
        f"/{DAYS_AHEAD}/{MIN_ELEVATION_DEG}"
        "/&apiKey=" + key
    )


def fetch_passes(magtag, norad_id, label):
    """
    Return list of pass dicts {label, aos, los, max_el}, or None if the
    N2YO API signals a rate-limit error (caller should circuit-break).
    """
    url = n2yo_url(norad_id)
    try:
        response = magtag.network.fetch(url)
        data = response.json()
        response.close()
    except Exception as e:
        print(f"  fetch error for {label}: {e}")
        return []

    if "error" in data:
        err = data["error"]
        print(f"  {label}: API error: {err}")
        # Rate-limit errors contain "transaction" or "exceeded"; signal caller
        # to stop making further requests this cycle.
        if "transaction" in err or "exceeded" in err.lower():
            return None
        return []

    raw = data.get("passes") or []
    print(f"  {label}: {len(raw)} passes")
    passes = []
    for p in raw:
        passes.append({
            "label":  label,
            "aos":    p["startUTC"],   # Unix timestamp
            "los":    p["endUTC"],
            "max_el": p["maxEl"],
        })
    return passes


def unix_to_hhmm(unix_ts, utc_offset_s):
    """
    Convert a UTC Unix timestamp to a local HH:MM string.
    Pure modular arithmetic — no CircuitPython epoch assumptions.
    """
    tod = (unix_ts + utc_offset_s) % 86400
    return f"{tod // 3600:02d}:{(tod % 3600) // 60:02d}"


def unix_to_date(unix_ts, utc_offset_s):
    """
    Convert a UTC Unix timestamp to a local YYYY-MM-DD string.
    Uses the Julian Day Number inverse formula — epoch-agnostic.
    Handy on e-ink: the persistent display shows the last-updated date,
    making it obvious if the device has been off for a while.
    """
    days  = (unix_ts + utc_offset_s) // 86400   # local days since Unix epoch
    jdn   = days + 2440588                       # Julian Day Number
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day   = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year  = 100 * b + d - 4800 + m // 10
    return f"{year}-{month:02d}-{day:02d}"


def format_duration(start_ts, end_ts):
    """Return pass duration as 'Xm YYs'."""
    dur = int(end_ts - start_ts)
    return f"{dur // 60}m{dur % 60:02d}s"


def battery_percent(magtag):
    """Return an approximate battery percentage, or None if unavailable."""
    try:
        battery_v = magtag.peripherals.battery
    except Exception as e:
        print(f"  battery read failed: {e}")
        return None

    if battery_v is None:
        return None

    pct = int(
        ((battery_v - BATTERY_EMPTY_V) / (BATTERY_FULL_V - BATTERY_EMPTY_V)) * 100
        + 0.5
    )
    if pct < 0:
        pct = 0
    elif pct > 100:
        pct = 100
    print(f"  battery: {battery_v:.2f}V ({pct}%)")
    return pct


def build_display_lines(all_passes, utc_offset_s):
    """Sort passes by AOS, take the next MAX_PASSES_SHOWN, return display strings."""
    cur = now_unix()
    print(f"Build display: total={len(all_passes)}, now_unix={cur}")
    if all_passes:
        earliest = min(p["aos"] for p in all_passes)
        latest   = max(p["aos"] for p in all_passes)
        print(f"  AOS range: {earliest}..{latest} (delta_first={earliest - cur}s)")
    upcoming = [p for p in all_passes if p["aos"] > cur]
    upcoming.sort(key=lambda p: p["aos"])
    upcoming = upcoming[:MAX_PASSES_SHOWN]
    print(f"  Upcoming: {len(upcoming)}")

    lines = []
    for p in upcoming:
        hhmm = unix_to_hhmm(p["aos"], utc_offset_s)
        dur  = format_duration(p["aos"], p["los"])
        el   = int(p["max_el"])
        lines.append(f"{p['label']:<6} {hhmm}  {dur:>7}  {el:>3}")

    while len(lines) < MAX_PASSES_SHOWN:
        lines.append("")

    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    magtag = MagTag()
    magtag.network.connect()

    # ── Layout ────────────────────────────────────────────────────────────────
    magtag.add_text(
        text_position=(4, 4),
        text_scale=1,
        text_color=0x000000,
        text_font=terminalio.FONT,
    )
    magtag.set_text("SAT    TIME    DUR    EL", index=0, auto_refresh=False)

    magtag.add_text(
        text_position=(4, 16),
        text_scale=1,
        text_color=0x000000,
        text_font=terminalio.FONT,
    )
    magtag.set_text("-" * 34, index=1, auto_refresh=False)

    for i in range(MAX_PASSES_SHOWN):
        magtag.add_text(
            text_position=(4, 26 + i * 24),
            text_scale=1,
            text_color=0x000000,
            text_font=terminalio.FONT,
        )

    magtag.add_text(
        text_position=(4, 118),
        text_scale=1,
        text_color=0x000000,
        text_font=terminalio.FONT,
    )

    # ── Time sync ─────────────────────────────────────────────────────────────
    utc_offset_s = sync_time(magtag)

    # ── Fetch passes (with rate-limit circuit-breaker) ────────────────────────
    magtag.set_text(
        "Fetching passes...", index=2 + MAX_PASSES_SHOWN, auto_refresh=False
    )

    all_passes = []
    rate_limited = False
    for norad_id, label, _mode in SATELLITES:
        if rate_limited:
            print(f"  Skipping {label} (rate limited)")
            continue
        print(f"Fetching {label} ({norad_id})...")
        result = fetch_passes(magtag, norad_id, label)
        if result is None:
            rate_limited = True
            print("  N2YO rate limit hit — skipping remaining satellites this cycle")
        else:
            all_passes.extend(result)
        time.sleep(0.5)

    # ── Render ────────────────────────────────────────────────────────────────
    lines = build_display_lines(all_passes, utc_offset_s)

    print(f"Rendering {len(lines)} rows...")
    for i, line in enumerate(lines):
        print(f"  row {i}: {repr(line)}")
        magtag.set_text(line, index=2 + i, auto_refresh=False)

    now_str  = unix_to_hhmm(now_unix(), utc_offset_s)
    date_str = unix_to_date(now_unix(), utc_offset_s)
    batt_pct = battery_percent(magtag)
    batt_str = f", batt {batt_pct}%" if batt_pct is not None else ""
    status = f"Updated {now_str} local, {date_str}{batt_str}"
    if rate_limited:
        status = f"N2YO rate limited, {date_str}{batt_str}"
    print(f"  status: {repr(status)}")
    magtag.set_text(status, index=2 + MAX_PASSES_SHOWN, auto_refresh=True)

    sleep_s = 600 if rate_limited else REFRESH_INTERVAL_S
    print(f"Sleeping for {sleep_s}s...")
    magtag.exit_and_deep_sleep(sleep_s)


main()
