"""Controle do RTL-SDR, áudio, medição em tempo real e scanner."""

import math
import os
import queue
import random
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from array import array
from dataclasses import asdict, dataclass, replace

from bands import BAND_PLANS, StationCatalog, infer_band, public_band_plans
from scanner import ScanCancelled, ScanError, SpectrumScanner, simulated_candidates


ALLOWED_MODES = {"AM", "NFM", "WFM"}
MIN_FREQUENCY_MHZ = 24.0
MAX_FREQUENCY_MHZ = 1766.0
_AUDIO_STREAM_END = object()


def wav_stream_header(sample_rate=48000, channels=1, bits_per_sample=16):
    """Cabeçalho WAV para um fluxo PCM contínuo reproduzível pelo navegador."""
    block_align = channels * bits_per_sample // 8
    byte_rate = sample_rate * block_align
    data_size = 0x7FFFF000
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )


class RadioError(RuntimeError):
    """Erro que pode ser apresentado ao usuário da estação."""


class ValidationError(RadioError):
    """Configuração enviada pela interface é inválida."""


@dataclass
class RadioConfig:
    frequency_mhz: float = 91.9
    band: str = "fm"
    channel: str = "Rádio Capital 91"
    mode: str = "NFM"
    step_khz: float = 100.0
    volume: int = 65


class BaseDriver:
    name = "unavailable"

    def start(self, config):
        raise RadioError("O receptor RTL-SDR não está disponível.")

    def stop(self):
        return None

    def set_volume(self, volume):
        return None

    def is_alive(self):
        return False

    def signal_metrics(self):
        return {"percent": 0.0, "dbfs": -90.0, "source": "unavailable"}

    def audio_chunks(self):
        raise RadioError("O áudio no navegador exige um receptor RTL-SDR ativo.")


class SimulationDriver(BaseDriver):
    name = "simulation"

    def __init__(self):
        self.running = False
        self.signal = 12.0

    def start(self, config):
        self.running = True

    def stop(self):
        self.running = False

    def is_alive(self):
        return self.running

    def signal_metrics(self):
        target = 55.0 if self.running else 8.0
        self.signal += (target - self.signal) * 0.22
        self.signal += random.uniform(-4.0, 4.5) if self.running else random.uniform(-1.0, 1.0)
        self.signal = max(0.0, min(100.0, self.signal))
        return {
            "percent": round(self.signal, 1),
            "dbfs": round(-78.0 + self.signal * 0.68, 1),
            "source": "simulation",
        }


class UnavailableDriver(BaseDriver):
    name = "unavailable"

    def __init__(self, reason):
        self.reason = reason

    def start(self, config):
        raise RadioError(self.reason)


