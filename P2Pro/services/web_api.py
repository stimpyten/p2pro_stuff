from __future__ import annotations

import io
import json
import mimetypes
import os
import time
import traceback
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

import cv2
import numpy as np
from PIL import Image

from P2Pro.services.media_service import MediaService
from P2Pro.services.thermal_service import PALETTE_NAMES, ThermalService


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

thermal = ThermalService()
media_service = MediaService(
    screenshots_dir=thermal.screenshot_dir,
    videos_dir=thermal.video_dir,
)

# Einfache In-Memory-Caches, damit Rohdaten/Videos nicht bei jedem Hover neu geladen werden
_media_cache: dict[tuple[str, str], Any] = {}

# Wichtige Video-Mimetypes für den Media Viewer
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("video/x-msvideo", ".avi")


def ensure_thermal_started() -> None:
    if not thermal.camera_initialized:
        thermal.initialize(palette_name="White Hot", gain_mode="Low")
    thermal.start_video()


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def thermal_to_celsius(raw_value: float) -> float:
    return round((float(raw_value) / 64.0) - 273.15, 1)


def get_temp_range_from_thermal(thermal_frame: np.ndarray) -> dict[str, Any]:
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(thermal_frame)
    return {
        "temp_min_c": thermal_to_celsius(min_val),
        "temp_max_c": thermal_to_celsius(max_val),
        "min_pos": [int(min_loc[0]), int(min_loc[1])],
        "max_pos": [int(max_loc[0]), int(max_loc[1])],
    }


def get_point_temp_from_thermal(thermal_frame: np.ndarray, x: int, y: int) -> float | None:
    if thermal_frame is None:
        return None
    h, w = thermal_frame.shape[:2]
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    return thermal_to_celsius(thermal_frame[y, x])


