(function () {
  "use strict";

  var BANDS = {
    fm: {
      label: "FM comercial",
      channel: "Rádio Capital 91",
      frequency: 91.900,
      mode: "NFM",
      step: 100
    },
    air: {
      label: "Aeronáutica",
      channel: "Emergência 121.5",
      frequency: 121.500,
      mode: "AM",
      step: 25
    },
    vhf: {
      label: "Radioamador VHF",
      channel: "Chamada VHF",
      frequency: 145.500,
      mode: "NFM",
      step: 12.5
    },
    uhf: {
      label: "Radioamador UHF",
      channel: "Chamada UHF",
      frequency: 433.500,
      mode: "NFM",
      step: 12.5
    },
    cb: {
      label: "PX / CB 11 m",
      channel: "PX · Canal 19",
      frequency: 27.185,
      mode: "AM",
      step: 10
    }
  };

  var state = {
    frequency: 91.900,
    band: "fm",
    channel: "Rádio Capital 91",
    mode: "NFM",
    step: 100,
    volume: 65,
    running: false,
    signal: 35,
    driver: "simulation",
    signalDbfs: -90,
    signalSource: "simulation",
    browserAudioPlaying: false,
    scanner: {
      active: false,
      phase: "idle",
      progress: 0,
      message: "Scanner pronto.",
      candidates: [],
      current_index: -1
    },
    apiOnline: window.location.protocol !== "file:"
  };

  var elements = {
    app: document.getElementById("radioApp"),
    frequencyButton: document.getElementById("frequencyButton"),
    frequencyDisplay: document.getElementById("frequencyDisplay"),
    channelDisplay: document.getElementById("channelDisplay"),
    modeDisplay: document.getElementById("modeDisplay"),
    bandSelect: document.getElementById("bandSelect"),
    modeSelect: document.getElementById("modeSelect"),
    stepSelect: document.getElementById("stepSelect"),
    themeButton: document.getElementById("themeButton"),
    themeIcon: document.getElementById("themeIcon"),
    browserAudioButton: document.getElementById("browserAudioButton"),
    browserAudioIcon: document.getElementById("browserAudioIcon"),
    browserAudio: document.getElementById("browserAudio"),
    driverDisplay: document.getElementById("driverDisplay"),
    statusDot: document.getElementById("statusDot"),
    meterTicks: document.getElementById("meterTicks"),
    meterNeedle: document.getElementById("meterNeedle"),
    signalDisplay: document.getElementById("signalDisplay"),
    dbmDisplay: document.getElementById("dbmDisplay"),
    tuneDownButton: document.getElementById("tuneDownButton"),
    tuneUpButton: document.getElementById("tuneUpButton"),
    downStepLabel: document.getElementById("downStepLabel"),
    upStepLabel: document.getElementById("upStepLabel"),
    receiverButton: document.getElementById("receiverButton"),
    receiverButtonLabel: document.getElementById("receiverButtonLabel"),
    scannerButton: document.getElementById("scannerButton"),
    volumeInput: document.getElementById("volumeInput"),
    volumeDisplay: document.getElementById("volumeDisplay"),
    message: document.getElementById("message"),
    frequencyDialog: document.getElementById("frequencyDialog"),
    frequencyForm: document.getElementById("frequencyForm"),
    frequencyInput: document.getElementById("frequencyInput"),
    frequencyInputDisplay: document.getElementById("frequencyInputDisplay"),
    frequencyError: document.getElementById("frequencyError"),
    frequencyCloseButton: document.getElementById("frequencyCloseButton"),
    frequencyCancelButton: document.getElementById("frequencyCancelButton"),
    frequencyDeleteButton: document.getElementById("frequencyDeleteButton"),
    scannerDialog: document.getElementById("scannerDialog"),
    scannerCloseButton: document.getElementById("scannerCloseButton"),
    scannerBand: document.getElementById("scannerBand"),
    scannerSensitivity: document.getElementById("scannerSensitivity"),
    scannerSensitivityDisplay: document.getElementById("scannerSensitivityDisplay"),
    scannerStatus: document.getElementById("scannerStatus"),
    scannerStation: document.getElementById("scannerStation"),
    scannerPower: document.getElementById("scannerPower"),
    scannerFrequency: document.getElementById("scannerFrequency"),
    scannerProgress: document.getElementById("scannerProgress"),
    scannerStartButton: document.getElementById("scannerStartButton"),
    scannerPreviousButton: document.getElementById("scannerPreviousButton"),
    scannerNextButton: document.getElementById("scannerNextButton")
  };

  var messageTimer = null;
  var volumeTimer = null;
  var signalTimer = null;
  var statusTimer = null;
  var dialogPreviouslyFocused = null;

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function formatFrequency(value) {
    return Number(value).toFixed(3);
  }

  function formatStep(value) {
    return String(value).replace(".", ",") + " kHz";
  }

  function pointOnMeter(angle, radius) {
    var radians = angle * Math.PI / 180;
    return {
      x: 180 + radius * Math.cos(radians),
      y: 131 + radius * Math.sin(radians)
    };
  }

  function createSvgElement(name, attributes) {
    var element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attributes).forEach(function (key) {
      element.setAttribute(key, String(attributes[key]));
    });
    return element;
  }

  function buildMeter() {
    var labels = {
      0: "S1",
      4: "S3",
      8: "S5",
      12: "S7",
      16: "S9",
      20: "+20",
      24: "+40",
      28: "+60"
    };
    var startAngle = 201;
    var endAngle = 339;
    var radius = 142;

    elements.meterTicks.textContent = "";

    for (var index = 0; index <= 28; index += 1) {
      var angle = startAngle + (endAngle - startAngle) * (index / 28);
      var isMajor = Object.prototype.hasOwnProperty.call(labels, index);
      var outer = pointOnMeter(angle, radius);
      var inner = pointOnMeter(angle, radius - (isMajor ? 14 : 7));
      var tick = createSvgElement("line", {
        x1: inner.x.toFixed(2),
        y1: inner.y.toFixed(2),
        x2: outer.x.toFixed(2),
        y2: outer.y.toFixed(2),
        "class": isMajor ? "meter-tick is-major" : "meter-tick"
      });
      elements.meterTicks.appendChild(tick);

      if (isMajor) {
        var labelPoint = pointOnMeter(angle, radius - 26);
        var label = createSvgElement("text", {
          x: labelPoint.x.toFixed(2),
          y: (labelPoint.y + 3).toFixed(2),
          "text-anchor": "middle",
          "class": "meter-tick-label"
        });
        label.textContent = labels[index];
        elements.meterTicks.appendChild(label);
      }
    }
  }

  function signalReading(percent) {
    if (percent <= 70) {
      var sValue = 1 + (percent / 70) * 8;
      return {
        label: "S" + sValue.toFixed(1),
        dbm: Math.round(-127 + (sValue - 1) * 6)
      };
    }

    var plusValue = ((percent - 70) / 30) * 60;
    return {
      label: "S9+" + Math.round(plusValue),
      dbm: Math.round(-73 + plusValue)
    };
  }

  function updateMeter(percent, dbfs, source) {
    var safePercent = clamp(Number(percent) || 0, 0, 100);
    var angle = 201 + (339 - 201) * (safePercent / 100);
    var reading = signalReading(safePercent);

    elements.meterNeedle.style.transform = "rotate(" + (angle - 270).toFixed(2) + "deg)";
    elements.meterNeedle.classList.toggle("is-hot", safePercent > 70);
    elements.signalDisplay.textContent = reading.label;
    if (source === "audio_rms" && Number.isFinite(dbfs)) {
      elements.dbmDisplay.textContent =
        (dbfs < 0 ? "−" + Math.abs(dbfs).toFixed(1) : dbfs.toFixed(1)) + " dBFS";
    } else {
      elements.dbmDisplay.textContent =
        (reading.dbm < 0 ? "−" + Math.abs(reading.dbm) : String(reading.dbm)) + " relativo";
    }
  }

  function driverLabel(driver) {
    if (driver === "rtl_fm") {
      return "RTL-SDR conectado";
    }
    if (driver === "simulation") {
      return "Modo demonstração";
    }
    return "Rádio indisponível";
  }

  function render() {
    elements.frequencyDisplay.textContent = formatFrequency(state.frequency);
    elements.channelDisplay.textContent = state.channel;
    elements.modeDisplay.textContent = state.mode;
    elements.modeSelect.value = state.mode;
    elements.stepSelect.value = String(state.step);
    elements.volumeInput.value = String(state.volume);
    elements.volumeDisplay.textContent = state.volume + "%";
    elements.downStepLabel.textContent = formatStep(state.step);
    elements.upStepLabel.textContent = formatStep(state.step);
    elements.receiverButton.setAttribute("aria-pressed", state.running ? "true" : "false");
    elements.receiverButtonLabel.textContent = state.running ? "Parar" : "Iniciar";
    elements.browserAudioButton.setAttribute(
      "aria-pressed",
      state.browserAudioPlaying ? "true" : "false"
    );
    elements.browserAudioButton.setAttribute(
      "aria-label",
      state.browserAudioPlaying
        ? "Parar áudio neste navegador"
        : "Ouvir o rádio neste navegador"
    );
    elements.browserAudioIcon.textContent = state.browserAudioPlaying ? "■" : "▶";
    elements.browserAudioButton.disabled =
      !state.running || state.driver !== "rtl_fm";
    elements.browserAudio.volume = clamp(state.volume / 100, 0, 1);
    elements.driverDisplay.textContent = driverLabel(state.driver);
    elements.statusDot.classList.toggle("is-ready", state.driver === "rtl_fm" || state.driver === "simulation");
    elements.statusDot.classList.toggle("is-error", state.driver === "unavailable");

    if (state.band !== "manual" && BANDS[state.band]) {
      elements.bandSelect.value = state.band;
    }

    updateMeter(state.signal, state.signalDbfs, state.signalSource);
    renderScanner();
  }

  function currentScannerCandidate() {
    var scanner = state.scanner || {};
    var candidates = scanner.candidates || [];
    var index = Number(scanner.current_index);
    return index >= 0 && candidates[index] ? candidates[index] : null;
  }

  function renderScanner() {
    var scanner = state.scanner || {};
    var candidate = currentScannerCandidate();
    var scanning = scanner.phase === "scanning";
    var hasResults = scanner.phase === "listening" && (scanner.candidates || []).length > 0;
    elements.scannerStatus.textContent = scanner.message || "Scanner pronto.";
    elements.scannerProgress.style.width = String(clamp(Number(scanner.progress) || 0, 0, 100)) + "%";
    elements.scannerStartButton.textContent = scanning ? "Medindo…" : "Varrer";
    elements.scannerStartButton.disabled = scanning;
    elements.scannerPreviousButton.disabled = !hasResults;
    elements.scannerNextButton.disabled = !hasResults;
    if (candidate) {
      elements.scannerFrequency.textContent = formatFrequency(candidate.frequency_mhz) + " MHz";
      elements.scannerStation.textContent = candidate.name || "Sinal encontrado";
      elements.scannerPower.textContent =
        "Pico " + Number(candidate.power_db).toFixed(1) + " dB · " +
        Number(candidate.above_noise_db).toFixed(1) + " dB acima do ruído";
    } else {
      elements.scannerFrequency.textContent = scanning ? "Varrendo…" : "Pronto";
      elements.scannerStation.textContent = "—";
      elements.scannerPower.textContent =
        scanning ? "O áudio volta ao terminar." : "O rádio para de tocar durante a medição.";
    }
  }

  function showMessage(text, isError) {
    window.clearTimeout(messageTimer);
    elements.message.textContent = text;
    elements.message.classList.toggle("is-error", Boolean(isError));
    elements.message.hidden = false;
    messageTimer = window.setTimeout(function () {
      elements.message.hidden = true;
    }, isError ? 5000 : 2500);
  }

  function apiRequest(path, method, body) {
    if (!state.apiOnline) {
      return Promise.reject(new Error("API indisponível"));
    }

    var options = {
      method: method || "GET",
      headers: {
        "Accept": "application/json"
      }
    };

    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    return fetch(path, options).then(function (response) {
      return response.json().catch(function () {
        return {};
      }).then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || "O rádio não respondeu.");
        }
        return data;
      });
    });
  }

  function applyServerState(serverState) {
    if (!serverState) {
      return;
    }

    if (typeof serverState.frequency_mhz === "number") {
      state.frequency = serverState.frequency_mhz;
    }
    if (typeof serverState.band === "string") {
      state.band = serverState.band;
    }
    if (typeof serverState.channel === "string") {
      state.channel = serverState.channel;
    }
    if (typeof serverState.mode === "string") {
      state.mode = serverState.mode;
    }
    if (typeof serverState.step_khz === "number") {
      state.step = serverState.step_khz;
    }
    if (typeof serverState.volume === "number") {
      state.volume = serverState.volume;
    }
    if (typeof serverState.running === "boolean") {
      state.running = serverState.running;
    }
    if (typeof serverState.signal_percent === "number") {
      state.signal = serverState.signal_percent;
    }
    if (typeof serverState.signal_dbfs === "number") {
      state.signalDbfs = serverState.signal_dbfs;
    }
    if (typeof serverState.signal_source === "string") {
      state.signalSource = serverState.signal_source;
    }
    if (typeof serverState.driver === "string") {
      state.driver = serverState.driver;
    }
    if (serverState.bands && typeof serverState.bands === "object") {
      Object.keys(serverState.bands).forEach(function (key) {
        if (BANDS[key]) {
          var plan = serverState.bands[key];
          BANDS[key].frequency = plan.preset_mhz;
          BANDS[key].mode = plan.mode;
          BANDS[key].step = plan.step_khz;
          BANDS[key].channel = plan.channel;
        }
      });
    }
    if (serverState.scanner && typeof serverState.scanner === "object") {
      state.scanner = serverState.scanner;
    }
    render();
  }

  function syncStatus() {
    if (!state.apiOnline) {
      return;
    }

    apiRequest("/api/status").then(function (data) {
      applyServerState(data);
    }).catch(function () {
      state.apiOnline = false;
      state.driver = "simulation";
      render();
      startSignalSimulation();
    });
  }

  function sendConfiguration(extra, autoSelect) {
    var payload = {
      frequency_mhz: state.frequency,
      band: state.band,
      channel: state.channel,
      mode: state.mode,
      step_khz: state.step,
      volume: state.volume
    };
    payload.auto_select = Boolean(autoSelect);

    Object.keys(extra || {}).forEach(function (key) {
      payload[key] = extra[key];
    });

    render();

    return apiRequest("/api/config", "POST", payload).then(function (data) {
      applyServerState(data);
      return data;
    }).catch(function (error) {
      if (error.message === "API indisponível") {
        return null;
      }
      showMessage(error.message, true);
      throw error;
    });
  }

  function tune(direction) {
    state.frequency = clamp(
      Math.round((state.frequency + direction * state.step / 1000) * 1000) / 1000,
      24,
      1766
    );
    sendConfiguration({}, true);
  }

  function applyBand(bandKey) {
    var preset = BANDS[bandKey];
    if (!preset) {
      return;
    }

    state.band = bandKey;
    state.channel = preset.channel;
    state.frequency = preset.frequency;
    state.mode = preset.mode;
    state.step = preset.step;
    render();
    apiRequest("/api/band/" + encodeURIComponent(bandKey) + "/select", "POST", {})
      .then(applyServerState)
      .catch(function (error) {
        showMessage(error.message, true);
      });
  }

  function toggleReceiver() {
    var endpoint = state.running ? "/api/receiver/stop" : "/api/receiver/start";
    var intendedRunning = !state.running;

    if (state.running) {
      stopBrowserAudio();
    }

    if (!state.apiOnline) {
      state.running = intendedRunning;
      render();
      showMessage(state.running ? "Demonstração iniciada." : "Demonstração parada.", false);
      return;
    }

    elements.receiverButton.disabled = true;
    apiRequest(endpoint, "POST", {}).then(function (data) {
      applyServerState(data);
      showMessage(state.running ? "Recepção iniciada." : "Recepção parada.", false);
    }).catch(function (error) {
      showMessage(error.message, true);
    }).finally(function () {
      elements.receiverButton.disabled = false;
    });
  }

  function stopBrowserAudio(message) {
    elements.browserAudio.pause();
    elements.browserAudio.removeAttribute("src");
    elements.browserAudio.load();
    state.browserAudioPlaying = false;
    render();
    if (message) {
      showMessage(message, false);
    }
  }

  function toggleBrowserAudio() {
    if (state.browserAudioPlaying) {
      stopBrowserAudio("Áudio no navegador desligado.");
      return;
    }
    if (!state.running) {
      showMessage("Primeiro toque em Iniciar.", true);
      return;
    }
    if (state.driver !== "rtl_fm") {
      showMessage("Conecte o RTL-SDR para ouvir o áudio ao vivo.", true);
      return;
    }

    elements.browserAudio.src =
      "/api/audio/stream.wav?t=" + String(Date.now());
    elements.browserAudio.volume = clamp(state.volume / 100, 0, 1);
    elements.browserAudio.play().then(function () {
      state.browserAudioPlaying = true;
      render();
      showMessage("Áudio tocando neste navegador.", false);
    }).catch(function () {
      state.browserAudioPlaying = false;
      render();
      showMessage(
        "O navegador bloqueou o áudio. Toque novamente no botão ▶.",
        true
      );
    });
  }

  function openFrequencyDialog() {
    dialogPreviouslyFocused = document.activeElement;
    elements.frequencyInput.value = formatFrequency(state.frequency);
    elements.frequencyInputDisplay.textContent = elements.frequencyInput.value;
    elements.frequencyError.hidden = true;
    elements.frequencyDialog.hidden = false;
    elements.frequencyInput.focus();
    elements.frequencyInput.select();
  }

  function closeFrequencyDialog() {
    elements.frequencyDialog.hidden = true;
    if (dialogPreviouslyFocused && typeof dialogPreviouslyFocused.focus === "function") {
      dialogPreviouslyFocused.focus();
    }
  }

  function updateFrequencyEntry() {
    elements.frequencyInputDisplay.textContent = elements.frequencyInput.value || "—";
    elements.frequencyError.hidden = true;
  }

  function insertFrequencyKey(key) {
    var input = elements.frequencyInput;
    var value = input.value;
    var start = input.selectionStart === null ? value.length : input.selectionStart;
    var end = input.selectionEnd === null ? value.length : input.selectionEnd;
    var selected = value.slice(start, end);

    if (key === "." && /[.,]/.test(value) && !/[.,]/.test(selected)) {
      return;
    }

    var nextValue = value.slice(0, start) + key + value.slice(end);
    if (nextValue.length > 8) {
      return;
    }

    input.value = nextValue;
    input.focus();
    input.setSelectionRange(start + key.length, start + key.length);
    updateFrequencyEntry();
  }

  function deleteFrequencyKey() {
    var input = elements.frequencyInput;
    var value = input.value;
    var start = input.selectionStart === null ? value.length : input.selectionStart;
    var end = input.selectionEnd === null ? value.length : input.selectionEnd;

    if (start !== end) {
      input.value = value.slice(0, start) + value.slice(end);
      input.setSelectionRange(start, start);
    } else if (start > 0) {
      input.value = value.slice(0, start - 1) + value.slice(end);
      input.setSelectionRange(start - 1, start - 1);
    }

    input.focus();
    updateFrequencyEntry();
  }

  function submitFrequency(event) {
    event.preventDefault();
    var value = Number(elements.frequencyInput.value.replace(",", "."));

    if (!Number.isFinite(value) || value < 24 || value > 1766) {
      elements.frequencyError.hidden = false;
      return;
    }

    state.frequency = Math.round(value * 1000) / 1000;
    closeFrequencyDialog();
    sendConfiguration({}, true);
  }

  function openScannerDialog() {
    elements.scannerBand.value = BANDS[state.band] ? state.band : "fm";
    elements.scannerDialog.hidden = false;
    renderScanner();
  }

  function closeScannerDialog() {
    elements.scannerDialog.hidden = true;
  }

  function startScanner() {
    var band = elements.scannerBand.value;
    var sensitivity = Number(elements.scannerSensitivity.value);
    stopBrowserAudio();
    elements.scannerStartButton.disabled = true;
    apiRequest("/api/scanner/start", "POST", {
      band: band,
      sensitivity_db: sensitivity
    }).then(function (data) {
      applyServerState(data);
      showMessage("Varredura iniciada. Aguarde alguns segundos.", false);
    }).catch(function (error) {
      showMessage(error.message, true);
    }).finally(function () {
      elements.scannerStartButton.disabled = false;
    });
  }

  function scannerMove(direction) {
    apiRequest("/api/scanner/next", "POST", { direction: direction })
      .then(applyServerState)
      .catch(function (error) {
        showMessage(error.message, true);
      });
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    elements.themeIcon.textContent = theme === "light" ? "☀" : "☾";
    elements.themeButton.setAttribute(
      "aria-label",
      theme === "light" ? "Ativar modo noturno" : "Ativar modo claro"
    );
    try {
      window.localStorage.setItem("radio-theme", theme);
    } catch (error) {
      return;
    }
  }

  function initializeTheme() {
    var storedTheme = null;
    try {
      storedTheme = window.localStorage.getItem("radio-theme");
    } catch (error) {
      storedTheme = null;
    }

    if (storedTheme === "light" || storedTheme === "dark") {
      setTheme(storedTheme);
      return;
    }

    var prefersLight = window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: light)").matches;
    setTheme(prefersLight ? "light" : "dark");
  }

  function startSignalSimulation() {
    if (signalTimer !== null) {
      return;
    }

    signalTimer = window.setInterval(function () {
      var target = state.running ? 48 : 8;
      var variation = state.running ? (Math.random() - 0.46) * 18 : (Math.random() - 0.5) * 4;
      state.signal = clamp(state.signal + (target - state.signal) * 0.18 + variation, 0, 100);
      updateMeter(state.signal, state.signalDbfs, state.signalSource);
    }, 650);
  }

  function bindEvents() {
    elements.bandSelect.addEventListener("change", function () {
      applyBand(elements.bandSelect.value);
    });

    elements.modeSelect.addEventListener("change", function () {
      state.mode = elements.modeSelect.value;
      sendConfiguration();
    });

    elements.stepSelect.addEventListener("change", function () {
      state.step = Number(elements.stepSelect.value);
      sendConfiguration();
    });

    elements.tuneDownButton.addEventListener("click", function () {
      tune(-1);
    });

    elements.tuneUpButton.addEventListener("click", function () {
      tune(1);
    });

    elements.receiverButton.addEventListener("click", toggleReceiver);
    elements.browserAudioButton.addEventListener("click", toggleBrowserAudio);
    elements.browserAudio.addEventListener("ended", function () {
      state.browserAudioPlaying = false;
      render();
    });
    elements.browserAudio.addEventListener("error", function () {
      if (state.browserAudioPlaying) {
        state.browserAudioPlaying = false;
        render();
        showMessage(
          "O fluxo de áudio foi interrompido. Toque em ▶ para reconectar.",
          true
        );
      }
    });

    elements.volumeInput.addEventListener("input", function () {
      state.volume = Number(elements.volumeInput.value);
      elements.volumeDisplay.textContent = state.volume + "%";
      elements.browserAudio.volume = clamp(state.volume / 100, 0, 1);
      window.clearTimeout(volumeTimer);
      volumeTimer = window.setTimeout(function () {
        sendConfiguration();
      }, 180);
    });

    elements.themeButton.addEventListener("click", function () {
      var current = document.documentElement.getAttribute("data-theme");
      setTheme(current === "light" ? "dark" : "light");
    });

    elements.frequencyButton.addEventListener("click", openFrequencyDialog);
    elements.frequencyCloseButton.addEventListener("click", closeFrequencyDialog);
    elements.frequencyCancelButton.addEventListener("click", closeFrequencyDialog);
    elements.frequencyDeleteButton.addEventListener("click", deleteFrequencyKey);
    elements.frequencyForm.addEventListener("submit", submitFrequency);
    elements.frequencyInput.addEventListener("input", updateFrequencyEntry);

    elements.scannerButton.addEventListener("click", openScannerDialog);
    elements.scannerCloseButton.addEventListener("click", closeScannerDialog);
    elements.scannerStartButton.addEventListener("click", startScanner);
    elements.scannerPreviousButton.addEventListener("click", function () {
      scannerMove(-1);
    });
    elements.scannerNextButton.addEventListener("click", function () {
      scannerMove(1);
    });
    elements.scannerSensitivity.addEventListener("input", function () {
      elements.scannerSensitivityDisplay.textContent =
        elements.scannerSensitivity.value + " dB";
    });

    elements.frequencyDialog.addEventListener("click", function (event) {
      var keyButton = event.target.closest("button[data-key]");
      if (keyButton) {
        insertFrequencyKey(keyButton.getAttribute("data-key"));
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !elements.frequencyDialog.hidden) {
        closeFrequencyDialog();
      } else if (event.key === "Escape" && !elements.scannerDialog.hidden) {
        closeScannerDialog();
      }
    });
  }

  function initialize() {
    buildMeter();
    initializeTheme();
    bindEvents();
    render();
    if (!state.apiOnline) {
      startSignalSimulation();
    }
    syncStatus();

    statusTimer = window.setInterval(function () {
      if (state.apiOnline) {
        syncStatus();
      }
    }, 1500);
  }

  initialize();
}());
