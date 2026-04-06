from __future__ import annotations

import io
import json
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from typing import Any

from PIL import Image

from P2Pro.services.thermal_service import ThermalService, PALETTE_NAMES
from P2Pro.services.media_service import MediaService


thermal = ThermalService()
media = MediaService()


def ensure_thermal_started() -> None:
    """
    Initialisiert Kamera + Videothread genau einmal.
    """
    if not thermal.camera_initialized:
        thermal.initialize(palette_name="White Hot", gain_mode="Low")
    thermal.start_video()


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "P2ProWebAPI/0.2"

    def log_message(self, format: str, *args) -> None:
        # Etwas kompaktere Logs
        print(f"[HTTP] {self.address_string()} - {format % args}")

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        try:
            if parsed.path == "/api/status":
                self._handle_status()
            elif parsed.path == "/api/frame":
                self._handle_frame()
            elif parsed.path == "/api/screenshots":
                self._handle_screenshots()
            elif parsed.path == "/api/videos":
                self._handle_videos()
            elif parsed.path == "/api/palettes":
                self._handle_palettes()
            else:
                self._send_json({"error": "Not Found"}, status=404)
        except Exception as exc:
            traceback.print_exc()
            self._send_json(
                {
                    "error": "internal_server_error",
                    "detail": str(exc),
                },
                status=500,
            )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        try:
            if parsed.path == "/api/screenshot":
                self._handle_screenshot()
            elif parsed.path == "/api/record/start":
                self._handle_record_start()
            elif parsed.path == "/api/record/stop":
                self._handle_record_stop()
            elif parsed.path == "/api/palette":
                self._handle_palette()
            elif parsed.path == "/api/gain":
                self._handle_gain()
            elif parsed.path == "/api/emissivity":
                self._handle_emissivity()
            else:
                self._send_json({"error": "Not Found"}, status=404)
        except Exception as exc:
            traceback.print_exc()
            self._send_json(
                {
                    "error": "internal_server_error",
                    "detail": str(exc),
                },
                status=500,
            )

    # -----------------------------
    # GET-Handler
    # -----------------------------

    def _handle_status(self) -> None:
        ensure_thermal_started()

        data = {
            "camera_initialized": thermal.camera_initialized,
            "recording": thermal.is_recording,
            "palette": thermal.palette_name,
            "gain": thermal.gain_state,
            "points": thermal.get_measure_points(),
            "last_frame_num": thermal.last_frame_num,
            "available_palettes": PALETTE_NAMES,
        }
        self._send_json(data)

    def _handle_frame(self) -> None:
        ensure_thermal_started()

        snapshot = thermal.get_latest_frame()
        if snapshot is None or snapshot.rgb_data is None:
            self._send_json(
                {"error": "no_frame_available"},
                status=503,
            )
            return

        img = Image.fromarray(snapshot.rgb_data)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)

        self._send_bytes(buf.getvalue(), "image/jpeg")

    def _handle_screenshots(self) -> None:
        shots = media.list_screenshots()
        self._send_json({"items": shots})

    def _handle_videos(self) -> None:
        vids = media.list_videos()
        self._send_json({"items": vids})

    def _handle_palettes(self) -> None:
        self._send_json({"items": PALETTE_NAMES})

    # -----------------------------
    # POST-Handler
    # -----------------------------

    def _handle_screenshot(self) -> None:
        ensure_thermal_started()

        # einmal frischen Frame holen, damit last_rgb/last_thermal sicher aktuell sind
        thermal.get_latest_frame()
        path = thermal.save_screenshot()

        if not path:
            self._send_json(
                {
                    "saved": None,
                    "error": "no_frame_available",
                },
                status=503,
            )
            return

        self._send_json({"saved": path})

    def _handle_record_start(self) -> None:
        ensure_thermal_started()
        rec_dir = thermal.start_recording()
        self._send_json(
            {
                "status": "recording_started",
                "recording_dir": rec_dir,
                "recording": thermal.is_recording,
            }
        )

    def _handle_record_stop(self) -> None:
        ensure_thermal_started()
        rec_dir = thermal.stop_recording()
        self._send_json(
            {
                "status": "recording_stopped",
                "recording_dir": rec_dir,
                "recording": thermal.is_recording,
            }
        )

    def _handle_palette(self) -> None:
        ensure_thermal_started()
        data = self._read_json_body()

        palette = data.get("palette")
        if not palette:
            self._send_json(
                {
                    "error": "missing_palette",
                    "available_palettes": PALETTE_NAMES,
                },
                status=400,
            )
            return

        thermal.set_palette(str(palette))
        self._send_json(
            {
                "palette": thermal.palette_name,
                "available_palettes": PALETTE_NAMES,
            }
        )

    def _handle_gain(self) -> None:
        ensure_thermal_started()
        new_gain = thermal.toggle_gain()
        self._send_json({"gain": new_gain})

    def _handle_emissivity(self) -> None:
        ensure_thermal_started()
        data = self._read_json_body()

        emissivity = data.get("emissivity")
        if emissivity is None:
            self._send_json({"error": "missing_emissivity"}, status=400)
            return

        emissivity = float(emissivity)
        thermal.set_emissivity(emissivity)
        self._send_json({"emissivity": emissivity})


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    ensure_thermal_started()
    server = HTTPServer((host, port), RequestHandler)
    print(f"Web API running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()