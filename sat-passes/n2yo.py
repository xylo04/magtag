"""N2YO API client with a flash-backed satellite pass cache."""

import json
import os


N2YO_BASE = "https://api.n2yo.com/rest/v1/satellite"


class N2YOClient:
    """Fetch and cache N2YO radio pass predictions."""

    def __init__(
        self,
        network,
        now,
        cache_path="/n2yo_cache.json",
        cache_timeout_s=None,
        los_retention_s=None,
        days_ahead=1,
        min_elevation_deg=10,
    ):
        self.network = network
        self.now = now
        self.cache_path = cache_path
        self.cache_timeout_s = (
            int(os.getenv("CACHE_TIMEOUT_S", "600"))
            if cache_timeout_s is None else cache_timeout_s
        )
        self.los_retention_s = (
            int(os.getenv("CACHE_LOS_RETENTION_S", "1800"))
            if los_retention_s is None else los_retention_s
        )
        self.days_ahead = days_ahead
        self.min_elevation_deg = min_elevation_deg
        self.cache = self._load_cache()
        self.cache_dirty = False
        self.rate_limited = False
        self.last_request_made = False

    def _url(self, norad_id):
        lat = os.getenv("LATITUDE", "0")
        lon = os.getenv("LONGITUDE", "0")
        alt = os.getenv("ALTITUDE_KM", "0")
        key = os.getenv("N2YO_API_KEY", "")
        return (
            f"{N2YO_BASE}/radiopasses/{norad_id}"
            f"/{lat}/{lon}/{alt}/{self.days_ahead}/{self.min_elevation_deg}"
            "/&apiKey=" + key
        )

    def _load_cache(self):
        try:
            with open(self.cache_path, "r") as cache_file:
                cache = json.load(cache_file)
            if not isinstance(cache.get("satellites"), dict):
                raise ValueError("invalid cache format")
            return cache
        except (OSError, ValueError, AttributeError) as e:
            print(f"  cache read failed: {e}")
            return {"satellites": {}}

    @property
    def last_fetch_at(self):
        """
        Unix time of the most recent successful N2YO query, or 0 if never.

        Read from the flash cache, so it is available before any network work
        and survives a power cycle.
        """
        newest = 0
        for entry in self.cache["satellites"].values():
            if not isinstance(entry, dict):
                continue
            fetched_at = entry.get("fetched_at", 0)
            if isinstance(fetched_at, (int, float)) and fetched_at > newest:
                newest = int(fetched_at)
        return newest

    def save(self):
        """Persist changed cache entries to flash."""
        if not self.cache_dirty:
            return
        try:
            with open(self.cache_path, "w") as cache_file:
                json.dump(self.cache, cache_file)
            self.cache_dirty = False
        except OSError as e:
            print(f"  cache write failed: {e}")

    def _merge(self, cached, fetched, cur):
        merged = []
        for recency, pass_info in enumerate(cached + fetched):
            try:
                if pass_info["los"] + self.los_retention_s >= cur:
                    is_fetched = recency >= len(cached)
                    replacement = {"pass": pass_info, "is_fetched": is_fetched, "recency": recency}
                    overlaps = [
                        i for i, existing in enumerate(merged)
                        if pass_info["aos"] < existing["pass"]["los"]
                        and existing["pass"]["aos"] < pass_info["los"]
                    ]
                    for i in reversed(overlaps):
                        existing = merged[i]
                        if (
                            replacement["is_fetched"] > existing["is_fetched"]
                            or (
                                replacement["is_fetched"] == existing["is_fetched"]
                                and replacement["recency"] > existing["recency"]
                            )
                        ):
                            merged.pop(i)
                        else:
                            replacement = None
                            break
                    if replacement is not None:
                        merged.append(replacement)
            except (KeyError, TypeError):
                print("  ignoring invalid cached pass")
        merged.sort(key=lambda item: item["pass"]["aos"])
        return [item["pass"] for item in merged]

    def _fetch(self, norad_id, label):
        self.last_request_made = True
        try:
            response = self.network.fetch(self._url(norad_id))
            try:
                data = response.json()
            finally:
                response.close()
        except Exception as e:
            print(f"  fetch error for {label}: {e}")
            return False

        if "error" in data:
            err = str(data["error"])
            print(f"  {label}: API error: {err}")
            err_lower = err.lower()
            if "transaction" in err_lower or "exceeded" in err_lower:
                return None
            return False

        raw = data.get("passes") or []
        print(f"  {label}: {len(raw)} passes")
        passes = []
        for pass_info in raw:
            passes.append({
                "label": label,
                "aos": pass_info["startUTC"],
                "los": pass_info["endUTC"],
                "max_el": pass_info["maxEl"],
            })
        return passes

    def get_passes(self, norad_id, label):
        """Return cached or refreshed passes for one satellite."""
        self.last_request_made = False
        cur = self.now()
        cache_key = str(norad_id)
        entry = self.cache["satellites"].get(cache_key, {})
        if not isinstance(entry, dict):
            entry = {}
        cached_data = entry.get("passes", [])
        if not isinstance(cached_data, list):
            cached_data = []
        cached = self._merge(cached_data, [], cur)
        fetched_at = entry.get("fetched_at", 0)
        if not isinstance(fetched_at, (int, float)):
            fetched_at = 0
        if cache_key in self.cache["satellites"] and cached != cached_data:
            self.cache["satellites"][cache_key] = {
                "fetched_at": fetched_at,
                "passes": cached,
            }
            self.cache_dirty = True

        cache_age = cur - fetched_at
        if 0 <= cache_age < self.cache_timeout_s:
            print(f"  {label}: using cache ({cache_age}s old)")
            return cached

        if self.rate_limited:
            print(f"  Skipping {label} API request (rate limited); using stale cache")
            return cached

        print(f"Fetching {label} ({norad_id})...")
        fetched = self._fetch(norad_id, label)
        if fetched is None:
            self.rate_limited = True
            print("  N2YO rate limit hit — skipping remaining satellites this cycle")
            return cached
        if fetched is False:
            return cached

        merged = self._merge(cached, fetched, cur)
        self.cache["satellites"][cache_key] = {
            "fetched_at": cur,
            "passes": merged,
        }
        self.cache_dirty = True
        return merged
