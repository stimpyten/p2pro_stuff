# P2Pro Web Thermal Viewer

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-green)
![Status](https://img.shields.io/badge/Status-Active-success)
![License](https://img.shields.io/badge/License-See%20Upstream-lightgrey)
![UI](https://img.shields.io/badge/UI-Web%20App-orange)
![Stream](https://img.shields.io/badge/Stream-MJPEG-blueviolet)

A web-based interface for the **InfiRay P2 Pro thermal camera**, running on a Raspberry Pi. Control your camera, view the live thermal stream, set measurement points, and record data — all from your browser. Also includes a Kivy desktop GUI for direct use on the Pi.

---

## Features

### Live Viewer
- Low-latency MJPEG stream (event-driven, no busy-waiting)
- Real-time thermal visualization with color palettes
- Hover temperature display

### Camera Control
- Palette switching (8 modes)
- Gain toggle (Low / High)
- Emissivity adjustment (live)

### Measurement Points
- Click to set/remove points on the live stream or saved media
- Real-time temperature display per point
- Overlay rendered in browser canvas

### Recording
- Screenshot capture: PNG + raw thermal array (`.npy`) + measurement points (`.json`)
- Video recording: AVI → H.264 MP4 (ffmpeg, background conversion) + `rawframes.npy`
- Raw thermal frames streamed to disk during recording — no RAM buffering

### Media Viewer (Web)
- Browse, view, and delete screenshots and recordings
- Frame-by-frame video scrubbing with thermal overlay
- Thermal data memory-mapped from disk (`mmap`) — large recordings don't OOM

### Server Sync
- Automatically uploads new media to a remote server when the Pi connects to WiFi
- Manual upload trigger via the web UI
- Upload progress exposed via REST API (`/api/upload/status`)
- Tracks already-uploaded bundles — no duplicate uploads

---

## Architecture

```
P2Pro_cmd.py          → Low-level USB commands (pyusb)
    ↓
video.py              → OpenCV frame capture, dual-queue buffering
    ↓
thermal_utils.py      → Standalone helpers (thermal_to_celsius) — no camera deps
thermal_service.py    → Core logic: palettes, gain, emissivity, measurement points, recording
media_service.py      → Screenshot/video file management and metadata
    ↓
web_api.py            → ThreadingHTTPServer :8080, REST endpoints, MJPEG stream
    ↓       services/web/ → index.html, live.html, media.html (Vanilla JS)
upload_service.py     → Pi-side upload client (triggered on WiFi connect or manually)

gui_neu_refactored.py          → Kivy live viewer (ThermalApp)
viewer_app_refactored.py       → Kivy media browser (ViewerApp)
  ├── screenshot_viewer_refactored.py
  └── video_viewer_refactored.py
gui_utils.py                   → Shared Kivy helpers
```

---

## Getting Started

### 1. Install udev rule (once)
```bash
sudo cp 60-p2pro.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 2. Activate environment
```bash
source .venv/bin/activate
```

### 3. Start web server
```bash
python3 -m P2Pro.services.web_api
```

Open `http://<raspberry-pi-ip>:8080/` in your browser.

### Desktop GUI (optional)
```bash
python3 -m P2Pro.gui_neu_refactored       # Live viewer
python3 -m P2Pro.viewer_app_refactored    # Media browser
```

> **Note:** Only one application can access the camera at a time. Do not run the web server and the desktop GUI simultaneously.

---

### Server sync (optional)

Copy and configure the upload client:
```bash
cp upload.conf.example upload.conf
# edit upload.conf: set url and api_key
```

Install the systemd service so it runs automatically on WiFi connect:
```bash
sudo cp upload.service /etc/systemd/system/p2pro-upload.service
sudo systemctl daemon-reload
sudo systemctl enable p2pro-upload.service
```

Or trigger manually from the web UI, or with:
```bash
python3 -m P2Pro.services.upload_service
```

---

## Requirements

- Raspberry Pi 4 (recommended)
- Python 3.11+
- InfiRay P2 Pro camera (USB, Vendor `0x0bda`, Product `0x5830`)
- OpenCV, NumPy, Pillow, pyusb
- ffmpeg (optional — for H.264 MP4 conversion after recording)

---

## REST API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/stream` | GET | MJPEG live stream |
| `/api/frame` | GET | Single JPEG frame |
| `/api/status` | GET | Camera state snapshot |
| `/api/palette` | POST | Switch color palette |
| `/api/gain` | POST | Toggle gain mode |
| `/api/emissivity` | POST | Set emissivity |
| `/api/screenshot` | POST | Save screenshot bundle |
| `/api/record/start` `/stop` | POST | Start/stop video recording |
| `/api/point` | POST | Toggle measurement point |
| `/api/point/move` | POST | Move measurement point |
| `/api/hover` | GET | Temperature at cursor position |
| `/api/media/*` | GET/POST | File listing, serving, deletion |
| `/api/upload/status` | GET | Upload progress and state |
| `/api/upload/trigger` | POST | Manually trigger upload to server |

---

## Credits

Built on top of the original work by **LeoDJ**:
[https://github.com/LeoDJ/P2Pro-Viewer](https://github.com/LeoDJ/P2Pro-Viewer)

Upstream provides core camera communication, raw thermal data access, and the base rendering pipeline.
