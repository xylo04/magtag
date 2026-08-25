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
  ssid, password, n2yo_api_key, latitude, longitude, altitude_km, timezone
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

N2YO_BASE  = "https://api.n2yo.com/rest/v1/satellite"
WTIME_BASE = "http://worldtimeapi.org/api/timezone"

# ── Time tracking (set by sync_time) ─────────────────────────────────────────
# We store a Unix timestamp + monotonic reference rather than relying on
# CircuitPython's RTC epoch (2000-01-01), which differs from the Unix epoch
# (1970-01-01) that N2YO uses. now_unix() stays accurate without any epoch math.

_boot_unix  = 0     # Unix timestamp captured at last sync
_boot_mono  = 0.0   # time.monotonic() captured at last sync
_utc_offset = 0     # DST-aware UTC offset in seconds (e.g. -21600 for MDT)


def now_unix():
    """Current Unix timestamp, derived from boot reference + monotonic elapsed."""
    return int(_boot_unix + (time.monotonic() - _boot_mono))


# ── Helpers ───────────────────────────────────────────────────────────────────

def sync_time(magtag, timezone):
    """
    Fetch current time and DST-aware UTC offset from WorldTimeAPI.
    The API returns raw_offset (base TZ, seconds) + dst_offset (DST addition,
    seconds) separately, so we never need a hardcoded timezone_offset config.
    Returns the DST-aware offset in seconds.
    """
    global _boot_unix, _boot_mono, _utc_offset
    url = f"{WTIME_BASE}/{timezone}"
    print(f"Syncing time for {timezone}...")
    try:
        resp = magtag.network.fetch(url)
        data = resp.json()
        resp.close()
        _utc_offset = data["raw_offset"] + data["dst_offset"]
        _boot_unix  = data["unixtime"]   # true Unix timestamp
        _boot_mono  = time.monotonic()
        abbr     = data.get("abbreviation", "?")
        offset_h = _utc_offset // 3600
        print(f"  Synced: {abbr} (UTC{offset_h:+d}), unix={_boot_unix}")
    except Exception as e:
        print(f"  Time sync failed: {e}")
        # Non-fatal: _boot_unix stays 0, so all passes will be shown
        # (better than hard-crashing on a transient network hiccup)
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
    Pure modular arithmetic — no CircuitPython epoch assumptions required.
    """
    tod = (unix_ts + utc_offset_s) % 86400   # seconds into the local day
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
        lines.append(f"{p['label']:<6} {hhmm}  {dur:>7}  {el:>2}°")

    # Pad so layout stays stable when fewer than MAX_PASSES_SHOWN remain
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

    # Status line at bottom
    magtag.add_text(
        text_position=(4, 118),
        text_scale=1,
        text_color=0x000000,
        text_font=terminalio.FONT,
    )

    # ── Time sync ─────────────────────────────────────────────────────────────
    # WorldTimeAPI returns raw_offset + dst_offset separately, so the device
    # always knows the correct local offset without any manual DST config.
    utc_offset_s = sync_time(magtag, secrets["timezone"])

    # ── Fetch & render ────────────────────────────────────────────────────────
    magtag.set_text(
        "Fetching passes...", index=2 + MAX_PASSES_SHOWN, auto_refresh=False
    )

    all_passes = []
    for norad_id, label, _mode in SATELLITES:
        print(f"Fetching {label} ({norad_id})...")
        all_passes.extend(fetch_passes(magtag, norad_id, label))
        time.sleep(0.5)   # be polite to the API

    lines = build_display_lines(all_passes, utc_offset_s)

    for i, line in enumerate(lines):
        magtag.set_text(line, index=2 + i, auto_refresh=False)

    now_str = unix_to_hhmm(now_unix(), utc_offset_s)
    magtag.set_text(f"Updated {now_str} local", index=2 + MAX_PASSES_SHOWN)

    print(f"Sleeping for {REFRESH_INTERVAL_S}s...")
    magtag.exit_and_deep_sleep(REFRESH_INTERVAL_S)


main()
