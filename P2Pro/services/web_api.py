from __future__ import annotations

import io
import json
import mimetypes
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs
import cv2

from PIL import Image

from P2Pro.services.thermal_service import PALETTE_NAMES, ThermalService


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

thermal = ThermalService()


def ensure_thermal_started() -> None:
    if not thermal.camera_initialized:
        thermal.initialize(palette_name="White Hot", gain_mode="Low")
    thermal.start_video()


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "P2ProWebAPI/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"[HTTP] {self.address_string()} - {format % args}")

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
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

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "Not Found"}, status=404)
            return

        content = path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(path))
        if not content_type:
            content_type = "application/octet-stream"
        self._send_bytes(content, content_type)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        try:
            if parsed.path in ("/", "/index.html"):
                self._serve_file(WEB_DIR / "index.html")
            elif parsed.path == "/live":
                self._serve_file(WEB_DIR / "live.html")
            elif parsed.path == "/api/status":
                self._handle_status()
            elif parsed.path == "/api/frame":
                self._handle_frame()
            elif parsed.path == "/api/stream":
                self._handle_stream()
            elif parsed.path == "/api/palettes":
                self._handle_palettes()
            elif parsed.path == "/api/colorbar":
                self._handle_colorbar()
            elif parsed.path == "/api/hover":
                self._handle_hover(parsed)
            else:
                self._send_json({"error": "Not Found"}, status=404)
        except BrokenPipeError:
            pass
        except ConnectionResetError:
            pass
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"error": "internal_server_error", "detail": str(exc)}, status=500)

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
            elif parsed.path == "/api/point":
                self._handle_point()
            elif parsed.path == "/api/point/move":
                self._handle_point_move()
            else:
                self._send_json({"error": "Not Found"}, status=404)
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"error": "internal_server_error", "detail": str(exc)}, status=500)

    def _handle_status(self) -> None:
        ensure_thermal_started()
        snapshot = thermal.get_latest_frame()

        frame_width = None
        frame_height = None
        temp_min_c = None
        temp_max_c = None
        min_pos = None
        max_pos = None

        if snapshot is not None and snapshot.rgb_data is not None:
            frame_height, frame_width = snapshot.rgb_data.shape[:2]
            temp_min_c = snapshot.temp_min_c
            temp_max_c = snapshot.temp_max_c
            min_pos = snapshot.min_pos
            max_pos = snapshot.max_pos

        data = {
            "camera_initialized": thermal.camera_initialized,
            "recording": thermal.is_recording,
            "palette": thermal.palette_name,
            "gain": thermal.gain_state,
            "points": thermal.get_measure_points(),
            "points_with_temp": thermal.get_measure_points_with_temperatures(),
            "last_frame_num": thermal.last_frame_num,
            "available_palettes": PALETTE_NAMES,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "temp_min_c": temp_min_c,
            "temp_max_c": temp_max_c,
            "min_pos": min_pos,
            "max_pos": max_pos,
        }
        self._send_json(data)

    def _handle_frame(self) -> None:
        ensure_thermal_started()
        snapshot = thermal.get_latest_frame()
        if snapshot is None or snapshot.rgb_data is None:
            self._send_json({"error": "no_frame_available"}, status=503)
            return

        img = Image.fromarray(snapshot.rgb_data)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        self._send_bytes(buf.getvalue(), "image/jpeg")

    def _handle_stream(self) -> None:
        ensure_thermal_started()

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            while True:
                snapshot = thermal.get_latest_frame()
                if snapshot is None or snapshot.rgb_data is None:
                    time.sleep(0.01)
                    continue

                img = Image.fromarray(snapshot.rgb_data)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                jpg = buf.getvalue()

                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode("utf-8"))
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(0.001)
        except BrokenPipeError:
            pass
        except ConnectionResetError:
            pass

    def _handle_colorbar(self) -> None:
        """Gibt das aktuelle Paletten-Bild als schmales PNG für die Legende zurück."""
        ensure_thermal_started()
        bar_rgb = thermal.build_colormap_bar()
        # Skaliere es für das Web auf 20px Breite, um die Darstellung zu optimieren
        bar_img = cv2.resize(bar_rgb, (20, 256), interpolation=cv2.INTER_NEAREST)
        img = Image.fromarray(bar_img)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self._send_bytes(buf.getvalue(), "image/png")

    def _handle_hover(self, parsed) -> None:
        """Erlaubt extrem schnelle Abfragen für die Hover-Temperatur im Browser."""
        ensure_thermal_started()
        qs = parse_qs(parsed.query)
        try:
            x = int(qs.get("x", ["0"])[0])
            y = int(qs.get("y", ["0"])[0])
            temp = thermal.get_point_temperature(x, y)
            self._send_json({"temp_c": temp})
        except Exception:
            self._send_json({"error": "invalid coordinates"}, status=400)

    def _handle_palettes(self) -> None:
        self._send_json({"items": PALETTE_NAMES})

    def _handle_screenshot(self) -> None:
        ensure_thermal_started()
        thermal.get_latest_frame()
        path = thermal.save_screenshot()
        if not path:
            self._send_json({"saved": None, "error": "no_frame_available"}, status=503)
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
                {"error": "missing_palette", "available_palettes": PALETTE_NAMES},
                status=400,
            )
            return
        thermal.set_palette(str(palette))
        self._send_json(
            {"palette": thermal.palette_name, "available_palettes": PALETTE_NAMES}
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

    def _handle_point(self) -> None:
        ensure_thermal_started()
        data = self._read_json_body()

        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            self._send_json({"error": "missing_coordinates"}, status=400)
            return

        thermal.toggle_measure_point(int(round(float(x))), int(round(float(y))))
        self._send_json({"points_with_temp": thermal.get_measure_points_with_temperatures()})

    def _handle_point_move(self) -> None:
        ensure_thermal_started()
        data = self._read_json_body()
        idx = data.get("index")
        x = data.get("x")
        y = data.get("y")
        
        if idx is not None and x is not None and y is not None:
            thermal.move_measure_point(int(idx), int(round(float(x))), int(round(float(y))))
        
        self._send_json({"points_with_temp": thermal.get_measure_points_with_temperatures()})


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    ensure_thermal_started()
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Web API running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()