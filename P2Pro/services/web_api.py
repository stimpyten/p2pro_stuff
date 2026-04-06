from __future__ import annotations

import io
import json
import mimetypes
import os
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

# Wichtige Video-Mimetypes für den Media Viewer
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/x-matroska", ".mkv")


def ensure_thermal_started() -> None:
    if not thermal.camera_initialized:
        thermal.initialize(palette_name="White Hot", gain_mode="Low")
    thermal.start_video()


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "P2ProWebAPI/1.3"

    def log_message(self, format: str, *args) -> None:
        pass # Verhindert Konsolenspam beim Streaming

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict:
        """Liest den Body aus, um die Leitung (Socket) für Keep-Alive sauber zu halten."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "Not Found"}, status=404)
            return

        content = path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(path))
        if not content_type:
            content_type = "application/octet-stream"
        
        # Für Media Viewer essenziell (Videostreaming im Browser)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(content)

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
            elif parsed.path == "/media":
                self._serve_file(WEB_DIR / "media.html")
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
            elif parsed.path == "/api/files":
                self._handle_files()
            elif parsed.path.startswith("/media_files/"):
                self._serve_media_file(parsed.path)
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
            # WICHTIGER FIX: Den Body IMMER auslesen, um den Socket sauber zu halten!
            req_data = self._read_json_body()

            if parsed.path == "/api/screenshot":
                self._handle_screenshot()
            elif parsed.path == "/api/record/start":
                self._handle_record_start()
            elif parsed.path == "/api/record/stop":
                self._handle_record_stop()
            elif parsed.path == "/api/palette":
                self._handle_palette(req_data)
            elif parsed.path == "/api/gain":
                self._handle_gain()
            elif parsed.path == "/api/emissivity":
                self._handle_emissivity(req_data)
            elif parsed.path == "/api/point":
                self._handle_point(req_data)
            elif parsed.path == "/api/point/move":
                self._handle_point_move(req_data)
            else:
                self._send_json({"error": "Not Found"}, status=404)
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"error": "internal_server_error", "detail": str(exc)}, status=500)

    def _handle_status(self) -> None:
        ensure_thermal_started()
        snapshot = thermal.get_latest_frame()

        data = {
            "camera_initialized": thermal.camera_initialized,
            "recording": thermal.is_recording,
            "palette": thermal.palette_name,
            "gain": thermal.gain_state,
            "points": thermal.get_measure_points(),
            "points_with_temp": thermal.get_measure_points_with_temperatures(),
            "last_frame_num": thermal.last_frame_num,
            "available_palettes": PALETTE_NAMES,
            "frame_width": snapshot.rgb_data.shape[1] if snapshot else None,
            "frame_height": snapshot.rgb_data.shape[0] if snapshot else None,
            "temp_min_c": snapshot.temp_min_c if snapshot else None,
            "temp_max_c": snapshot.temp_max_c if snapshot else None,
            "min_pos": snapshot.min_pos if snapshot else None,
            "max_pos": snapshot.max_pos if snapshot else None,
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
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_colorbar(self) -> None:
        ensure_thermal_started()
        bar_rgb = thermal.build_colormap_bar()
        bar_img = cv2.resize(bar_rgb, (20, 256), interpolation=cv2.INTER_NEAREST)
        img = Image.fromarray(bar_img)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self._send_bytes(buf.getvalue(), "image/png")

    def _handle_hover(self, parsed) -> None:
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
        path = thermal.save_screenshot()
        if not path:
            self._send_json({"saved": None, "error": "no_frame_available"}, status=503)
            return
        self._send_json({"saved": path})

    def _handle_record_start(self) -> None:
        ensure_thermal_started()
        rec_dir = thermal.start_recording()
        self._send_json({"status": "recording_started", "recording_dir": rec_dir, "recording": True})

    def _handle_record_stop(self) -> None:
        ensure_thermal_started()
        rec_dir = thermal.stop_recording()
        self._send_json({"status": "recording_stopped", "recording_dir": rec_dir, "recording": False})

    def _handle_palette(self, data: dict) -> None:
        ensure_thermal_started()
        palette = data.get("palette")
        if palette: thermal.set_palette(str(palette))
        self._send_json({"palette": thermal.palette_name})

    def _handle_gain(self) -> None:
        ensure_thermal_started()
        self._send_json({"gain": thermal.toggle_gain()})

    def _handle_emissivity(self, data: dict) -> None:
        ensure_thermal_started()
        emissivity = data.get("emissivity")
        if emissivity is not None: thermal.set_emissivity(float(emissivity))
        self._send_json({"emissivity": float(emissivity) if emissivity is not None else 0})

    def _handle_point(self, data: dict) -> None:
        ensure_thermal_started()
        x, y = data.get("x"), data.get("y")
        if x is not None and y is not None:
            thermal.toggle_measure_point(int(round(float(x))), int(round(float(y))))
        self._send_json({"points_with_temp": thermal.get_measure_points_with_temperatures()})

    def _handle_point_move(self, data: dict) -> None:
        ensure_thermal_started()
        idx, x, y = data.get("index"), data.get("x"), data.get("y")
        if idx is not None and x is not None and y is not None:
            thermal.move_measure_point(int(idx), int(round(float(x))), int(round(float(y))))
        self._send_json({"points_with_temp": thermal.get_measure_points_with_temperatures()})

    def _handle_files(self) -> None:
        ss_dir = Path(thermal.screenshot_dir)
        vid_dir = Path(thermal.video_dir)
        
        files = {"screenshots": [], "videos": []}
        
        if ss_dir.exists():
            for f in ss_dir.glob("*.png"):
                files["screenshots"].append({
                    "name": f.name,
                    "url": f"/media_files/screenshots/{f.name}",
                    "time": f.stat().st_mtime
                })
                
        if vid_dir.exists():
            for d in vid_dir.glob("rec_*"):
                if d.is_dir():
                    vid_file = d / "video.mp4"
                    if not vid_file.exists():
                        vid_file = d / "video.mkv"
                    if not vid_file.exists():
                        vid_file = d / "video.avi"
                        
                    if vid_file.exists():
                        files["videos"].append({
                            "name": d.name,
                            "url": f"/media_files/videos/{d.name}/{vid_file.name}",
                            "time": d.stat().st_mtime
                        })
                        
        files["screenshots"].sort(key=lambda x: x["time"], reverse=True)
        files["videos"].sort(key=lambda x: x["time"], reverse=True)
        
        self._send_json(files)

    def _serve_media_file(self, path_str: str) -> None:
        parts = path_str.strip("/").split("/")
        
        if len(parts) >= 3 and parts[1] == "screenshots":
            file_path = Path(thermal.screenshot_dir) / parts[2]
        elif len(parts) >= 4 and parts[1] == "videos":
            file_path = Path(thermal.video_dir) / parts[2] / parts[3]
        else:
            self._send_json({"error": "Bad Request"}, status=400)
            return

        if ".." in path_str:
            self._send_json({"error": "Forbidden"}, status=403)
            return

        self._serve_file(file_path)


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    ensure_thermal_started()
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Web API running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()