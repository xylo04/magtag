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
import alarm
import board
import displayio
import supervisor
import terminalio
import vectorio
from adafruit_magtag.magtag import MagTag
from n2yo import N2YOClient
from passes import ACTIVE, RECENT, next_wake_s, select_passes
from satellites import SATELLITES
from status import (
    LOW_BATTERY_PERCENT,
    UTC_OFFSET_LEN,
    battery_percent,
    is_low_battery,
    pack_utc_offset,
    status_lines,
    unpack_utc_offset,
)

# ── Config ────────────────────────────────────────────────────────────────────

REFRESH_INTERVAL_S = 3600       # longest nap: re-fetch from N2YO every hour
MIN_SLEEP_S       = 60          # shortest nap, so we don't thrash the e-ink
DAYS_AHEAD        = 1           # how many days of passes to request
MIN_ELEVATION_DEG = 10          # ignore passes that barely peek over horizon
MAX_PASSES_SHOWN  = 5           # number of pass rows on display

# How long a finished pass keeps its row before it drops off the display.
RECENT_RETENTION_S = int(os.getenv("RECENT_PASS_RETENTION_S", "900"))

# How long the status page stays up after a button press before the pass list
# comes back.
STATUS_PAGE_DURATION_S = int(os.getenv("STATUS_PAGE_DURATION_S", "15"))

# Below this battery percentage, and while unplugged, skip all network work and
# just ask to be charged, so stale pass times can't linger on the display.
LOW_BATTERY_PCT     = int(os.getenv("LOW_BATTERY_PERCENT", str(LOW_BATTERY_PERCENT)))
LOW_BATTERY_SLEEP_S = 3600      # re-check the battery once an hour

ROW_HEIGHT = 23                 # vertical pitch between pass rows
ROW_TOP    = 26                 # baseline (vertical centre) of the first row

COLOR_NORMAL    = 0x000000      # upcoming pass: black on white
COLOR_ACTIVE    = 0xFFFFFF      # in-progress pass: white on black
COLOR_RECENT    = 0x555555      # finished pass: subdued grey
COLOR_HIGHLIGHT = 0x000000      # background fill behind an in-progress pass

STATUS_INDEX = 2 + MAX_PASSES_SHOWN     # text index of the status page label

# Buttons that summon the status page: all four direction arrows.
BUTTON_PINS = (board.BUTTON_A, board.BUTTON_B, board.BUTTON_C, board.BUTTON_D)
BUTTON_RELEASE_WAIT_S = 5       # give up waiting for a stuck button after this

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


def read_battery_percent(magtag):
    """Return an approximate battery percentage, or None if unavailable."""
    try:
        battery_v = magtag.peripherals.battery
    except Exception as e:
        print(f"  battery read failed: {e}")
        return None

    pct = battery_percent(battery_v)
    if pct is not None:
        print(f"  battery: {battery_v:.2f}V ({pct}%)")
    return pct


def build_display_rows(all_passes, utc_offset_s):
    """
    Return ``MAX_PASSES_SHOWN`` (line, state, pass) tuples ready for rendering.

    In-progress and recently finished passes keep their row, so the display
    also shows what just happened, not only what is coming up.
    """
    cur = now_unix()
    print(f"Build display: total={len(all_passes)}, now_unix={cur}")
    if all_passes:
        earliest = min(p["aos"] for p in all_passes)
        latest   = max(p["aos"] for p in all_passes)
        print(f"  AOS range: {earliest}..{latest} (delta_first={earliest - cur}s)")
    visible = select_passes(all_passes, cur, MAX_PASSES_SHOWN, RECENT_RETENTION_S)
    print(f"  Visible: {len(visible)}")

    rows = []
    for pass_info, state in visible:
        hhmm = unix_to_hhmm(pass_info["aos"], utc_offset_s)
        dur  = format_duration(pass_info["aos"], pass_info["los"])
        el   = int(pass_info["max_el"])
        rows.append(
            (f"{pass_info['label']:<6} {hhmm}  {dur:>7}  {el:>3}", state, pass_info)
        )

    while len(rows) < MAX_PASSES_SHOWN:
        rows.append(("", None, None))

    return rows


def add_row_highlights(magtag):
    """
    Create one hidden black bar per pass row, behind the text labels.

    They are added before any labels so the labels draw on top of them; the
    bars are then un-hidden for whichever rows are currently in progress.
    """
    palette = displayio.Palette(1)
    palette[0] = COLOR_HIGHLIGHT
    highlights = []
    for i in range(MAX_PASSES_SHOWN):
        group = displayio.Group()
        group.append(vectorio.Rectangle(
            pixel_shader=palette,
            width=magtag.graphics.display.width,
            height=ROW_HEIGHT - 4,
            x=0,
            y=ROW_TOP + i * ROW_HEIGHT - (ROW_HEIGHT - 4) // 2,
        ))
        group.hidden = True
        magtag.graphics.root_group.append(group)
        highlights.append(group)
    return highlights


