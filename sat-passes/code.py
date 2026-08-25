"""
sat-passes/code.py — Upcoming satellite pass display for Adafruit MagTag
Shows the next N passes across a configurable list of satellites via N2YO API.

Hardware: Adafruit MagTag (ESP32-S2, 2.9" e-ink 296*128, 4 buttons, NeoPixels)
Firmware: CircuitPython 8+
Libraries needed (copy to CIRCUITPY/lib/):
  - adafruit_magtag/  (adafruit-circuitpython-magtag bundle)
  - adafruit_requests.mpy
  - adafruit_connection_manager.mpy

Secrets keys required (see secrets.py.example):
  ssid, password, n2yo_api_key, latitude, longitude, altitude_km,
  timezone_offset, aio_username, aio_key
"""

import time
import json
import board
import busio
import alarm
import supervisor

from adafruit_magtag.magtag import MagTag
from secrets import secrets
from satellites import SATELLITES

# ── Config ────────────────────────────────────────────────────────────────────

REFRESH_INTERVAL_S = 3600       # re-fetch from N2YO every hour
DAYS_AHEAD        = 1           # how many days of passes to request
MIN_ELEVATION_DEG = 10          # ignore passes that barely peek over horizon
MAX_PASSES_SHOWN  = 4           # number of pass rows on display

N2YO_BASE = "https://api.n2yo.com/rest/v1/satellite"

# ── Helpers ───────────────────────────────────────────────────────────────────

def n2yo_url(norad_id):
    """Build a radiopasses URL for the given NORAD ID."""
    lat  = secrets["latitude"]
    lon  = secrets["longitude"]
    alt  = secrets["altitude_km"]
    key  = secrets["n2yo_api_key"]
    return (
        f"{N2YO_BASE}/radiopasses/{norad_id}"
        f"/{lat}/{lon}/{alt}"
        f"/{DAYS_AHEAD}/{MIN_ELEVATION_DEG}"
        f"/&apiKey={key}"
    )


def fetch_passes(magtag, norad_id, label):
    """Return list of pass dicts {label, aos, los, max_el} sorted by AOS."""
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
            "aos":    p["startUTC"],     # Unix timestamp
            "los":    p["endUTC"],
            "max_el": p["maxEl"],
        })
    return passes


def unix_to_hhmm(ts, tz_offset):
    """Convert a UTC Unix timestamp to a local HH:MM string."""
    local_ts = ts + tz_offset * 3600
    t = time.localtime(local_ts)
    return f"{t.tm_hour:02d}:{t.tm_min:02d}"


def format_duration(start_ts, end_ts):
    """Return duration in minutes:seconds."""
    dur = int(end_ts - start_ts)
    return f"{dur // 60}m{dur % 60:02d}s"


def build_display_lines(all_passes, tz_offset):
    """Sort passes by AOS, take the next MAX_PASSES_SHOWN, return display strings."""
    now = time.time()
    upcoming = [p for p in all_passes if p["aos"] > now]
    upcoming.sort(key=lambda p: p["aos"])
    upcoming = upcoming[:MAX_PASSES_SHOWN]

    lines = []
    for p in upcoming:
        hhmm = unix_to_hhmm(p["aos"], tz_offset)
        dur  = format_duration(p["aos"], p["los"])
        el   = int(p["max_el"])
        lines.append(f"{p['label']:<6} {hhmm}  {dur:>7}  {el:>2}°")

    # Pad to MAX_PASSES_SHOWN so display doesn't jump around
    while len(lines) < MAX_PASSES_SHOWN:
        lines.append("")

    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    magtag = MagTag()
    magtag.network.connect()

    tz = secrets["timezone_offset"]

    # ── Sync time via Adafruit IO ─────────────────────────────────────────────
    # Requires aio_username + aio_key in secrets.py.
    # Sets the device RTC so time.time() returns accurate UTC Unix timestamps,
    # which we need to filter out already-passed N2YO results.
    print("Syncing time via Adafruit IO...")
    try:
        magtag.network.get_local_time()
        print(f"  RTC synced: {time.localtime()}")
    except Exception as e:
        # Non-fatal: we'll still fetch passes, but AOS filtering may be off
        print(f"  Time sync failed: {e}")

    # ── Layout ────────────────────────────────────────────────────────────────
    # Header row
    magtag.add_text(
        text_position=(4, 6),
        text_scale=1,
        text_color=0x000000,
        text_font="/fonts/Arial-Bold-12.bdf",
    )
    magtag.set_text("SAT    TIME   DUR     MAX EL", index=0, auto_refresh=False)

    # Divider line drawn via a filled rect in the background bitmap would need
    # displayio — for simplicity we use a text row of dashes
    magtag.add_text(
        text_position=(4, 20),
        text_scale=1,
        text_color=0x000000,
    )
    magtag.set_text("─" * 38, index=1, auto_refresh=False)

    # Pass rows (4 rows, each 24px apart starting at y=32)
    for i in range(MAX_PASSES_SHOWN):
        magtag.add_text(
            text_position=(4, 32 + i * 24),
            text_scale=1,
            text_color=0x000000,
        )

    # Status line at bottom
    magtag.add_text(
        text_position=(4, 120),
        text_scale=1,
        text_color=0x000000,
    )

    # ── Fetch & render ────────────────────────────────────────────────────────
    magtag.set_text(
        "Fetching passes...", index=2 + MAX_PASSES_SHOWN, auto_refresh=False
    )

    all_passes = []
    for norad_id, label, _mode in SATELLITES:
        print(f"Fetching {label} ({norad_id})...")
        all_passes.extend(fetch_passes(magtag, norad_id, label))
        time.sleep(0.5)   # be polite to the API

    lines = build_display_lines(all_passes, tz)

    for i, line in enumerate(lines):
        # index 2 = first pass row (0=header, 1=divider, 2..5=passes, 6=status)
        magtag.set_text(line, index=2 + i, auto_refresh=False)

    # Status line: last updated time
    now_str = unix_to_hhmm(int(time.time()), tz)
    magtag.set_text(f"Updated {now_str} local", index=2 + MAX_PASSES_SHOWN)

    # ── Deep sleep until next refresh ─────────────────────────────────────────
    print(f"Sleeping for {REFRESH_INTERVAL_S}s...")
    magtag.exit_and_deep_sleep(REFRESH_INTERVAL_S)


main()
