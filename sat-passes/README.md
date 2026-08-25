# sat-passes

Displays upcoming amateur satellite and ISS pass times on the Adafruit MagTag's
e-ink display. Pass predictions are fetched from the
[N2YO API](https://www.n2yo.com/api/) so no orbital math runs on the device.

## Display layout

```
SAT    TIME   DUR     MAX EL
──────────────────────────────────────
ISS    14:32   9m15s    52°
AO-91  15:07   7m40s    38°
SO-50  16:21   5m02s    14°
FO-29  17:55   8m33s    61°
Updated 14:05 local
```

- **SAT** — satellite short name
- **TIME** — AOS (acquisition of signal) in local time
- **DUR** — pass duration (LOS − AOS)
- **MAX EL** — maximum elevation in degrees

## Setup

### 1. Get an N2YO API key

Register for free at <https://www.n2yo.com/api/>. Free tier: 1,000 transactions/hour.
No other API keys are needed.

### 2. Install CircuitPython libraries

Use [circup](https://github.com/adafruit/circup), Adafruit's library manager,
to install all dependencies automatically:

```bash
pip install circup
# plug in the MagTag via USB, then:
circup install -r requirements.txt
```

`adafruit_magtag` has a deep dependency tree (portalbase, display_text,
bitmap_font, lis3dh, neopixel, requests, connection_manager, …). circup resolves
all of it from the bundle so you don't have to track it manually.

You'll also need the `Arial-Bold-12.bdf` font in `CIRCUITPY/fonts/` — grab it
from the [Adafruit CircuitPython Bundle](https://github.com/adafruit/Adafruit_CircuitPython_Bundle)
or the MagTag learn guide assets.

### 3. Configure

```bash
cp secrets.py.example secrets.py
# Edit secrets.py with your Wi-Fi credentials, API key, and coordinates
```

Required fields in `secrets.py`:

| Key | Description |
|-----|-------------|
| `ssid` / `password` | Wi-Fi credentials |
| `n2yo_api_key` | N2YO API key |
| `timezone` | IANA timezone name (e.g. `"America/Denver"`) |
| `latitude` / `longitude` / `altitude_km` | Observer location |

Time is synced from [WorldTimeAPI](https://worldtimeapi.org/) on every boot using
the IANA timezone name. DST transitions are handled automatically — no manual
offset config needed, ever.

### 4. Deploy to MagTag

Copy to the `CIRCUITPY/` root:

```
code.py
satellites.py
secrets.py        ← yours, not the example
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
On a 350 mAh LiPo this should run for days between charges.

## Files

| File                 | Lives on device? | Notes                    |
| -------------------- | ---------------- | ------------------------ |
| `code.py`            | ✅ CIRCUITPY/    | Main entry point         |
| `satellites.py`      | ✅ CIRCUITPY/    | Satellite list           |
| `secrets.py`         | ✅ CIRCUITPY/    | Credentials — not in git |
| `secrets.py.example` | repo only        | Template for secrets     |
