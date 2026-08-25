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


# ── DST helpers ───────────────────────────────────────────────────────────────
# US Mountain Time: UTC-7 (MST) or UTC-6 (MDT, second Sun Mar – first Sun Nov).
# Rules have been stable since the Energy Policy Act of 2005 (effective 2007).

def _day_of_week(y, m, d):
    """Return day of week (0=Sun … 6=Sat) via Tomohiko Sakamoto's algorithm."""
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    if m < 3:
        y -= 1
    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7


def _nth_sunday(y, m, n):
    """Day-of-month of the nth Sunday in month m of year y."""
    d = 1
    while _day_of_week(y, m, d) != 0:
        d += 1
    return d + (n - 1) * 7


def _mountain_utc_offset(year, month, day):
    """
    DST-aware UTC offset in seconds for US Mountain Time (America/Denver).
    No external API needed — US DST boundaries are fixed calendar math.
    """
    MST = -25200   # UTC-7
    MDT = -21600   # UTC-6
    if month < 3 or month > 11:
        return MST
    if 3 < month < 11:
        return MDT
    if month == 3:
        return MDT if day >= _nth_sunday(year, 3, 2) else MST   # 2nd Sunday of March
    # month == 11
    return MST if day >= _nth_sunday(year, 11, 1) else MDT      # 1st Sunday of November


# ── Helpers ───────────────────────────────────────────────────────────────────

def sync_time(magtag):
    """
    Sync from Adafruit IO (reliable for CircuitPython; no third-party dependency).
    AIO returns seconds since 2000-01-01 UTC (CircuitPython epoch).
    Converts to Unix epoch for N2YO comparisons, computes DST offset locally.
    """
    global _boot_unix, _boot_mono, _utc_offset
    user = secrets["aio_username"]
    key  = secrets["aio_key"]
    url  = (
        "https://io.adafruit.com/api/v2/"
        + user
        + "/integrations/time/seconds?x-aio-key="
        + key
    )
    print("Syncing time via Adafruit IO...")
    try:
        resp = magtag.network.fetch(url)
        body = resp.text.strip()
        resp.close()
        if not body.isdigit():
            raise ValueError(f"unexpected AIO response: {body[:80]}")
        aio_secs = int(body)

        # AIO epoch is 2000-01-01; Unix epoch is 1970-01-01 (946684800 s apart)
        _boot_unix = aio_secs + 946684800
        _boot_mono = time.monotonic()

        # Get UTC date for DST calculation (time.localtime treats arg as CP epoch)
        t = time.localtime(aio_secs)
        _utc_offset = _mountain_utc_offset(t.tm_year, t.tm_mon, t.tm_mday)

        abbr = "MDT" if _utc_offset == -21600 else "MST"
        print(f"  Synced: {t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d} UTC  →  {abbr}")
    except Exception as e:
        print(f"  Time sync failed: {e}")
        # Non-fatal: passes won't be filtered by time, but still display
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