def normalize_points(points: list[Any]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for item in points:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((int(round(float(item[0]))), int(round(float(item[1])))))
    return out


def toggle_point(points: list[tuple[int, int]], x: int, y: int, threshold: int = 8) -> list[tuple[int, int]]:
    new_points = list(points)
    for idx, (px, py) in enumerate(new_points):
        if abs(px - x) <= threshold and abs(py - y) <= threshold:
            del new_points[idx]
            return new_points
    new_points.append((int(x), int(y)))
    return new_points


def move_point(points: list[tuple[int, int]], index: int, x: int, y: int) -> list[tuple[int, int]]:
    new_points = list(points)
    if 0 <= index < len(new_points):
        new_points[index] = (int(x), int(y))
    return new_points


def points_with_temp(points: list[tuple[int, int]], thermal_frame: np.ndarray) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for x, y in points:
        result.append(
            {
                "x": int(x),
                "y": int(y),
                "temp_c": get_point_temp_from_thermal(thermal_frame, x, y),
            }
        )
    return result


def resolve_media_url_to_path(url: str) -> Path:
    parsed = urlparse(unquote(url))
    parts = parsed.path.strip("/").split("/")

    if ".." in parts:
        raise ValueError("Ungültiger Pfad")

    if len(parts) >= 3 and parts[0] == "media_files" and parts[1] == "screenshots":
        return Path(thermal.screenshot_dir) / parts[2]

    if len(parts) >= 4 and parts[0] == "media_files" and parts[1] == "videos":
        return Path(thermal.video_dir) / parts[2] / parts[3]

    raise ValueError("Unbekannte Media-URL")


def get_cached_screenshot(image_file: str):
    key = ("screenshot", image_file)
    bundle = _media_cache.get(key)
    if bundle is None:
        bundle = media_service.load_screenshot(image_file)
        _media_cache[key] = bundle
    return bundle


def get_cached_video(video_file: str):
    key = ("video", video_file)
    bundle = _media_cache.get(key)
    if bundle is None:
        bundle = media_service.load_video(video_file)
        _media_cache[key] = bundle
    return bundle


def invalidate_media_cache_for_path(path_str: str) -> None:
    _media_cache.pop(("screenshot", path_str), None)
    _media_cache.pop(("video", path_str), None)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "P2ProWebAPI/1.4"

    def log_message(self, format: str, *args) -> None:
        pass

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
            elif parsed.path == "/api/media/info":
                self._handle_media_info(parsed)
            elif parsed.path == "/api/media/frame-data":
                self._handle_media_frame_data(parsed)
            elif parsed.path == "/api/media/hover":
                self._handle_media_hover(parsed)
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
            elif parsed.path == "/api/media/points/toggle":
                self._handle_media_points_toggle(req_data)
            elif parsed.path == "/api/media/points/move":
                self._handle_media_points_move(req_data)
            elif parsed.path == "/api/media/points/save":
                self._handle_media_points_save(req_data)
            elif parsed.path == "/api/media/video-frame-screenshot":
                self._handle_media_video_frame_screenshot(req_data)
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
        if palette:
            thermal.set_palette(str(palette))
        self._send_json({"palette": thermal.palette_name})

    def _handle_gain(self) -> None:
        ensure_thermal_started()
        self._send_json({"gain": thermal.toggle_gain()})

    def _handle_emissivity(self, data: dict) -> None:
        ensure_thermal_started()
        emissivity = data.get("emissivity")
        if emissivity is not None:
            thermal.set_emissivity(float(emissivity))
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
                files["screenshots"].append(
                    {
                        "name": f.name,
                        "url": f"/media_files/screenshots/{f.name}",
                        "time": f.stat().st_mtime,
                    }
                )

        if vid_dir.exists():
            for d in vid_dir.glob("rec_*"):
                if d.is_dir():
                    vid_file = d / "video.mp4"
                    if not vid_file.exists():
                        vid_file = d / "video.mkv"
                    if not vid_file.exists():
                        vid_file = d / "video.avi"

                    if vid_file.exists():
                        files["videos"].append(
                            {
                                "name": d.name,
                                "url": f"/media_files/videos/{d.name}/{vid_file.name}",
                                "time": d.stat().st_mtime,
                            }
                        )

        files["screenshots"].sort(key=lambda x: x["time"], reverse=True)
        files["videos"].sort(key=lambda x: x["time"], reverse=True)

        self._send_json(files)

    def _handle_media_info(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        media_type = qs.get("type", [""])[0]
        media_url = qs.get("url", [""])[0]

        if not media_type or not media_url:
            self._send_json({"error": "type und url sind erforderlich"}, status=400)
            return

        path = str(resolve_media_url_to_path(media_url))

        if media_type == "screenshot":
            bundle = get_cached_screenshot(path)
            info = get_temp_range_from_thermal(bundle.thermal)
            self._send_json(
                {
                    "type": "screenshot",
                    "url": media_url,
                    "width": int(bundle.rgb_image.shape[1]),
                    "height": int(bundle.rgb_image.shape[0]),
                    "frame_count": 1,
                    "points": [[int(x), int(y)] for x, y in bundle.measure_points],
                    "points_with_temp": points_with_temp(bundle.measure_points, bundle.thermal),
                    **info,
                }
            )
            return

        if media_type == "video":
            bundle = get_cached_video(path)
            frame_index = 0
            thermal_frame = bundle.thermal_frames[frame_index]
            info = get_temp_range_from_thermal(thermal_frame)
            self._send_json(
                {
                    "type": "video",
                    "url": media_url,
                    "width": int(bundle.rgb_frames[0].shape[1]) if bundle.rgb_frames else None,
                    "height": int(bundle.rgb_frames[0].shape[0]) if bundle.rgb_frames else None,
                    "frame_count": int(len(bundle.rgb_frames)),
                    "points": [[int(x), int(y)] for x, y in bundle.measure_points],
                    "points_with_temp": points_with_temp(bundle.measure_points, thermal_frame),
                    **info,
                }
            )
            return

        self._send_json({"error": "Unbekannter type"}, status=400)

    def _handle_media_frame_data(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        media_type = qs.get("type", [""])[0]
        media_url = qs.get("url", [""])[0]
        frame_index = int(qs.get("frame", ["0"])[0])

        if not media_type or not media_url:
            self._send_json({"error": "type und url sind erforderlich"}, status=400)
            return

        path = str(resolve_media_url_to_path(media_url))

        if media_type == "screenshot":
            bundle = get_cached_screenshot(path)
            info = get_temp_range_from_thermal(bundle.thermal)
            self._send_json(
                {
                    "frame": 0,
                    "points_with_temp": points_with_temp(bundle.measure_points, bundle.thermal),
                    **info,
                }
            )
            return

        if media_type == "video":
            bundle = get_cached_video(path)
            if not bundle.rgb_frames or bundle.thermal_frames.size == 0:
                self._send_json({"error": "Keine Frames vorhanden"}, status=404)
                return

            frame_index = max(0, min(frame_index, len(bundle.rgb_frames) - 1))
            thermal_frame = bundle.thermal_frames[frame_index]
            info = get_temp_range_from_thermal(thermal_frame)
            self._send_json(
                {
                    "frame": frame_index,
                    "points_with_temp": points_with_temp(bundle.measure_points, thermal_frame),
                    **info,
                }
            )
            return

        self._send_json({"error": "Unbekannter type"}, status=400)

    def _handle_media_hover(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        media_type = qs.get("type", [""])[0]
        media_url = qs.get("url", [""])[0]
        x = int(qs.get("x", ["0"])[0])
        y = int(qs.get("y", ["0"])[0])
        frame_index = int(qs.get("frame", ["0"])[0])

        if not media_type or not media_url:
            self._send_json({"error": "type und url sind erforderlich"}, status=400)
            return

        path = str(resolve_media_url_to_path(media_url))

        if media_type == "screenshot":
            bundle = get_cached_screenshot(path)
            self._send_json({"temp_c": get_point_temp_from_thermal(bundle.thermal, x, y)})
            return

        if media_type == "video":
            bundle = get_cached_video(path)
            if not bundle.rgb_frames or bundle.thermal_frames.size == 0:
                self._send_json({"error": "Keine Frames vorhanden"}, status=404)
                return
            frame_index = max(0, min(frame_index, len(bundle.rgb_frames) - 1))
            thermal_frame = bundle.thermal_frames[frame_index]
            self._send_json({"temp_c": get_point_temp_from_thermal(thermal_frame, x, y)})
            return

        self._send_json({"error": "Unbekannter type"}, status=400)

    def _handle_media_points_toggle(self, data: dict) -> None:
        media_type = str(data.get("type", ""))
        media_url = str(data.get("url", ""))
        x = int(round(float(data.get("x", 0))))
        y = int(round(float(data.get("y", 0))))
        frame_index = int(round(float(data.get("frame", 0))))

        path = str(resolve_media_url_to_path(media_url))

        if media_type == "screenshot":
            bundle = get_cached_screenshot(path)
            bundle.measure_points = toggle_point(bundle.measure_points, x, y)
            self._send_json(
                {
                    "points": [[int(px), int(py)] for px, py in bundle.measure_points],
                    "points_with_temp": points_with_temp(bundle.measure_points, bundle.thermal),
                }
            )
            return

        if media_type == "video":
            bundle = get_cached_video(path)
            bundle.measure_points = toggle_point(bundle.measure_points, x, y)
            frame_index = max(0, min(frame_index, len(bundle.rgb_frames) - 1))
            thermal_frame = bundle.thermal_frames[frame_index]
            self._send_json(
                {
                    "points": [[int(px), int(py)] for px, py in bundle.measure_points],
                    "points_with_temp": points_with_temp(bundle.measure_points, thermal_frame),
                }
            )
            return

        self._send_json({"error": "Unbekannter type"}, status=400)

    def _handle_media_points_move(self, data: dict) -> None:
        media_type = str(data.get("type", ""))
        media_url = str(data.get("url", ""))
        index = int(round(float(data.get("index", -1))))
        x = int(round(float(data.get("x", 0))))
        y = int(round(float(data.get("y", 0))))
        frame_index = int(round(float(data.get("frame", 0))))

        path = str(resolve_media_url_to_path(media_url))

        if media_type == "screenshot":
            bundle = get_cached_screenshot(path)
            bundle.measure_points = move_point(bundle.measure_points, index, x, y)
            self._send_json(
                {
                    "points": [[int(px), int(py)] for px, py in bundle.measure_points],
                    "points_with_temp": points_with_temp(bundle.measure_points, bundle.thermal),
                }
            )
            return

        if media_type == "video":
            bundle = get_cached_video(path)
            bundle.measure_points = move_point(bundle.measure_points, index, x, y)
            frame_index = max(0, min(frame_index, len(bundle.rgb_frames) - 1))
            thermal_frame = bundle.thermal_frames[frame_index]
            self._send_json(
                {
                    "points": [[int(px), int(py)] for px, py in bundle.measure_points],
                    "points_with_temp": points_with_temp(bundle.measure_points, thermal_frame),
                }
            )
            return

        self._send_json({"error": "Unbekannter type"}, status=400)

    def _handle_media_points_save(self, data: dict) -> None:
        media_type = str(data.get("type", ""))
        media_url = str(data.get("url", ""))
        path = str(resolve_media_url_to_path(media_url))

        if media_type == "screenshot":
            bundle = get_cached_screenshot(path)
            points_file = media_service.save_screenshot_measure_points(path, bundle.measure_points)
            self._send_json({"saved": points_file, "points": [[int(x), int(y)] for x, y in bundle.measure_points]})
            return

        if media_type == "video":
            bundle = get_cached_video(path)
            points_file = media_service.save_video_measure_points(path, bundle.measure_points)
            self._send_json({"saved": points_file, "points": [[int(x), int(y)] for x, y in bundle.measure_points]})
            return

        self._send_json({"error": "Unbekannter type"}, status=400)

    def _handle_media_video_frame_screenshot(self, data: dict) -> None:
        media_url = str(data.get("url", ""))
        frame_index = int(round(float(data.get("frame", 0))))
        path = str(resolve_media_url_to_path(media_url))

        bundle = get_cached_video(path)
        if not bundle.rgb_frames or bundle.thermal_frames.size == 0:
            self._send_json({"error": "Keine Frames vorhanden"}, status=404)
            return

        frame_index = max(0, min(frame_index, len(bundle.rgb_frames) - 1))
        result = media_service.save_video_frame_as_screenshot(
            video_file=path,
            frame_index=frame_index,
            rgb_frame=bundle.rgb_frames[frame_index],
            thermal_frame=bundle.thermal_frames[frame_index],
            measure_points=bundle.measure_points,
        )
        invalidate_media_cache_for_path(path)
        self._send_json(result)

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