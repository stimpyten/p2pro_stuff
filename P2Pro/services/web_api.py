import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from PIL import Image
import threading

from P2Pro.services.thermal_service import ThermalService
from P2Pro.services.media_service import MediaService

thermal = ThermalService()
media = MediaService()


class RequestHandler(BaseHTTPRequestHandler):

    def _set_headers(self, content_type="application/json"):
        self.send_response(200)
        self.send_header("Content-type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/status":
            self._handle_status()

        elif parsed.path == "/api/frame":
            self._handle_frame()

        elif parsed.path == "/api/screenshots":
            self._handle_screenshots()

        elif parsed.path == "/api/videos":
            self._handle_videos()

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)

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

        else:
            self.send_error(404, "Not Found")

    # -----------------------------
    # Handlers
    # -----------------------------

    def _handle_status(self):
        data = {
            "recording": thermal.is_recording,
            "palette": thermal.current_palette,
            "gain": thermal.gain_state,
            "points": thermal.measure_points,
        }
        self._set_headers()
        self.wfile.write(json.dumps(data).encode())

    def _handle_frame(self):
        frame = thermal.get_latest_frame()
        if frame is None:
            self.send_error(500, "No frame available")
            return

        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")

        self._set_headers("image/jpeg")
        self.wfile.write(buf.getvalue())

    def _handle_screenshots(self):
        shots = media.list_screenshots()
        self._set_headers()
        self.wfile.write(json.dumps(shots).encode())

    def _handle_videos(self):
        vids = media.list_videos()
        self._set_headers()
        self.wfile.write(json.dumps(vids).encode())

    def _handle_screenshot(self):
        path = thermal.save_screenshot()
        self._set_headers()
        self.wfile.write(json.dumps({"saved": path}).encode())

    def _handle_record_start(self):
        thermal.start_recording()
        self._set_headers()
        self.wfile.write(json.dumps({"status": "recording_started"}).encode())

    def _handle_record_stop(self):
        thermal.stop_recording()
        self._set_headers()
        self.wfile.write(json.dumps({"status": "recording_stopped"}).encode())

    def _handle_palette(self):
        length = int(self.headers.get('Content-Length'))
        body = self.rfile.read(length)
        data = json.loads(body)

        palette = data.get("palette")
        if palette:
            thermal.set_palette(palette)

        self._set_headers()
        self.wfile.write(json.dumps({"palette": palette}).encode())

    def _handle_gain(self):
        thermal.toggle_gain()
        self._set_headers()
        self.wfile.write(json.dumps({"gain": thermal.gain_state}).encode())


def run_server(host="0.0.0.0", port=8080):
    server = HTTPServer((host, port), RequestHandler)
    print(f"Web API running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()