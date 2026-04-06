# 🔥 P2Pro Web Thermal Viewer

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-green)
![Status](https://img.shields.io/badge/Status-Active-success)
![License](https://img.shields.io/badge/License-See%20Upstream-lightgrey)
![UI](https://img.shields.io/badge/UI-Web%20App-orange)
![Stream](https://img.shields.io/badge/Stream-MJPEG-blueviolet)

A modern **web-based interface** for the **InfiRay P2 Pro thermal camera**, running on a Raspberry Pi.

Control your camera, view the live thermal stream, set measurement points, and record data — all directly from your browser.

---

## 🚀 Features

### 🎥 Live Viewer

* Low-latency MJPEG stream
* Real-time thermal visualization
* Smooth browser-based rendering

### 🎛️ Camera Control

* Palette switching (instant)
* Gain toggle
* Emissivity adjustment (live)
* No page reload required

### 📍 Measurement Points

* Click to set/remove points
* Real-time temperature display
* Multiple points supported
* Overlay rendered in browser

### 📸 Recording

* Screenshot capture (PNG + raw data)
* Video recording (MKV + raw frames)
* Measurement points saved with recordings

---

## 🖥️ Architecture

```text
Raspberry Pi + P2Pro Camera
        │
        ▼
 ThermalService (Python backend)
        │
        ▼
 Web API (Threaded HTTP Server)
        │
        ▼
 Browser (Live Web UI)
```

---

## ⚡ Getting Started

### 1. Activate environment

```bash
cd ~/P2Pro-Viewer
source venv/bin/activate
```

### 2. Start server

```bash
python3 -m P2Pro.services.web_api
```

### 3. Open browser

```text
http://<raspberry-pi-ip>:8080/
```

---

## 📂 Project Structure

```text
P2Pro/
 ├── services/
 │   ├── thermal_service.py   # Camera logic & processing
 │   ├── web_api.py           # API + web server
 │   └── web/
 │       ├── index.html       # Entry page
 │       └── live.html        # Live viewer UI
 ├── video.py                 # Frame capture
 └── P2Pro_cmd.py             # Low-level camera control
```

---

## ⚙️ Requirements

* Raspberry Pi 4 (recommended)
* Python 3.11+
* InfiRay P2 Pro camera
* OpenCV
* NumPy
* PIL

---

## ⚠️ Important Notes

* Only **one application** can access the camera at a time
* Do **not** run `gui_neu.py` and the web app simultaneously
* For best performance:

  * Use direct USB connection
  * Ensure stable power supply

---

## 🙏 Credits

This project is built on top of the excellent work by
👉 LeoDJ

Original project:

🔗 https://github.com/LeoDJ/P2Pro-Viewer

Without this foundation, this project would not be possible.

### Upstream provides:

* Core camera communication
* Access to raw thermal data
* Base rendering pipeline

### This project adds:

* Web-based UI
* Remote control via browser
* Improved UX
* Measurement overlays
* Recording enhancements

---

## 🧠 Roadmap

* [ ] Media Viewer (images & videos)
* [ ] Advanced measurement tools
* [ ] Temperature graphs
* [ ] GUI remote control (mirror logic)
* [ ] UI improvements & touch support

---

## 🤝 Contributing

Contributions, ideas and improvements are welcome.

---

## 📜 License

Please refer to the upstream project license:

🔗 https://github.com/LeoDJ/P2Pro-Viewer
