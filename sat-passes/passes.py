"""Pass selection and wake scheduling helpers (no hardware dependencies)."""

UPCOMING = "upcoming"    # pass has not started yet
ACTIVE   = "active"      # pass is in progress right now
RECENT   = "recent"      # pass has ended but is still worth showing


def classify(pass_info, cur):
    """Return UPCOMING/ACTIVE/RECENT for one pass at time ``cur``."""
    if cur < pass_info["aos"]:
        return UPCOMING
    if cur < pass_info["los"]:
        return ACTIVE
    return RECENT


def select_passes(all_passes, cur, max_shown, recent_retention_s):
    """
    Return up to ``max_shown`` (pass, state) tuples sorted by AOS.

    Passes that ended more than ``recent_retention_s`` ago are dropped;
    everything else — in progress, recently finished, or still to come — is
    eligible for display.
    """
    visible = [p for p in all_passes if p["los"] + recent_retention_s > cur]
    visible.sort(key=lambda p: p["aos"])
    return [(p, classify(p, cur)) for p in visible[:max_shown]]


def next_wake_s(visible, cur, recent_retention_s, max_sleep_s,
                min_sleep_s=60, margin_s=5):
    """
    Seconds to sleep so the device wakes for the next change in the display.

    Each visible pass contributes three interesting moments: its AOS (start
    highlighting it), its LOS (subdue it), and LOS + retention (drop it). The
    soonest moment across *all* visible passes wins, so overlapping passes are
    handled correctly. The result is clamped to [min_sleep_s, max_sleep_s].
    """
    sleep_s = max_sleep_s
    for pass_info, _state in visible:
        for event in (pass_info["aos"],
                      pass_info["los"],
                      pass_info["los"] + recent_retention_s):
            if event > cur:
                sleep_s = min(sleep_s, event - cur + margin_s)
    if sleep_s < min_sleep_s:
        sleep_s = min_sleep_s
    return int(sleep_s)
