"""Epoch-agnostic parsing and local date/time formatting helpers."""


TIME_SERVICE_FORMAT = "%s %z %Z"


def parse_time_service_reply(reply):
    """
    Return ``(unix_timestamp, utc_offset_seconds, timezone_abbreviation)``.

    The Adafruit IO strftime endpoint supplies Unix time directly, avoiding a
    local-calendar-to-UTC conversion on the device.
    """
    fields = reply.split()
    if len(fields) < 2:
        raise ValueError("incomplete time service reply")

    unix_ts = int(fields[0])
    tz_str = fields[1]
    if (len(tz_str) != 5 or tz_str[0] not in ("+", "-")
            or not tz_str[1:].isdigit()):
        raise ValueError("invalid UTC offset")

    hours = int(tz_str[1:3])
    minutes = int(tz_str[3:5])
    if hours > 23 or minutes > 59:
        raise ValueError("invalid UTC offset")

    sign = -1 if tz_str[0] == "-" else 1
    utc_offset_s = sign * (hours * 3600 + minutes * 60)
    timezone_abbreviation = fields[2] if len(fields) > 2 else tz_str
    return unix_ts, utc_offset_s, timezone_abbreviation


def unix_to_hhmm(unix_ts, utc_offset_s):
    """Convert a UTC Unix timestamp to a local ``HH:MM`` string."""
    tod = (unix_ts + utc_offset_s) % 86400
    return f"{tod // 3600:02d}:{(tod % 3600) // 60:02d}"


def unix_to_date(unix_ts, utc_offset_s):
    """Convert a UTC Unix timestamp to a local ``YYYY-MM-DD`` string."""
    days = (unix_ts + utc_offset_s) // 86400
    jdn = days + 2440588
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return f"{year}-{month:02d}-{day:02d}"
