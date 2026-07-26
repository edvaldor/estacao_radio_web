"""Controle do receptor usado pela interface web.

O projeto funciona em dois modos:

* ``simulation``: permite testar toda a interface sem um dongle.
* ``rtl_fm``: usa os programas rtl_fm e aplay para receber AM/NFM/WFM.

USB e LSB aparecem na interface para evolução futura, mas o rtl_fm não
demodula esses dois modos.
"""

import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, replace


ALLOWED_MODES = {"AM", "NFM", "WFM", "USB", "LSB"}
MIN_FREQUENCY_MHZ = 24.0
MAX_FREQUENCY_MHZ = 1766.0


class RadioError(RuntimeError):
    """Erro que pode ser apresentado ao usuário da estação."""


class ValidationError(RadioError):
    """Configuração enviada pela interface é inválida."""


@dataclass
class RadioConfig:
    frequency_mhz: float = 27.185
    band: str = "cb"
    channel: str = "PX · Canal 19"
    mode: str = "AM"
    step_khz: float = 5.0
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


class SimulationDriver(BaseDriver):
    name = "simulation"

    def __init__(self):
        self.running = False

    def start(self, config):
        self.running = True

    def stop(self):
        self.running = False

    def is_alive(self):
        return self.running


class UnavailableDriver(BaseDriver):
    name = "unavailable"

    def __init__(self, reason):
        self.reason = reason

    def start(self, config):
        raise RadioError(self.reason)


