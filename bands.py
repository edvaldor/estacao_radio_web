"""Planos de banda e catálogo local de emissoras.

O catálogo é propositalmente um arquivo JSON simples: ele funciona sem
internet e pode ser corrigido pelo proprietário da estação.
"""

import json
from pathlib import Path


BAND_PLANS = {
    "fm": {
        "label": "FM comercial",
        "start_mhz": 87.5,
        "end_mhz": 108.0,
        "mode": "NFM",
        "step_khz": 100.0,
        "preset_mhz": 91.9,
        "channel": "FM comercial",
        "scan_bin_khz": 50.0,
    },
    "air": {
        "label": "Aeronáutica",
        "start_mhz": 118.0,
        "end_mhz": 136.975,
        "mode": "AM",
        "step_khz": 25.0,
        "preset_mhz": 121.5,
        "channel": "Emergência aeronáutica",
        "scan_bin_khz": 12.5,
    },
    "vhf": {
        "label": "Radioamador VHF",
        "start_mhz": 144.0,
        "end_mhz": 148.0,
        "mode": "NFM",
        "step_khz": 12.5,
        "preset_mhz": 145.5,
        "channel": "Chamada VHF",
        "scan_bin_khz": 6.25,
    },
    "uhf": {
        "label": "Radioamador UHF",
        "start_mhz": 430.0,
        "end_mhz": 440.0,
        "mode": "NFM",
        "step_khz": 12.5,
        "preset_mhz": 433.5,
        "channel": "Chamada UHF",
        "scan_bin_khz": 6.25,
    },
    "cb": {
        "label": "PX / CB 11 m",
        "start_mhz": 26.965,
        "end_mhz": 27.405,
        "mode": "AM",
        "step_khz": 10.0,
        "preset_mhz": 27.185,
        "channel": "PX · Canal 19",
        "scan_bin_khz": 5.0,
    },
}


def public_band_plans():
    """Retorna apenas dados seguros e úteis para a interface."""
    return {key: dict(value) for key, value in BAND_PLANS.items()}


def infer_band(frequency_mhz):
    """Infere banda, modo e passo a partir da frequência."""
    value = float(frequency_mhz)
    for key, plan in BAND_PLANS.items():
        if plan["start_mhz"] <= value <= plan["end_mhz"]:
            return key, plan
    return "manual", None


def nearest_channel(frequency_mhz, plan):
    """Arredonda uma frequência para a grade de canais da banda."""
    step_mhz = float(plan["step_khz"]) / 1000.0
    start = float(plan["start_mhz"])
    slots = round((float(frequency_mhz) - start) / step_mhz)
    return round(start + slots * step_mhz, 6)


class StationCatalog:
    """Catálogo de nomes de emissoras FM, recarregado quando o JSON muda."""

    def __init__(self, path=None):
        default_path = Path(__file__).resolve().parent / "config" / "stations.json"
        self.path = Path(path or default_path)
        self._mtime = None
        self._stations = []

    def _load(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._stations = []
            self._mtime = None
            return

        if self._mtime == mtime:
            return

        try:
            content = json.loads(self.path.read_text(encoding="utf-8"))
            stations = content.get("stations", content)
            self._stations = [
                {
                    "frequency_mhz": float(item["frequency_mhz"]),
                    "name": str(item["name"]).strip()[:80],
                    "city": str(item.get("city", "")).strip()[:80],
                }
                for item in stations
                if item.get("name")
            ]
            self._mtime = mtime
        except (OSError, ValueError, TypeError, KeyError):
            self._stations = []
            self._mtime = mtime

    def lookup(self, frequency_mhz, tolerance_mhz=0.055):
        self._load()
        frequency = float(frequency_mhz)
        if not self._stations:
            return None
        nearest = min(
            self._stations,
            key=lambda item: abs(item["frequency_mhz"] - frequency),
        )
        if abs(nearest["frequency_mhz"] - frequency) <= tolerance_mhz:
            return dict(nearest)
        return None

    def within(self, start_mhz, end_mhz):
        self._load()
        return [
            dict(item)
            for item in self._stations
            if float(start_mhz) <= item["frequency_mhz"] <= float(end_mhz)
        ]
