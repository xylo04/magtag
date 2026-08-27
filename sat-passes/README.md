# sat-passes

Displays upcoming amateur satellite and ISS pass times on the Adafruit MagTag's
e-ink display. Pass predictions are fetched from the [N2YO API](https://www.n2yo.com/api/)
so no orbital math runs on the device.

## Display layout

```
SAT    TIME    DUR    EL
----------------------------------
ISS    14:32   9m15s   52
AO-91  15:07   7m40s   38
SO-50  16:21   5m02s   14
FO-29  17:55   8m33s   61
AO-92  19:04   6m11s   27
```

- **SAT** — satellite short name
- **TIME** — AOS (acquisition of signal) in local time
- **DUR** — pass duration (LOS − AOS)
- **EL** — maximum elevation in degrees

Rows are styled by pass state:

- **in progress** — white text on a black bar (more than one pass can be
  highlighted at once)
- **finished** — subdued grey text, kept for `RECENT_PASS_RETENTION_S` after LOS
- **upcoming** — plain black text

### Status page

Pressing any of the four buttons wakes the MagTag and immediately shows a
"Waking up..." message, before the battery is even read, so a button press
gets instant feedback rather than a blank screen while things get set up. A
timer wake skips this — it's meant to run unattended, with nobody watching the
display. The pass list is then replaced with a status page for
`STATUS_PAGE_DURATION_S` seconds (default 15), then the pass list returns:

```
Updated 14:05
2026-08-25
Battery 84%
```

**Updated** is the last time the N2YO API was successfully queried — not the
last time the display was refreshed, which happens far more often and is
visible from the pass rows anyway. It comes from the `/n2yo_cache.json` fetch
timestamps, so it survives a power cycle; a cached cycle leaves it unchanged.

The status page is drawn *before* any network work, so a button press is
responsive rather than waiting on the time sync and N2YO lookups. Rendering it
in local time also needs the UTC offset, which is remembered in
`alarm.sleep_memory` across deep sleep; once the refresh finishes, the page is
redrawn if anything on it changed. After a power cycle the offset isn't known
until the time sync lands, so the page briefly reads `Updated unknown`.

`N2YO rate limited` is added as a fourth line when the last refresh was blocked
by the N2YO transaction limit.

### Low battery mode

When the battery is at or below `LOW_BATTERY_PERCENT` (default 5) and the
MagTag is not plugged in, it skips the time and N2YO lookups entirely and shows
only:

```
Charge Me
```

in large letters, so stale pass times can't linger on the e-ink display. It then
sleeps for an hour before re-checking, or until a button is pressed.

## Setup

### 1. Get API keys

**N2YO** — register for free at <https://www.n2yo.com/api/>. Free tier:
100 radio pass lookups/hour. Note: during development, each device reset burns
6 transactions (one per satellite), so the limit is easy to hit while iterating.

**Adafruit IO** — free account at <https://io.adafruit.com/>. Used for DST-aware
time sync on every boot. Key is under **My Key** in the IO dashboard.

### 2. Install CircuitPython libraries

Use [circup](https://github.com/adafruit/circup), Adafruit's library manager:

```bash
pipx install circup          # or: pip install circup
# plug in the MagTag via USB, then:
circup install -r requirements.txt
```

`adafruit_magtag` has a deep dependency tree (portalbase, display_text,
bitmap_font, lis3dh, neopixel, requests, connection_manager, …). circup resolves
all of it from the bundle so you don't have to track it manually.

No font files needed — the code uses CircuitPython's built-in `terminalio.FONT`.

### 3. Configure

```bash
cp settings.toml.example settings.toml
# Edit settings.toml with your credentials and coordinates
```

`settings.toml` is the CircuitPython 8+ standard for device configuration.
Values are read in code via `os.getenv()`.

| Key | Description |
|-----|-------------|
| `CIRCUITPY_WIFI_SSID` / `CIRCUITPY_WIFI_PASSWORD` | Wi-Fi credentials |
| `N2YO_API_KEY` | N2YO API key |
| `ADAFRUIT_AIO_USERNAME` / `ADAFRUIT_AIO_KEY` | Adafruit IO credentials |
| `TIMEZONE` | IANA timezone name (e.g. `"America/Denver"`) |
| `LATITUDE` / `LONGITUDE` / `ALTITUDE_KM` | Observer location (strings) |
| `CACHE_TIMEOUT_S` | Seconds before cached N2YO results are refreshed (default `600`) |
| `CACHE_LOS_RETENTION_S` | Seconds to retain passes after LOS (default `1800`) |
| `RECENT_PASS_RETENTION_S` | Seconds a finished pass stays on the display (default `900`; keep ≤ `CACHE_LOS_RETENTION_S`) |
| `STATUS_PAGE_DURATION_S` | Seconds the status page stays up after a button press (default `15`) |
| `LOW_BATTERY_PERCENT` | Battery percentage at or below which "Charge Me" mode kicks in while unplugged (default `5`) |

DST transitions are handled automatically via Adafruit IO's timezone database —
no manual offset ever needed.

N2YO results are cached in `/n2yo_cache.json` on the device. Fresh results avoid
API requests, while stale results remain available if a refresh fails or is rate
limited. Successful refreshes merge new passes with cached passes, collapse
overlapping rows per satellite to the most recent pass record, and discard
entries after the configured post-LOS retention period.

### 4. Deploy to MagTag

Copy to the `CIRCUITPY/` root:

```
boot.py
code.py
n2yo.py
passes.py
satellites.py
status.py
settings.toml     ← yours, not the example
```

`boot.py` remounts the device filesystem writable for CircuitPython so the
sketch can update `/n2yo_cache.json`. While this is enabled, avoid editing the
`CIRCUITPY` drive from the host computer at the same time the sketch is running.

## Customise satellites

Edit `satellites.py` to add/remove birds. Each entry is:

```python
(NORAD_ID, "LABEL", "radio")
```

Find NORAD IDs at <https://www.n2yo.com/> or <https://celestrak.org/>.

Common ham radio satellites:

| Call / Name      | NORAD | Mode        |
| ---------------- | ----- | ----------- |
| ISS              | 25544 | FM/SSTV/etc |
| SO-50 (SaudiSat) | 27607 | FM          |
| AO-91 (Fox-1B)   | 43017 | FM          |
| AO-92 (Fox-1D)   | 43137 | FM          |
| FO-29            | 24278 | Linear SSB  |
| AO-85 (Fox-1A)   | 40967 | FM          |
| XW-2A            | 40903 | Linear      |

## Tests

The N2YO client, pass selection, and status page tests run on standard Python
without CircuitPython hardware libraries:

```bash
python -m unittest discover -s tests -v
```

## Power

The MagTag deep-sleeps between refreshes. Instead of a fixed cycle, it wakes at
the next moment the display would change — the AOS of a shown pass, its LOS, or
the moment it ages out of the list — across all visible passes, clamped to
between 1 minute and `REFRESH_INTERVAL_S` (default 1 hour). A press on any of
the four buttons also wakes it, to show the status page.
On a 350 mAh LiPo this should run for days between charges. The status page
shows an approximate battery percentage based on the MagTag battery voltage.

## Files

| File                    | Lives on device? | Notes                        |
| ----------------------- | ---------------- | ---------------------------- |
| `boot.py`               | ✅ CIRCUITPY/    | Makes on-device cache writes possible |
| `code.py`               | ✅ CIRCUITPY/    | Main entry point             |
| `n2yo.py`               | ✅ CIRCUITPY/    | N2YO API client and cache    |
| `passes.py`             | ✅ CIRCUITPY/    | Pass selection and wake times |
| `status.py`             | ✅ CIRCUITPY/    | Status page content helpers  |
| `satellites.py`         | ✅ CIRCUITPY/    | Satellite list               |
| `settings.toml`         | ✅ CIRCUITPY/    | Credentials — not in git     |
| `settings.toml.example` | repo only        | Template for settings.toml   |
