#!/usr/bin/env python3
"""Servidor local da Estação Rádio Web."""

import atexit
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from radio import RadioController, RadioError, ValidationError


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"


def create_app(controller=None):
    app = Flask(__name__, static_folder=None)
    radio = controller or RadioController(os.environ.get("RADIO_DRIVER", "auto"))
    app.config["RADIO_CONTROLLER"] = radio

    @app.after_request
    def disable_cache(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/")
    def index():
        return send_from_directory(str(WEB_DIR), "index.html")

    @app.route("/<path:filename>")
    def web_file(filename):
        return send_from_directory(str(WEB_DIR), filename)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "service": "estacao-radio-web", "version": "2.0.3"})

    @app.get("/api/status")
    def status():
        return jsonify(radio.status())

    @app.post("/api/config")
    def configure():
        payload = request.get_json(silent=True)
        if payload is None:
            raise ValidationError("Envie a configuração no formato JSON.")
        return jsonify(radio.configure(payload))

    @app.post("/api/band/<band>/select")
    def select_band(band):
        return jsonify(radio.apply_band(band))

    @app.post("/api/receiver/start")
    def start_receiver():
        return jsonify(radio.start())

    @app.post("/api/receiver/stop")
    def stop_receiver():
        return jsonify(radio.stop())

    @app.post("/api/scanner/start")
    def start_scanner():
        return jsonify(radio.start_scan(request.get_json(silent=True) or {}))

    @app.post("/api/scanner/next")
    def next_scanner_result():
        payload = request.get_json(silent=True) or {}
        return jsonify(radio.scan_next(payload.get("direction", 1)))

    @app.post("/api/scanner/stop")
    def stop_scanner():
        return jsonify(radio.stop_scan())

    @app.errorhandler(ValidationError)
    def validation_error(error):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(RadioError)
    def radio_error(error):
        return jsonify({"error": str(error), "status": radio.status()}), 503

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Recurso não encontrado."}), 404
        return send_from_directory(str(WEB_DIR), "index.html")

    atexit.register(radio.close)
    return app


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("RADIO_HOST", "0.0.0.0")
    port = int(os.environ.get("RADIO_PORT", "5000"))
    debug = os.environ.get("RADIO_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug, threaded=True)
