"""
sat-passes/code.py — Upcoming satellite pass display for Adafruit MagTag
Shows the next N passes across a configurable list of satellites via N2YO API.

Hardware: Adafruit MagTag (ESP32-S2, 2.9" e-ink 296×128, 4 buttons, NeoPixels)
Firmware: CircuitPython 8+
Libraries needed (copy to CIRCUITPY/lib/):
  - adafruit_magtag/  (adafruit-circuitpython-magtag bundle)
  - adafruit_requests.mpy
  - adafruit_connection_manager.mpy

Secrets keys required (see secrets.py.example):
  ssid, password, n2yo_api_key, aio_username, aio_key,
  latitude, longitude, altitude_km, timezone
"""

import time
import terminalio
from adafruit_magtag.magtag import MagTag
from secrets import secrets
from satellites import SATELLITES

# ── Config ────────────────────────────────────────────────────────────────────

REFRESH_INTERVAL_S = 3600       # re-fetch from N2YO every hour
DAYS_AHEAD        = 1           # how many days of passes to request
MIN_ELEVATION_DEG = 10          # ignore passes that barely peek over horizon
MAX_PASSES_SHOWN  = 4           # number of pass rows on display

N2YO_BASE = "https://api.n2yo.com/rest/v1/satellite"

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
    strftime endpoint — reads aio_username/aio_key from secrets.py automatically.
    The reply includes the DST-aware UTC offset (%z), so no local DST math needed.
    Reply format: "YYYY-MM-DD HH:MM:SS.mmm yday wday +HHMM TZabbr"
    """
    global _boot_unix, _boot_mono, _utc_offset
    print("Syncing time via Adafruit IO...")
    try:
        reply = magtag.network.get_local_time(location=secrets["timezone"])
        # e.g. "2026-08-25 10:51:00.000 237 2 -0600 MDT"
        fields = reply.split(" ")
        tz_str = fields[4]   # e.g. "-0600"
        sign = -1 if tz_str[0] == "-" else 1
        _utc_offset = sign * (int(tz_str[1:3]) * 3600 + int(tz_str[3:5]) * 60)

        # RTC is now set to local time by get_local_time().
        # time.time() = CP epoch seconds (since 2000-01-01) for local time.
        # UTC Unix = local_cp_secs - utc_offset + 946684800
        _boot_unix = int(time.time()) - _utc_offset + 946684800
        _boot_mono = time.monotonic()

        tz_abbr = fields[5] if len(fields) > 5 else tz_str
        print(f"  Synced: {tz_abbr} (UTC{_utc_offset // 3600:+d})")
    except Exception as e:
        print(f"  Time sync failed: {e}")
    return _utc_offset


def n2yo_url(norad_id):
    """Build a radiopasses URL for the given NORAD ID."""
    lat = secrets["latitude"]
    lon = secrets["longitude"]
    alt = secrets["altitude_km"]
    key = secrets["n2yo_api_key"]
    return (
        f"{N2YO_BASE}/radiopasses/{norad_id}"
        f"/{lat}/{lon}/{alt}"
        f"/{DAYS_AHEAD}/{MIN_ELEVATION_DEG}"
        f"/&apiKey={key}"
    )


def fetch_passes(magtag, norad_id, label):
    """Return list of pass dicts {label, aos, los, max_el}."""
    url = n2yo_url(norad_id)
    try:
        response = magtag.network.fetch(url)
        data = response.json()
        response.close()
    except Exception as e:
        print(f"  fetch error for {label}: {e}")
        return []

    passes = []
    for p in data.get("passes", []):
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


def format_duration(start_ts, end_ts):
    """Return pass duration as 'Xm YYs'."""
    dur = int(end_ts - start_ts)
    return f"{dur // 60}m{dur % 60:02d}s"


def build_display_lines(all_passes, utc_offset_s):
    """Sort passes by AOS, take the next MAX_PASSES_SHOWN, return display strings."""
    cur = now_unix()
    upcoming = [p for p in all_passes if p["aos"] > cur]
    upcoming.sort(key=lambda p: p["aos"])
    upcoming = upcoming[:MAX_PASSES_SHOWN]

    lines = []
    for p in upcoming:
        hhmm = unix_to_hhmm(p["aos"], utc_offset_s)
        dur  = format_duration(p["aos"], p["los"])
        el   = int(p["max_el"])
        # terminalio.FONT is ASCII-only — no degree symbol; column header says EL
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

    # ── Fetch & render ────────────────────────────────────────────────────────
    magtag.set_text(
        "Fetching passes...", index=2 + MAX_PASSES_SHOWN, auto_refresh=False
    )

    all_passes = []
    for norad_id, label, _mode in SATELLITES:
        print(f"Fetching {label} ({norad_id})...")
        all_passes.extend(fetch_passes(magtag, norad_id, label))
        time.sleep(0.5)

    lines = build_display_lines(all_passes, utc_offset_s)

    for i, line in enumerate(lines):
        magtag.set_text(line, index=2 + i, auto_refresh=False)

    now_str = unix_to_hhmm(now_unix(), utc_offset_s)
    magtag.set_text(f"Updated {now_str} local", index=2 + MAX_PASSES_SHOWN)

    print(f"Sleeping for {REFRESH_INTERVAL_S}s...")
    magtag.exit_and_deep_sleep(REFRESH_INTERVAL_S)


main()