def woke_from_button():
    """True when this boot was caused by a button press rather than a timer."""
    try:
        return isinstance(alarm.wake_alarm, alarm.pin.PinAlarm)
    except AttributeError:
        return False


def clock_synced():
    """True once ``sync_time`` has established a real wall-clock reference."""
    return _boot_unix != 0


def save_utc_offset(utc_offset_s):
    """
    Remember the DST-aware UTC offset across deep sleep.

    ``alarm.sleep_memory`` survives deep sleep but not a power cycle. It lets
    the status page render the last N2YO query time in local time on a button
    press, before the clock has been re-synced over the network.
    """
    try:
        alarm.sleep_memory[0:UTC_OFFSET_LEN] = pack_utc_offset(utc_offset_s)
    except (AttributeError, ValueError, RuntimeError) as e:
        print(f"  UTC offset save failed: {e}")


def load_utc_offset():
    """Return the remembered UTC offset in seconds, or ``None``."""
    try:
        return unpack_utc_offset(bytes(alarm.sleep_memory[0:UTC_OFFSET_LEN]))
    except (AttributeError, ValueError, RuntimeError) as e:
        print(f"  UTC offset read failed: {e}")
        return None


def build_status_lines(unix_ts, utc_offset_s, battery_pct, rate_limited=False):
    """
    Status page lines for the last N2YO query time.

    Both the timestamp and the offset are needed to render a local time, so an
    unknown either way shows as "Updated unknown".
    """
    if not unix_ts or utc_offset_s is None:
        return status_lines(None, None, battery_pct, rate_limited)
    return status_lines(
        unix_to_hhmm(unix_ts, utc_offset_s),
        unix_to_date(unix_ts, utc_offset_s),
        battery_pct,
        rate_limited,
    )


def render_passes(magtag, rows, highlights):
    """Draw the main page: the pass list, with the status page hidden."""
    magtag.set_text("SAT    TIME    DUR    EL", index=0, auto_refresh=False)
    magtag.set_text("-" * 34, index=1, auto_refresh=False)
    magtag.set_text("", index=STATUS_INDEX, auto_refresh=False)

    print(f"Rendering {len(rows)} rows...")
    for i, (line, state, _pass_info) in enumerate(rows):
        print(f"  row {i}: {repr(line)} ({state})")
        magtag.set_text(line, index=2 + i, auto_refresh=False)
        if state == ACTIVE:
            color = COLOR_ACTIVE
        elif state == RECENT:
            color = COLOR_RECENT
        else:
            color = COLOR_NORMAL
        magtag.set_text_color(color, index=2 + i)
        highlights[i].hidden = state != ACTIVE

    magtag.refresh()


def usb_power_connected():
    """True when the MagTag has USB power (and so can charge) attached."""
    try:
        return bool(supervisor.runtime.usb_connected)
    except AttributeError:
        return False


