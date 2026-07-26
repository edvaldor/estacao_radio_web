"""Varredura espectral leve usando o utilitário rtl_power."""

import csv
import math
import os
import shutil
import statistics
import subprocess
import tempfile
import threading
import time

from bands import nearest_channel


class ScanError(RuntimeError):
    """Falha que pode ser mostrada na interface do scanner."""


class ScanCancelled(ScanError):
    """Varredura cancelada pelo usuário."""


class SpectrumScanner:
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._cancelled = False

    @staticmethod
    def available():
        return bool(shutil.which("rtl_power"))

    def cancel(self):
        with self._lock:
            self._cancelled = True
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    def _set_process(self, process):
        with self._lock:
            self._process = process

    def scan(self, plan, sensitivity_db=8.0, duration_seconds=3):
        rtl_power = shutil.which("rtl_power")
        if not rtl_power:
            raise ScanError("O rtl_power não está instalado. Execute novamente o instalador.")

        self._cancelled = False
        descriptor, csv_path = tempfile.mkstemp(prefix="estacao-scan-", suffix=".csv")
        os.close(descriptor)

        start_hz = int(round(plan["start_mhz"] * 1_000_000))
        end_hz = int(round(plan["end_mhz"] * 1_000_000))
        bin_hz = max(1_000, int(round(plan["scan_bin_khz"] * 1_000)))
        command = [
            rtl_power,
            "-f",
            "{}:{}:{}".format(start_hz, end_hz, bin_hz),
            "-i",
            "1",
            "-e",
            "{}s".format(max(2, int(duration_seconds))),
            csv_path,
        ]

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            self._set_process(process)
            try:
                _, error_text = process.communicate(timeout=duration_seconds + 15)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    _, error_text = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    _, error_text = process.communicate()
                raise ScanError("A varredura excedeu o tempo esperado.")

            with self._lock:
                cancelled = self._cancelled
            if cancelled:
                raise ScanCancelled("Varredura cancelada.")
            if process.returncode not in (0, None):
                message = (error_text or "").strip().splitlines()
                detail = message[-1] if message else "rtl_power terminou com erro."
                raise ScanError(detail[-220:])

            return self.parse_csv(csv_path, plan, sensitivity_db)
        except OSError as error:
            raise ScanError("Não foi possível executar o rtl_power: {}".format(error))
        finally:
            self._set_process(None)
            try:
                os.unlink(csv_path)
            except OSError:
                pass

    @staticmethod
    def parse_csv(path, plan, sensitivity_db=8.0, limit=24):
        """Converte o CSV do rtl_power em picos úteis de frequência."""
        bins = {}
        with open(path, "r", encoding="utf-8", errors="replace") as source:
            for row in csv.reader(source):
                if len(row) < 7:
                    continue
                try:
                    low_hz = float(row[2].strip())
                    step_hz = float(row[4].strip())
                except ValueError:
                    continue
                for index, raw_power in enumerate(row[6:]):
                    try:
                        power_db = float(raw_power.strip())
                    except ValueError:
                        continue
                    if not math.isfinite(power_db):
                        continue
                    frequency_mhz = (low_hz + index * step_hz) / 1_000_000.0
                    if not plan["start_mhz"] <= frequency_mhz <= plan["end_mhz"]:
                        continue
                    channel = nearest_channel(frequency_mhz, plan)
                    bins[channel] = max(power_db, bins.get(channel, -999.0))

        if not bins:
            return {
                "noise_floor_db": None,
                "threshold_db": None,
                "candidates": [],
            }

        ordered = sorted(bins.items())
        powers = [power for _, power in ordered]
        noise_floor = statistics.median(powers)
        threshold = noise_floor + float(sensitivity_db)
        candidates = []

        for index, (frequency, power) in enumerate(ordered):
            previous_power = ordered[index - 1][1] if index else -999.0
            next_power = ordered[index + 1][1] if index + 1 < len(ordered) else -999.0
            if power < threshold or power < previous_power or power < next_power:
                continue
            candidates.append(
                {
                    "frequency_mhz": round(frequency, 6),
                    "power_db": round(power, 1),
                    "above_noise_db": round(power - noise_floor, 1),
                }
            )

        candidates.sort(key=lambda item: item["power_db"], reverse=True)
        return {
            "noise_floor_db": round(noise_floor, 1),
            "threshold_db": round(threshold, 1),
            "candidates": candidates[:limit],
        }


def simulated_candidates(plan, station_catalog=None):
    """Resultados determinísticos para demonstração e testes sem dongle."""
    values = []
    if station_catalog and plan["mode"] == "WFM":
        for index, station in enumerate(
            station_catalog.within(plan["start_mhz"], plan["end_mhz"])
        ):
            values.append(
                {
                    "frequency_mhz": station["frequency_mhz"],
                    "power_db": -35.0 - index * 2.5,
                    "above_noise_db": 22.0 - index,
                }
            )
    if not values:
        preset = float(plan["preset_mhz"])
        step = float(plan["step_khz"]) / 1000.0
        values = [
            {
                "frequency_mhz": round(preset, 6),
                "power_db": -42.0,
                "above_noise_db": 18.0,
            },
            {
                "frequency_mhz": round(
                    min(plan["end_mhz"], preset + step * 4), 6
                ),
                "power_db": -49.0,
                "above_noise_db": 11.0,
            },
        ]
    return {
        "noise_floor_db": -60.0,
        "threshold_db": -52.0,
        "candidates": values,
    }
