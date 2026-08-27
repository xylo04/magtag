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
from adafruit_display_text import label
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
from timekeeping import (
    TIME_SERVICE_FORMAT,
    parse_time_service_reply,
    unix_to_date,
    unix_to_hhmm,
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

_boot_unix     = 0  # Unix timestamp captured at last sync
_boot_ticks_ns = 0  # time.monotonic_ns() captured at last sync
_utc_offset    = 0  # DST-aware UTC offset in seconds (e.g. -21600 for MDT)


def now_unix():
    """Current Unix timestamp, derived from sync reference + elapsed ticks."""
    if _boot_unix == 0:
        return 0
    return _boot_unix + (time.monotonic_ns() - _boot_ticks_ns) // 1000000000


def clock_age_s():
    """Seconds since the current wall-clock reference was synced."""
    if _boot_unix == 0:
        return 0
    return (time.monotonic_ns() - _boot_ticks_ns) // 1000000000


# ── Helpers ───────────────────────────────────────────────────────────────────

def sync_time(magtag):
    """
    Sync via the Adafruit IO strftime endpoint.

    Unix time (%s) is requested directly so local calendar fields never need
    to be converted back to UTC on the device. The reply also includes the
    DST-aware UTC offset (%z).
    """
    global _boot_unix, _boot_ticks_ns, _utc_offset
    print("Syncing time via Adafruit IO...")
    try:
        timezone = os.getenv("TIMEZONE", "UTC")
        reply = magtag.network.get_strftime(
            TIME_SERVICE_FORMAT, location=timezone
        )
        _boot_unix, _utc_offset, tz_abbr = parse_time_service_reply(reply)
        _boot_ticks_ns = time.monotonic_ns()

        offset_sign = "+" if _utc_offset >= 0 else "-"
        offset_abs = abs(_utc_offset)
        offset_text = (
            f"{offset_sign}{offset_abs // 3600:02d}:"
            f"{(offset_abs % 3600) // 60:02d}"
        )
        print(
            f"  Synced: {tz_abbr} (UTC{offset_text}), "
            f"unix={_boot_unix}, ticks_ns={_boot_ticks_ns}"
        )
    except Exception as e:
        print(f"  Time sync failed: {e}")
    return _utc_offset


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
    print(
        f"Build display: total={len(all_passes)}, "
        f"now_unix={cur}, clock_age_s={clock_age_s()}"
    )
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
    if not unix_ts or utc_offset_s is None:      # 0 means "never queried"
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


def render_waking_up(magtag):
    """
    Show a quick "Waking up" message right after a button press.

    Battery reads, layout setup, and the status page's own data all take a
    moment to assemble, so this goes up first (button wakes only, never a
    timer wake) to make the response feel immediate; it is removed again
    before the next refresh draws the real content.
    """
    print("Rendering waking up page")
    text_area = label.Label(
        terminalio.FONT,
        text="Waking up...",
        color=0x000000,
        scale=2,
        anchor_point=(0.5, 0.5),
        anchored_position=(
            magtag.graphics.display.width // 2,
            magtag.graphics.display.height // 2,
        ),
    )
    magtag.graphics.root_group.append(text_area)
    magtag.refresh()
    return text_area


def remove_waking_up(magtag, waking_label):
    """Remove the transient "Waking up" label before the next refresh."""
    if waking_label is not None:
        magtag.graphics.root_group.remove(waking_label)


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

    # A timer wake is expected to run unattended, so only a button press (a
    # person waiting on the display) gets the instant "Waking up" feedback.
    waking_label = render_waking_up(magtag) if button_wake else None

    # ── Low battery ───────────────────────────────────────────────────────────
    # Checked before anything else: no APIs are queried and no pass data is
    # drawn until the battery is charged again.
    battery_pct = read_battery_percent(magtag)
    if is_low_battery(battery_pct, usb_power_connected(), LOW_BATTERY_PCT):
        print(f"Low battery ({battery_pct}% <= {LOW_BATTERY_PCT}%), charge me mode")
        remove_waking_up(magtag, waking_label)
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
        remove_waking_up(magtag, waking_label)
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