class RTLFMDriver(BaseDriver):
    """Executa rtl_fm e mede o PCM antes de enviá-lo ao ALSA."""

    name = "rtl_fm"

    def __init__(self, rtl_fm_path, aplay_path):
        self.rtl_fm_path = rtl_fm_path
        self.aplay_path = aplay_path
        self.rtl_process = None
        self.audio_process = None
        self.rtl_log = None
        self.audio_log = None
        self.audio_thread = None
        self.audio_stop = threading.Event()
        self.metrics_lock = threading.Lock()
        self.subscribers_lock = threading.RLock()
        self.audio_subscribers = set()
        self.signal_percent = 0.0
        self.signal_dbfs = -90.0

    @staticmethod
    def probe_device():
        rtl_test_path = shutil.which("rtl_test")
        if not rtl_test_path:
            return True
        try:
            result = subprocess.run(
                [rtl_test_path, "-t"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                timeout=5,
                check=False,
            )
            output = result.stdout or ""
            return "Found 1 device" in output or "Using device 0" in output
        except subprocess.TimeoutExpired as error:
            output = error.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return "Found 1 device" in output or "Using device 0" in output
        except OSError:
            return False

    def _radio_command(self, config):
        if config.mode == "AM":
            rtl_mode, sample_rate, extra = "am", "120000", ["-E", "dc"]
        elif config.mode == "NFM":
            rtl_mode, sample_rate, extra = "fm", "240000", ["-E", "dc"]
        elif config.mode == "WFM":
            rtl_mode, sample_rate, extra = "wbfm", "170000", ["-E", "deemp"]
        else:
            raise RadioError("O rtl_fm recebe AM, NFM e WFM.")

        return [
            self.rtl_fm_path,
            "-f",
            str(int(round(config.frequency_mhz * 1_000_000))),
            "-M",
            rtl_mode,
            "-s",
            sample_rate,
            "-r",
            "48000",
        ] + extra + ["-"]

    def _audio_command(self):
        command = [
            self.aplay_path,
            "-q",
            "-r",
            "48000",
            "-f",
            "S16_LE",
            "-c",
            "1",
        ]
        device = os.environ.get("RADIO_AUDIO_DEVICE", "").strip()
        if device:
            command.extend(["-D", device])
        return command

    @staticmethod
    def _read_log(log_file):
        if not log_file:
            return ""
        try:
            log_file.flush()
            log_file.seek(0)
            return log_file.read().decode("utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return ""

    def _measure(self, chunk):
        samples = array("h")
        usable = len(chunk) - (len(chunk) % 2)
        if not usable:
            return
        samples.frombytes(chunk[:usable])
        if not samples:
            return
        mean_square = sum(float(sample) * sample for sample in samples) / len(samples)
        rms = math.sqrt(mean_square)
        dbfs = 20.0 * math.log10(max(rms, 1.0) / 32768.0)
        # Escala relativa: -72 dBFS = 0%; -12 dBFS = 100%.
        percent = max(0.0, min(100.0, (dbfs + 72.0) * (100.0 / 60.0)))
        with self.metrics_lock:
            self.signal_dbfs += (dbfs - self.signal_dbfs) * 0.28
            self.signal_percent += (percent - self.signal_percent) * 0.28

    def _pump_audio(self):
        rtl_stdout = self.rtl_process.stdout if self.rtl_process else None
        audio_stdin = self.audio_process.stdin if self.audio_process else None
        if not rtl_stdout or not audio_stdin:
            return
        try:
            while not self.audio_stop.is_set():
                chunk = rtl_stdout.read(8192)
                if not chunk:
                    break
                self._measure(chunk)
                self._publish_audio(chunk)
                audio_stdin.write(chunk)
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            try:
                audio_stdin.close()
            except (OSError, ValueError):
                pass

    def _publish_audio(self, chunk):
        """Entrega o mesmo PCM ao ALSA e a cada navegador conectado."""
        with self.subscribers_lock:
            subscribers = list(self.audio_subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(chunk)
            except queue.Full:
                # Mantém o áudio recente; um navegador lento não pode travar o rádio.
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(chunk)
                except queue.Full:
                    pass

    def _close_audio_subscribers(self):
        with self.subscribers_lock:
            subscribers = list(self.audio_subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(_AUDIO_STREAM_END)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(_AUDIO_STREAM_END)
                except queue.Full:
                    pass

    def audio_chunks(self):
        subscriber = queue.Queue(maxsize=48)
        with self.subscribers_lock:
            self.audio_subscribers.add(subscriber)
        try:
            while True:
                try:
                    chunk = subscriber.get(timeout=8)
                except queue.Empty:
                    if not self.is_alive():
                        break
                    continue
                if chunk is _AUDIO_STREAM_END:
                    break
                yield chunk
        finally:
            with self.subscribers_lock:
                self.audio_subscribers.discard(subscriber)

    def start(self, config):
        self.stop()
        self.rtl_log = tempfile.TemporaryFile()
        self.audio_log = tempfile.TemporaryFile()
        self.audio_stop.clear()
        with self.metrics_lock:
            self.signal_percent = 0.0
            self.signal_dbfs = -90.0

        try:
            self.rtl_process = subprocess.Popen(
                self._radio_command(config),
                stdout=subprocess.PIPE,
                stderr=self.rtl_log,
                start_new_session=True,
            )
            self.audio_process = subprocess.Popen(
                self._audio_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self.audio_log,
                start_new_session=True,
            )
            self.audio_thread = threading.Thread(
                target=self._pump_audio,
                name="radio-audio-meter",
                daemon=True,
            )
            self.audio_thread.start()
            time.sleep(0.45)

            if self.rtl_process.poll() is not None or self.audio_process.poll() is not None:
                details = (
                    self._read_log(self.rtl_log)
                    or self._read_log(self.audio_log)
                    or "O processo do receptor terminou inesperadamente."
                )
                self.stop()
                raise RadioError("Não foi possível iniciar o rádio: " + details[-280:])
            self.set_volume(config.volume)
        except OSError as error:
            self.stop()
            raise RadioError("Falha ao executar o receptor: " + str(error))

    def set_volume(self, volume):
        amixer = shutil.which("amixer")
        if not amixer:
            return
        preferred = os.environ.get("RADIO_AUDIO_MIXER", "").strip()
        mixers = [preferred] if preferred else []
        mixers.extend(["PCM", "Master", "Headphone"])
        card = os.environ.get("RADIO_AUDIO_CARD", "").strip()
        attempted = set()
        for mixer in mixers:
            if not mixer or mixer in attempted:
                continue
            attempted.add(mixer)
            command = [amixer]
            if card:
                command.extend(["-c", card])
            command.extend(["sset", mixer, "{}%".format(int(volume)), "unmute"])
            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                return

    @staticmethod
    def _terminate(process):
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.5)

    def stop(self):
        self.audio_stop.set()
        self._close_audio_subscribers()
        self._terminate(self.rtl_process)
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        self._terminate(self.audio_process)
        self.audio_thread = None
        self.audio_process = None
        self.rtl_process = None
        for log_file in (self.rtl_log, self.audio_log):
            if log_file:
                try:
                    log_file.close()
                except OSError:
                    pass
        self.rtl_log = None
        self.audio_log = None

    def is_alive(self):
        return bool(
            self.rtl_process
            and self.audio_process
            and self.rtl_process.poll() is None
            and self.audio_process.poll() is None
        )

    def signal_metrics(self):
        with self.metrics_lock:
            return {
                "percent": round(self.signal_percent, 1),
                "dbfs": round(self.signal_dbfs, 1),
                "source": "audio_rms",
            }


def select_driver(preference):
    preference = (preference or "auto").strip().lower()
    if preference == "simulation":
        return SimulationDriver()
    if preference not in {"auto", "rtl_fm"}:
        return UnavailableDriver(
            "RADIO_DRIVER inválido. Use auto, simulation ou rtl_fm."
        )
    rtl_fm_path = shutil.which("rtl_fm")
    aplay_path = shutil.which("aplay")
    commands_ready = bool(rtl_fm_path and aplay_path)
    device_ready = commands_ready and RTLFMDriver.probe_device()
    if device_ready:
        return RTLFMDriver(rtl_fm_path, aplay_path)
    if preference == "rtl_fm":
        reason = (
            "Instale os pacotes rtl-sdr e alsa-utils."
            if not commands_ready
            else "Nenhum dongle RTL-SDR foi encontrado."
        )
        return UnavailableDriver(reason)
    return SimulationDriver()


class RadioController:
    def __init__(self, driver_preference="auto", station_catalog=None):
        self.lock = threading.RLock()
        self.catalog = station_catalog or StationCatalog()
        self.config = RadioConfig()
        self.driver = select_driver(driver_preference)
        self.running = False
        self.last_error = None
        self.scanner = SpectrumScanner()
        self.scan_generation = 0
        self.scan_thread = None
        self.scan_state = self._empty_scan_state()
        self._refresh_channel()

    @staticmethod
    def _empty_scan_state():
        return {
            "active": False,
            "phase": "idle",
            "band": None,
            "sensitivity_db": 8.0,
            "progress": 0,
            "message": "Scanner pronto.",
            "candidates": [],
            "current_index": -1,
            "noise_floor_db": None,
            "threshold_db": None,
        }

    @staticmethod
    def _number(payload, key, current):
        if key not in payload:
            return current
        try:
            return float(payload[key])
        except (TypeError, ValueError):
            raise ValidationError("O campo {} deve ser numérico.".format(key))

    def _refresh_channel(self):
        band, plan = infer_band(self.config.frequency_mhz)
        if band == "fm":
            station = self.catalog.lookup(self.config.frequency_mhz)
            self.config.channel = (
                station["name"]
                if station
                else "FM {:.1f} MHz".format(self.config.frequency_mhz)
            )
        elif plan:
            self.config.channel = plan["channel"]
        else:
            self.config.channel = "Sintonia manual"

    def _validated_config(self, payload):
        config = replace(self.config)
        config.frequency_mhz = self._number(payload, "frequency_mhz", config.frequency_mhz)
        if not MIN_FREQUENCY_MHZ <= config.frequency_mhz <= MAX_FREQUENCY_MHZ:
            raise ValidationError(
                "A frequência deve ficar entre {:.3f} e {:.3f} MHz.".format(
                    MIN_FREQUENCY_MHZ, MAX_FREQUENCY_MHZ
                )
            )
        config.frequency_mhz = round(config.frequency_mhz, 6)
        auto_select = bool(payload.get("auto_select", False))
        if auto_select:
            band, plan = infer_band(config.frequency_mhz)
            config.band = band
            if plan:
                config.mode = plan["mode"]
                config.step_khz = plan["step_khz"]
        else:
            if "band" in payload:
                band = str(payload["band"]).strip()
                config.band = band if band in BAND_PLANS or band == "manual" else "manual"
            if "mode" in payload:
                mode = str(payload["mode"]).upper().strip()
                if mode not in ALLOWED_MODES:
                    raise ValidationError("Modo de recepção inválido.")
                config.mode = mode
            config.step_khz = self._number(payload, "step_khz", config.step_khz)

        # Preferência desta estação: FM comercial permanece em NFM.
        if config.band == "fm":
            config.mode = "NFM"

        if not 0.1 <= config.step_khz <= 1000:
            raise ValidationError("O passo deve ficar entre 0,1 e 1000 kHz.")
        if "volume" in payload:
            try:
                config.volume = int(payload["volume"])
            except (TypeError, ValueError):
                raise ValidationError("O volume deve ser um número inteiro.")
            if not 0 <= config.volume <= 100:
                raise ValidationError("O volume deve ficar entre 0 e 100%.")
        return config

    def configure(self, payload):
        with self.lock:
            new_config = self._validated_config(payload or {})
            receiver_changed = (
                new_config.frequency_mhz != self.config.frequency_mhz
                or new_config.mode != self.config.mode
            )
            volume_changed = new_config.volume != self.config.volume
            self.config = new_config
            self._refresh_channel()
            if volume_changed:
                self.driver.set_volume(self.config.volume)
            if self.running and receiver_changed:
                self._deactivate_scanner()
                try:
                    self.driver.start(self.config)
                    self.last_error = None
                except RadioError as error:
                    self.running = False
                    self.last_error = str(error)
                    raise
            return self.status()

    def apply_band(self, band):
        if band not in BAND_PLANS:
            raise ValidationError("Banda inválida.")
        plan = BAND_PLANS[band]
        return self.configure(
            {
                "frequency_mhz": plan["preset_mhz"],
                "band": band,
                "mode": plan["mode"],
                "step_khz": plan["step_khz"],
            }
        )

    def start(self):
        with self.lock:
            self._deactivate_scanner()
            if self.running and self.driver.is_alive():
                return self.status()
            try:
                self.driver.start(self.config)
                self.running = True
                self.last_error = None
            except RadioError as error:
                self.running = False
                self.last_error = str(error)
                raise
            return self.status()

    def stop(self):
        with self.lock:
            self._deactivate_scanner()
            self.driver.stop()
            self.running = False
            return self.status()

    def browser_audio_stream(self):
        """Obtém PCM ao vivo sem tomar o dongle do processo principal."""
        with self.lock:
            if not self.running or not self.driver.is_alive():
                raise RadioError("Inicie o receptor antes de ouvir no navegador.")
            if self.driver.name != "rtl_fm":
                raise RadioError(
                    "O áudio no navegador fica disponível quando o RTL-SDR está conectado."
                )
            driver = self.driver
        return driver.audio_chunks()

    def _deactivate_scanner(self):
        if self.scan_state["active"]:
            self.scan_generation += 1
            self.scanner.cancel()
            self.scan_state["active"] = False
            self.scan_state["phase"] = "idle"
            self.scan_state["message"] = "Scanner parado."

    def start_scan(self, payload):
        band = str((payload or {}).get("band", self.config.band)).strip()
        if band not in BAND_PLANS:
            raise ValidationError("Escolha uma banda antes de iniciar o scanner.")
        try:
            sensitivity = float((payload or {}).get("sensitivity_db", 8.0))
        except (TypeError, ValueError):
            raise ValidationError("A sensibilidade do scanner deve ser numérica.")
        if not 3.0 <= sensitivity <= 25.0:
            raise ValidationError("Use sensibilidade entre 3 e 25 dB.")

        with self.lock:
            self.scan_generation += 1
            generation = self.scan_generation
            self.scanner.cancel()
            self.driver.stop()
            self.running = False
            self.scan_state = self._empty_scan_state()
            self.scan_state.update(
                {
                    "active": True,
                    "phase": "scanning",
                    "band": band,
                    "sensitivity_db": sensitivity,
                    "progress": 12,
                    "message": "Medindo a banda {}…".format(BAND_PLANS[band]["label"]),
                }
            )
            self.scan_thread = threading.Thread(
                target=self._scan_worker,
                args=(generation, band, sensitivity),
                name="radio-spectrum-scan",
                daemon=True,
            )
            self.scan_thread.start()
            return self.status()

    def _scan_worker(self, generation, band, sensitivity):
        plan = BAND_PLANS[band]
        try:
            if self.driver.name == "simulation":
                time.sleep(0.35)
                result = simulated_candidates(plan, self.catalog)
            else:
                result = self.scanner.scan(plan, sensitivity_db=sensitivity)
            with self.lock:
                if generation != self.scan_generation:
                    return
                candidates = [
                    self._describe_candidate(item, band)
                    for item in result["candidates"]
                ]
                self.scan_state.update(
                    {
                        "progress": 100,
                        "candidates": candidates,
                        "noise_floor_db": result["noise_floor_db"],
                        "threshold_db": result["threshold_db"],
                    }
                )
                if not candidates:
                    self.scan_state.update(
                        {
                            "phase": "empty",
                            "message": "Nenhum pico superou o limite. Reduza a sensibilidade e tente de novo.",
                        }
                    )
                    return
                self.scan_state["phase"] = "listening"
                self.scan_state["message"] = "{} sinais encontrados.".format(len(candidates))
                self._tune_scan_candidate(0)
        except ScanCancelled:
            return
        except (ScanError, RadioError) as error:
            with self.lock:
                if generation != self.scan_generation:
                    return
                self.last_error = str(error)
                self.scan_state.update(
                    {
                        "phase": "error",
                        "progress": 100,
                        "message": str(error),
                    }
                )

    def _describe_candidate(self, item, band):
        candidate = dict(item)
        frequency = candidate["frequency_mhz"]
        if band == "fm":
            station = self.catalog.lookup(frequency)
            candidate["name"] = station["name"] if station else "FM {:.1f}".format(frequency)
        else:
            candidate["name"] = "{} {:.3f}".format(BAND_PLANS[band]["label"], frequency)
        return candidate

    def _tune_scan_candidate(self, index):
        candidates = self.scan_state["candidates"]
        if not candidates:
            raise ValidationError("O scanner ainda não encontrou sinais.")
        index %= len(candidates)
        candidate = candidates[index]
        band = self.scan_state["band"]
        plan = BAND_PLANS[band]
        self.config = replace(
            self.config,
            frequency_mhz=candidate["frequency_mhz"],
            band=band,
            mode=plan["mode"],
            step_khz=plan["step_khz"],
        )
        self._refresh_channel()
        self.driver.start(self.config)
        self.running = True
        self.last_error = None
        self.scan_state["current_index"] = index
        self.scan_state["message"] = "Ouvindo {} de {}.".format(index + 1, len(candidates))

    def scan_next(self, direction=1):
        with self.lock:
            if self.scan_state["phase"] != "listening":
                raise ValidationError("Aguarde a varredura terminar.")
            try:
                offset = 1 if int(direction) >= 0 else -1
            except (TypeError, ValueError):
                offset = 1
            self._tune_scan_candidate(self.scan_state["current_index"] + offset)
            return self.status()

    def stop_scan(self):
        with self.lock:
            self._deactivate_scanner()
            if not self.running:
                try:
                    self.driver.start(self.config)
                    self.running = True
                except RadioError:
                    self.running = False
            return self.status()

    def status(self):
        with self.lock:
            if self.running and not self.driver.is_alive():
                self.running = False
                self.last_error = "O processo de recepção foi encerrado."
            metrics = self.driver.signal_metrics()
            result = asdict(self.config)
            result.update(
                {
                    "running": self.running,
                    "driver": self.driver.name,
                    "signal_percent": metrics["percent"],
                    "signal_dbfs": metrics["dbfs"],
                    "signal_source": metrics["source"],
                    "last_error": self.last_error,
                    "bands": public_band_plans(),
                    "scanner": {
                        key: (
                            [dict(item) for item in value]
                            if key == "candidates"
                            else value
                        )
                        for key, value in self.scan_state.items()
                    },
                }
            )
            return result

    def close(self):
        with self.lock:
            self.scan_generation += 1
            self.scanner.cancel()
            self.driver.stop()
            self.running = False
