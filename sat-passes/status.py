"""Status page content helpers (no hardware dependencies)."""

BATTERY_EMPTY_V = 3.20      # approximate 0% for a single-cell LiPo
BATTERY_FULL_V  = 4.20      # approximate 100% for a single-cell LiPo

LOW_BATTERY_PERCENT = 5     # at or below this, and unplugged, ask for a charge

# Layout of the UTC offset record kept in alarm.sleep_memory: a magic byte so
# leftover memory isn't mistaken for a record, then the offset as four
# big-endian bytes. The last-updated timestamp itself lives in the N2YO cache;
# only the offset needed to render it locally is remembered here.
UTC_OFFSET_MAGIC = 0x53
UTC_OFFSET_LEN   = 1 + 4        # magic + offset


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

    ``time_str`` is ``None`` when the last N2YO query time can't be shown —
    either because no query has ever succeeded, or because the clock hasn't
    been synced yet this boot — in which case the date is omitted too.
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


def pack_utc_offset(utc_offset_s):
    """Encode a UTC offset in seconds as bytes."""
    off = int(utc_offset_s) & 0xFFFFFFFF
    return bytes([
        UTC_OFFSET_MAGIC,
        (off >> 24) & 0xFF, (off >> 16) & 0xFF, (off >> 8) & 0xFF, off & 0xFF,
    ])


def unpack_utc_offset(data):
    """
    Decode ``pack_utc_offset`` output back into a UTC offset in seconds.

    Returns ``None`` for anything that isn't a valid record, so an
    uninitialised or garbled sleep memory simply means "offset not known".
    """
    if data is None or len(data) < UTC_OFFSET_LEN:
        return None
    if data[0] != UTC_OFFSET_MAGIC:
        return None
    off = (data[1] << 24) | (data[2] << 16) | (data[3] << 8) | data[4]
    if off >= 0x80000000:
        off -= 0x100000000
    return off
