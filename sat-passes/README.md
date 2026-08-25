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
Updated 14:05 local, 2026-08-25, batt 84%
```

- **SAT** — satellite short name
- **TIME** — AOS (acquisition of signal) in local time
- **DUR** — pass duration (LOS − AOS)
- **EL** — maximum elevation in degrees

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

DST transitions are handled automatically via Adafruit IO's timezone database —
no manual offset ever needed.

### 4. Deploy to MagTag

Copy to the `CIRCUITPY/` root:

```
code.py
satellites.py
settings.toml     ← yours, not the example
```

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

## Power

The MagTag deep-sleeps between refreshes (`REFRESH_INTERVAL_S`, default 1 hour).
On a 350 mAh LiPo this should run for days between charges. The bottom status
line shows an approximate battery percentage based on the MagTag battery voltage.

## Files

| File                    | Lives on device? | Notes                        |
| ----------------------- | ---------------- | ---------------------------- |
| `code.py`               | ✅ CIRCUITPY/    | Main entry point             |
| `satellites.py`         | ✅ CIRCUITPY/    | Satellite list               |
| `settings.toml`         | ✅ CIRCUITPY/    | Credentials — not in git     |
| `settings.toml.example` | repo only        | Template for settings.toml   |
