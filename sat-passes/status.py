"""Status page content helpers (no hardware dependencies)."""

BATTERY_EMPTY_V = 3.20      # approximate 0% for a single-cell LiPo
BATTERY_FULL_V  = 4.20      # approximate 100% for a single-cell LiPo

LOW_BATTERY_PERCENT = 5     # at or below this, and unplugged, ask for a charge


def is_low_battery(battery_pct, usb_connected, threshold=LOW_BATTERY_PERCENT):
    """
    Return True when the device runs on battery at or below ``threshold``.

    An unknown battery reading or a plugged-in device never counts as low, so
    normal operation is the default whenever the state is uncertain.
    """
    if usb_connected or battery_pct is None:
        return False
    return battery_pct <= threshold


def battery_percent(voltage, empty_v=BATTERY_EMPTY_V, full_v=BATTERY_FULL_V):
    """
    Return an approximate battery percentage (0-100) for ``voltage``.

    ``None`` in, ``None`` out, so an unavailable battery reading can be passed
    straight through.
    """
    if voltage is None:
        return None
    pct = int(((voltage - empty_v) / (full_v - empty_v)) * 100 + 0.5)
    if pct < 0:
        return 0
    if pct > 100:
        return 100
    return pct


def status_lines(time_str, date_str, battery_pct, rate_limited=False):
    """Return the lines of the "last updated and battery state" page."""
    lines = [f"Updated {time_str}", date_str]
    if battery_pct is None:
        lines.append("Battery unknown")
    else:
        lines.append(f"Battery {battery_pct}%")
    if rate_limited:
        lines.append("N2YO rate limited")
    return lines