class RTLFMDriver(BaseDriver):
    name = "rtl_fm"

    def __init__(self, rtl_fm_path, aplay_path):
        self.rtl_fm_path = rtl_fm_path
        self.aplay_path = aplay_path
        self.rtl_process = None
        self.audio_process = None
        self.rtl_log = None
        self.audio_log = None

    @staticmethod
    def command_available():
        return bool(shutil.which("rtl_fm") and shutil.which("aplay"))

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
        mode = config.mode.upper()
        if mode == "AM":
            rtl_mode = "am"
            sample_rate = "120000"
            extra = ["-E", "dc"]
        elif mode == "NFM":
            rtl_mode = "fm"
            sample_rate = "240000"
            extra = ["-E", "dc"]
        elif mode == "WFM":
            rtl_mode = "wbfm"
            sample_rate = "170000"
            extra = ["-E", "deemp"]
        else:
            raise RadioError(
                "O rtl_fm recebe AM, NFM e WFM. USB/LSB serão adicionados em uma próxima etapa."
            )

        frequency_hz = int(round(config.frequency_mhz * 1_000_000))
        return [
            self.rtl_fm_path,
            "-f",
            str(frequency_hz),
            "-M",
            rtl_mode,
            "-s",
            sample_rate,
            "-r",
            "48000",
        ] + extra + ["-"]

    def _audio_command(self):
        return [
            self.aplay_path,
            "-q",
            "-r",
            "48000",
            "-f",
            "S16_LE",
            "-c",
            "1",
        ]

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

    def start(self, config):
        self.stop()
        self.rtl_log = tempfile.TemporaryFile()
        self.audio_log = tempfile.TemporaryFile()

        try:
            self.rtl_process = subprocess.Popen(
                self._radio_command(config),
                stdout=subprocess.PIPE,
                stderr=self.rtl_log,
                start_new_session=True,
            )
            self.audio_process = subprocess.Popen(
                self._audio_command(),
                stdin=self.rtl_process.stdout,
                stdout=subprocess.DEVNULL,
                stderr=self.audio_log,
                start_new_session=True,
            )
            self.rtl_process.stdout.close()
            time.sleep(0.45)

            if self.rtl_process.poll() is not None or self.audio_process.poll() is not None:
                rtl_error = self._read_log(self.rtl_log)
                audio_error = self._read_log(self.audio_log)
                details = rtl_error or audio_error or "O processo do receptor terminou inesperadamente."
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

        attempted = set()
        for mixer in mixers:
            if not mixer or mixer in attempted:
                continue
            attempted.add(mixer)
            result = subprocess.run(
                [amixer, "sset", mixer, "{}%".format(int(volume))],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
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
        self._terminate(self.audio_process)
        self._terminate(self.rtl_process)
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


def select_driver(preference):
    preference = (preference or "auto").strip().lower()

    if preference == "simulation":
        return SimulationDriver()

    if preference not in {"auto", "rtl_fm"}:
        return UnavailableDriver(
            "Configuração RADIO_DRIVER inválida. Use auto, simulation ou rtl_fm."
        )

    rtl_fm_path = shutil.which("rtl_fm")
    aplay_path = shutil.which("aplay")
    commands_ready = bool(rtl_fm_path and aplay_path)
    device_ready = commands_ready and RTLFMDriver.probe_device()

    if device_ready:
        return RTLFMDriver(rtl_fm_path, aplay_path)

    if preference == "rtl_fm":
        if not commands_ready:
            reason = "Instale os pacotes rtl-sdr e alsa-utils antes de iniciar o rádio."
        else:
            reason = "Nenhum dongle RTL-SDR foi encontrado. Confira a porta USB e reinicie."
        return UnavailableDriver(reason)

    return SimulationDriver()


class RadioController:
    def __init__(self, driver_preference="auto"):
        self.lock = threading.RLock()
        self.config = RadioConfig()
        self.driver = select_driver(driver_preference)
        self.running = False
        self.signal_percent = 8.0
        self.last_error = None

    @staticmethod
    def _number(payload, key, current):
        if key not in payload:
            return current
        try:
            return float(payload[key])
        except (TypeError, ValueError):
            raise ValidationError("O campo {} deve ser numérico.".format(key))

    def _validated_config(self, payload):
        config = replace(self.config)

        config.frequency_mhz = self._number(payload, "frequency_mhz", config.frequency_mhz)
        if not MIN_FREQUENCY_MHZ <= config.frequency_mhz <= MAX_FREQUENCY_MHZ:
            raise ValidationError(
                "A frequência deve ficar entre {:.3f} e {:.3f} MHz.".format(
                    MIN_FREQUENCY_MHZ, MAX_FREQUENCY_MHZ
                )
            )
        config.frequency_mhz = round(config.frequency_mhz, 3)

        if "mode" in payload:
            mode = str(payload["mode"]).upper().strip()
            if mode not in ALLOWED_MODES:
                raise ValidationError("Modo de recepção inválido.")
            config.mode = mode

        config.step_khz = self._number(payload, "step_khz", config.step_khz)
        if not 0.1 <= config.step_khz <= 1000:
            raise ValidationError("O passo deve ficar entre 0,1 e 1000 kHz.")

        if "volume" in payload:
            try:
                config.volume = int(payload["volume"])
            except (TypeError, ValueError):
                raise ValidationError("O volume deve ser um número inteiro.")
            if not 0 <= config.volume <= 100:
                raise ValidationError("O volume deve ficar entre 0 e 100%.")

        if "band" in payload:
            config.band = str(payload["band"]).strip()[:30] or "manual"
        if "channel" in payload:
            config.channel = str(payload["channel"]).strip()[:80] or "Sintonia manual"

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

            if volume_changed:
                self.driver.set_volume(self.config.volume)

            if self.running and receiver_changed:
                try:
                    self.driver.start(self.config)
                    self.last_error = None
                except RadioError as error:
                    self.running = False
                    self.last_error = str(error)
                    raise

            return self.status()

    def start(self):
        with self.lock:
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
            self.driver.stop()
            self.running = False
            return self.status()

    def _update_signal(self):
        if self.running:
            target = 55.0 if self.driver.name == "rtl_fm" else 45.0
            self.signal_percent += (target - self.signal_percent) * 0.22
            self.signal_percent += random.uniform(-6.0, 7.0)
        else:
            self.signal_percent += (7.0 - self.signal_percent) * 0.3
            self.signal_percent += random.uniform(-1.5, 1.5)
        self.signal_percent = max(0.0, min(100.0, self.signal_percent))

    def status(self):
        with self.lock:
            if self.running and not self.driver.is_alive():
                self.running = False
                self.last_error = "O processo de recepção foi encerrado."

            self._update_signal()
            result = asdict(self.config)
            result.update(
                {
                    "running": self.running,
                    "driver": self.driver.name,
                    "signal_percent": round(self.signal_percent, 1),
                    "signal_source": "estimated",
                    "last_error": self.last_error,
                }
            )
            return result

    def close(self):
        with self.lock:
            self.driver.stop()
            self.running = False
