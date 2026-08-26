import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from n2yo import N2YOClient


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.closed = False

    def json(self):
        return self.data

    def close(self):
        self.closed = True


class BrokenResponse(FakeResponse):
    def json(self):
        raise ValueError("invalid JSON")


class FakeNetwork:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return self.responses.pop(0)


class N2YOClientTest(unittest.TestCase):
    def write_cache(self, path, satellites):
        with open(path, "w") as cache_file:
            json.dump({"satellites": satellites}, cache_file)

    def test_fresh_cache_avoids_api_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cache.json")
            cached_pass = {
                "label": "ISS", "aos": 1100, "los": 1200, "max_el": 40,
            }
            self.write_cache(path, {
                "25544": {"fetched_at": 900, "passes": [cached_pass]},
            })
            network = FakeNetwork()
            client = N2YOClient(network, lambda: 1000, path)

            self.assertEqual(client.get_passes(25544, "ISS"), [cached_pass])
            self.assertEqual(network.urls, [])
            self.assertFalse(client.last_request_made)

    def test_stale_response_merges_and_prunes_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cache.json")
            self.write_cache(path, {
                "1": {
                    "fetched_at": 100,
                    "passes": [
                        {"label": "SAT", "aos": 900, "los": 950, "max_el": 1},
                        {"label": "SAT", "aos": 1100, "los": 1200, "max_el": 2},
                    ],
                },
            })
            response = FakeResponse({"passes": [
                {"startUTC": 1100, "endUTC": 1200, "maxEl": 20},
                {"startUTC": 1300, "endUTC": 1400, "maxEl": 30},
            ]})
            client = N2YOClient(
                FakeNetwork([response]),
                lambda: 1000,
                path,
                cache_timeout_s=600,
                los_retention_s=30,
            )

            passes = client.get_passes(1, "SAT")
            client.save()

            self.assertEqual([p["max_el"] for p in passes], [20, 30])
            self.assertTrue(response.closed)
            with open(path, "r") as cache_file:
                saved = json.load(cache_file)
            self.assertEqual(saved["satellites"]["1"]["passes"], passes)
            self.assertEqual(saved["satellites"]["1"]["fetched_at"], 1000)

    def test_rate_limit_uses_stale_cache_and_stops_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cache.json")
            first = {"label": "ONE", "aos": 1100, "los": 1200, "max_el": 10}
            second = {"label": "TWO", "aos": 1200, "los": 1300, "max_el": 20}
            self.write_cache(path, {
                "1": {"fetched_at": 1, "passes": [first]},
                "2": {"fetched_at": 1, "passes": [second]},
            })
            network = FakeNetwork([FakeResponse({
                "error": "Transaction limit reached",
            })])
            client = N2YOClient(network, lambda: 1000, path)

            self.assertEqual(client.get_passes(1, "ONE"), [first])
            self.assertEqual(client.get_passes(2, "TWO"), [second])
            self.assertTrue(client.rate_limited)
            self.assertEqual(len(network.urls), 1)

    def test_fetch_failure_closes_response_and_uses_stale_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cache.json")
            cached_pass = {
                "label": "SAT", "aos": 1100, "los": 1200, "max_el": 10,
            }
            self.write_cache(path, {
                "1": {"fetched_at": 1, "passes": [cached_pass]},
            })
            response = BrokenResponse(None)
            client = N2YOClient(FakeNetwork([response]), lambda: 1000, path)

            self.assertEqual(client.get_passes(1, "SAT"), [cached_pass])
            self.assertTrue(response.closed)

    def test_request_uses_observer_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cache.json")
            network = FakeNetwork([FakeResponse({"passes": []})])
            with mock.patch.dict(os.environ, {
                "LATITUDE": "1.2",
                "LONGITUDE": "-3.4",
                "ALTITUDE_KM": "5.6",
                "N2YO_API_KEY": "test-key",
            }):
                client = N2YOClient(
                    network,
                    lambda: 1000,
                    path,
                    days_ahead=2,
                    min_elevation_deg=15,
                )
                self.assertEqual(client.get_passes(42, "SAT"), [])

            self.assertIn(
                "/radiopasses/42/1.2/-3.4/5.6/2/15/&apiKey=test-key",
                network.urls[0],
            )


if __name__ == "__main__":
    unittest.main()
