import os
import unittest
from unittest import mock

os.environ["RADIO_DRIVER"] = "simulation"

from app import create_app
from radio import RadioController, SimulationDriver, ValidationError


class RadioControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = RadioController("simulation")

    def tearDown(self):
        self.controller.close()

    def test_default_status(self):
        status = self.controller.status()
        self.assertEqual(status["frequency_mhz"], 27.185)
        self.assertEqual(status["mode"], "AM")
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


if __name__ == "__main__":
    unittest.main()