def render_charge_me(magtag):
    """
    Draw the low-battery page: "Charge Me" in large letters, nothing else.

    This is the only thing drawn in low-battery mode, so no network work has
    happened and there is no stale pass data left on the display.
    """
    print("Rendering charge me page")
    magtag.add_text(
        text_position=(magtag.graphics.display.width // 2,
                       magtag.graphics.display.height // 2),
        text_scale=4,
        text_color=0x000000,
        text_font=terminalio.FONT,
        text_anchor_point=(0.5, 0.5),
    )
    magtag.set_text("Charge Me", index=0, auto_refresh=False)
    magtag.refresh()


def render_status(magtag, highlights, lines):
    """Draw the "last updated and battery state" page on its own."""
    print(f"Rendering status page: {lines}")
    magtag.set_text("", index=0, auto_refresh=False)
    magtag.set_text("", index=1, auto_refresh=False)
    for i in range(MAX_PASSES_SHOWN):
        magtag.set_text("", index=2 + i, auto_refresh=False)
        highlights[i].hidden = True
    magtag.set_text("\n".join(lines), index=STATUS_INDEX, auto_refresh=False)
    magtag.refresh()


def deep_sleep(magtag, sleep_s):
    """
    Deep sleep until ``sleep_s`` elapses or any of the four buttons is pressed.

    The MagTag helper only knows how to set a time alarm, so the button pins are
    released and the alarm module is used directly (see the note in
    ``MagTag.exit_and_deep_sleep``).
    """
    print(f"Sleeping for {sleep_s}s...")
    magtag.peripherals.neopixel_disable = True
    magtag.peripherals.speaker_disable = True

    # A button still held down would trigger its alarm immediately.
    deadline = time.monotonic() + BUTTON_RELEASE_WAIT_S
    while magtag.peripherals.any_button_pressed and time.monotonic() < deadline:
        time.sleep(0.1)

    alarms = [alarm.time.TimeAlarm(monotonic_time=time.monotonic() + sleep_s)]
    try:
        magtag.peripherals.deinit()
        for pin in BUTTON_PINS:
            alarms.append(alarm.pin.PinAlarm(pin=pin, value=False, pull=True))
    except (AttributeError, ValueError) as e:
        print(f"  button wake unavailable ({e}), sleeping on time alone")
    alarm.exit_and_deep_sleep_until_alarms(*alarms)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    magtag = MagTag()
    button_wake = woke_from_button()
    print(f"Boot: button_wake={button_wake}")

    # ── Low battery ───────────────────────────────────────────────────────────
    # Checked before anything else: no APIs are queried and no pass data is
    # drawn until the battery is charged again.
    battery_pct = read_battery_percent(magtag)
    if is_low_battery(battery_pct, usb_power_connected(), LOW_BATTERY_PCT):
        print(f"Low battery ({battery_pct}% <= {LOW_BATTERY_PCT}%), charge me mode")
        render_charge_me(magtag)
        deep_sleep(magtag, LOW_BATTERY_SLEEP_S)

    # ── Layout ────────────────────────────────────────────────────────────────
    highlights = add_row_highlights(magtag)

    magtag.add_text(
        text_position=(4, 4),
        text_scale=1,
        text_color=0x000000,
        text_font=terminalio.FONT,
    )

    magtag.add_text(
        text_position=(4, 16),
        text_scale=1,
        text_color=0x000000,
        text_font=terminalio.FONT,
    )

    for i in range(MAX_PASSES_SHOWN):
        magtag.add_text(
            text_position=(4, ROW_TOP + i * ROW_HEIGHT),
            text_scale=1,
            text_color=0x000000,
            text_font=terminalio.FONT,
        )

    magtag.add_text(
        text_position=(8, 14),
        text_scale=2,
        text_color=0x000000,
        text_font=terminalio.FONT,
        text_anchor_point=(0, 0),
    )

    # ── Status page ───────────────────────────────────────────────────────────
    # Drawn before any network work, so a button press feels responsive.
    # "Updated" is the last time N2YO was queried, which the client reads
    # straight from its flash cache; the offset needed to show it in local time
    # comes from sleep memory. Both are refreshed further down if this cycle
    # queries N2YO again.
    n2yo = N2YOClient(
        magtag.network,
        now_unix,
        days_ahead=DAYS_AHEAD,
        min_elevation_deg=MIN_ELEVATION_DEG,
    )

    shown_lines   = None
    status_expiry = 0.0
    if button_wake:
        shown_lines = build_status_lines(
            n2yo.last_fetch_at, load_utc_offset(), battery_pct
        )
        render_status(magtag, highlights, shown_lines)
        status_expiry = time.monotonic() + STATUS_PAGE_DURATION_S

    magtag.network.connect()

    # ── Time sync ─────────────────────────────────────────────────────────────
    utc_offset_s = sync_time(magtag)
    if clock_synced():
        save_utc_offset(utc_offset_s)

    # ── Fetch passes (with cache and rate-limit circuit-breaker) ──────────────
    all_passes = []
    for norad_id, label, _mode in SATELLITES:
        all_passes.extend(n2yo.get_passes(norad_id, label))
        if n2yo.last_request_made:
            time.sleep(0.5)
    n2yo.save()
    rate_limited = n2yo.rate_limited

    # ── Render ────────────────────────────────────────────────────────────────
    rows = build_display_rows(all_passes, utc_offset_s)

    # The status page is already up if a button woke us; redraw it only when the
    # fresh data changed what it says, then leave it up for the rest of its
    # duration before the pass list comes back.
    if button_wake:
        lines = build_status_lines(
            n2yo.last_fetch_at,
            utc_offset_s if clock_synced() else None,
            battery_pct,
            rate_limited,
        )
        if lines != shown_lines:
            render_status(magtag, highlights, lines)
        remaining = status_expiry - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    render_passes(magtag, rows, highlights)

    if rate_limited:
        sleep_s = 600
    else:
        sleep_s = next_wake_s(
            [(p, state) for _line, state, p in rows if p is not None],
            now_unix(),
            RECENT_RETENTION_S,
            REFRESH_INTERVAL_S,
            min_sleep_s=MIN_SLEEP_S,
        )
    deep_sleep(magtag, sleep_s)


main()
