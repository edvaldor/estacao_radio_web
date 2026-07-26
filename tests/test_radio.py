import os
import tempfile
import time
import unittest

os.environ["RADIO_DRIVER"] = "simulation"

from app import create_app
from radio import RadioController, SimulationDriver, ValidationError
from scanner import SpectrumScanner


class RadioControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = RadioController("simulation")

    def tearDown(self):
        self.controller.close()

    def test_default_status(self):
        status = self.controller.status()
        self.assertEqual(status["frequency_mhz"], 91.9)
        self.assertEqual(status["mode"], "WFM")
        self.assertEqual(status["channel"], "Rádio Capital 91")
        self.assertEqual(status["driver"], "simulation")
        self.assertFalse(status["running"])

    def test_configure_frequency(self):
        status = self.controller.configure(
            {
                "frequency_mhz": 145.500,
                "band": "manual",
                "channel": "Sintonia manual",
                "mode": "NFM",
                "step_khz": 5,
                "volume": 70,
            }
        )
        self.assertEqual(status["frequency_mhz"], 145.500)
        self.assertEqual(status["mode"], "NFM")
        self.assertEqual(status["volume"], 70)

    def test_rejects_frequency_outside_tuner_range(self):
        with self.assertRaises(ValidationError):
            self.controller.configure({"frequency_mhz": 12})

    def test_start_and_stop(self):
        self.assertIsInstance(self.controller.driver, SimulationDriver)
        self.assertTrue(self.controller.start()["running"])
        self.assertFalse(self.controller.stop()["running"])

    def test_frequency_automatically_selects_band_mode_and_station(self):
        status = self.controller.configure(
            {"frequency_mhz": 95.9, "auto_select": True}
        )
        self.assertEqual(status["band"], "fm")
        self.assertEqual(status["mode"], "WFM")
        self.assertEqual(status["step_khz"], 100.0)
        self.assertEqual(status["channel"], "Cia FM")

    def test_air_frequency_automatically_uses_am(self):
        status = self.controller.configure(
            {"frequency_mhz": 121.5, "auto_select": True}
        )
        self.assertEqual(status["band"], "air")
        self.assertEqual(status["mode"], "AM")
        self.assertEqual(status["step_khz"], 25.0)

    def test_simulation_scanner_tunes_a_candidate(self):
        self.controller.start_scan({"band": "fm", "sensitivity_db": 8})
        deadline = time.time() + 2
        status = self.controller.status()
        while status["scanner"]["phase"] == "scanning" and time.time() < deadline:
            time.sleep(0.05)
            status = self.controller.status()
        self.assertEqual(status["scanner"]["phase"], "listening")
        self.assertGreater(len(status["scanner"]["candidates"]), 0)
        self.assertTrue(status["running"])
        next_status = self.controller.scan_next(1)
        self.assertEqual(next_status["scanner"]["current_index"], 1)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.controller = RadioController("simulation")
        self.app = create_app(self.controller)
        self.client = self.app.test_client()

    def tearDown(self):
        self.controller.close()

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_manual_tuning(self):
        response = self.client.post(
            "/api/config",
            json={
                "frequency_mhz": 121.500,
                "band": "manual",
                "channel": "Sintonia manual",
                "mode": "AM",
                "step_khz": 25,
                "volume": 65,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["frequency_mhz"], 121.500)

    def test_scanner_api(self):
        response = self.client.post(
            "/api/scanner/start",
            json={"band": "cb", "sensitivity_db": 8},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["scanner"]["active"])


class ScannerParserTests(unittest.TestCase):
    def test_parse_rtl_power_csv_finds_peak_above_noise(self):
        plan = {
            "start_mhz": 100.0,
            "end_mhz": 100.4,
            "step_khz": 100.0,
        }
        row = "2026-01-01, 12:00:00, 100000000, 100400000, 100000, 1, -60, -59, -30, -61, -62\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(row)
            path = handle.name
        try:
            result = SpectrumScanner.parse_csv(path, plan, sensitivity_db=8)
        finally:
            os.unlink(path)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["frequency_mhz"], 100.2)


if __name__ == "__main__":
    unittest.main()
