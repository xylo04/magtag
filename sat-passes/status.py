"""Status page content helpers (no hardware dependencies)."""

BATTERY_EMPTY_V = 3.20      # approximate 0% for a single-cell LiPo
BATTERY_FULL_V  = 4.20      # approximate 100% for a single-cell LiPo

LOW_BATTERY_PERCENT = 5     # at or below this, and unplugged, ask for a charge

# Layout of the "last updated" record kept in alarm.sleep_memory: a magic byte
# so leftover memory isn't mistaken for a record, then the Unix timestamp and
# the UTC offset, both as four big-endian bytes.
LAST_UPDATED_MAGIC = 0x53
LAST_UPDATED_LEN   = 1 + 4 + 4      # magic + timestamp + offset


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
    """
    Return the lines of the "last updated and battery state" page.

    ``time_str`` is ``None`` when no previous update is known (for example on
    the first boot after a power cycle), in which case the date is omitted too.
    """
    if time_str is None:
        lines = ["Updated unknown"]
    else:
        lines = [f"Updated {time_str}", date_str]
    if battery_pct is None:
        lines.append("Battery unknown")
    else:
        lines.append(f"Battery {battery_pct}%")
    if rate_limited:
        lines.append("N2YO rate limited")
    return lines


def pack_last_updated(unix_ts, utc_offset_s):
    """Encode a last-updated timestamp and UTC offset as bytes."""
    ts  = int(unix_ts) & 0xFFFFFFFF
    off = int(utc_offset_s) & 0xFFFFFFFF
    return bytes([
        LAST_UPDATED_MAGIC,
        (ts >> 24) & 0xFF, (ts >> 16) & 0xFF, (ts >> 8) & 0xFF, ts & 0xFF,
        (off >> 24) & 0xFF, (off >> 16) & 0xFF, (off >> 8) & 0xFF, off & 0xFF,
    ])


def unpack_last_updated(data):
    """
    Decode ``pack_last_updated`` output back into ``(unix_ts, utc_offset_s)``.

    Returns ``(None, None)`` for anything that isn't a valid record, so an
    uninitialised or garbled sleep memory simply means "never updated".
    """
    if data is None or len(data) < LAST_UPDATED_LEN:
        return (None, None)
    if data[0] != LAST_UPDATED_MAGIC:
        return (None, None)
    ts  = (data[1] << 24) | (data[2] << 16) | (data[3] << 8) | data[4]
    off = (data[5] << 24) | (data[6] << 16) | (data[7] << 8) | data[8]
    if off >= 0x80000000:
        off -= 0x100000000
    if ts == 0:
        return (None, None)
    return (ts, off)
