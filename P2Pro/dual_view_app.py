# 1. Notwendige Bibliotheken importieren
import cv2
import numpy as np
import threading
import time
from picamera2 import Picamera2
from libcamera import controls

# Versuch, die P2 Pro Bibliothek zu importieren und einen Schalter zu setzen
try:
    from P2Pro.video import Video
    P2PRO_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    print("WARNUNG: P2Pro.video konnte nicht importiert werden. Stelle sicher, dass die Datei existiert.")
    P2PRO_AVAILABLE = False

# 2. Fenster- und Auflösungseinstellungen
WINDOW_NAME = "Dual-Kamera-Overlay (PiCam & Thermal)"

# Globale Variablen für die Frames und Steuerung
picam_frame = None
thermal_frame = None
stop_threads = False
overlay_alpha = 0.5  # Startwert für die Transparenz (0.0 bis 1.0)

# 3. Thread-Funktion für die PiCamera
def capture_picam():
    global picam_frame, stop_threads
    
    print("Initialisiere PiCamera...")
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (853, 480), "format": "RGB888"},
        raw={"size": (2304, 1296)}
    )
    picam2.configure(config)
    print("PiCamera-Modus mit Downscaling konfiguriert (voller Bildausschnitt).")
    
    picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous, "FrameRate": 25})
    print("PiCamera auf 25 FPS limitiert.")
    
    picam2.start()
    print("PiCamera gestartet.")

    while not stop_threads:
        frame_rgb = picam2.capture_array()
        picam_frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        time.sleep(0.005)

    picam2.stop()
    print("PiCamera gestoppt.")

# 4. Thread-Funktion für die P2 Pro Thermal Camera
def capture_thermal():
    global thermal_frame, stop_threads, P2PRO_AVAILABLE
    
    display_height_for_fallback = 480
    if not P2PRO_AVAILABLE:
        placeholder_width = int(display_height_for_fallback * (256 / 384))
        print("P2 Pro Kamera-Modul nicht verfügbar, zeige schwarzes Bild.")
        while not stop_threads:
            thermal_frame = np.zeros((display_height_for_fallback, placeholder_width, 3), dtype=np.uint8)
            time.sleep(0.1)
        return

    print("Initialisiere P2 Pro Wärmebildkamera...")
    p2pro_video = Video()
    try:
        thermal_cam_id = p2pro_video.get_P2Pro_cap_id()
        if thermal_cam_id is None:
            print("P2 Pro Kamera nicht gefunden! Zeige schwarzes Bild.")
            placeholder_width = int(display_height_for_fallback * (256 / 384))
            while not stop_threads:
                thermal_frame = np.zeros((display_height_for_fallback, placeholder_width, 3), dtype=np.uint8)
                time.sleep(0.1)
            return

        p2pro_video_thread = threading.Thread(target=p2pro_video.open, args=(thermal_cam_id,), daemon=True)
        p2pro_video_thread.start()
        print("P2 Pro Kamera-Thread gestartet.")

        while not stop_threads:
            if not p2pro_video.frame_queue[0].empty():
                frame_data = p2pro_video.frame_queue[0].get()
                if isinstance(frame_data, dict) and "rgb_data" in frame_data:
                    thermal_frame = cv2.cvtColor(frame_data["rgb_data"], cv2.COLOR_RGB2BGR)
            time.sleep(0.01)
    finally:
        if 'p2pro_video' in locals() and p2pro_video.video_running:
            p2pro_video.video_running = False
        print("P2 Pro Kamera gestoppt.")

# 5. Hauptprogramm starten
if __name__ == "__main__":
    picam_thread = threading.Thread(target=capture_picam)
    thermal_thread = threading.Thread(target=capture_thermal)
    
    print("Starte Kamera-Threads...")
    picam_thread.start()
    thermal_thread.start()
    
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    print("Vollbild-Fenster wird erstellt...")
    print("Steuerung: 'q' zum Beenden, 'w'/'s' zur Anpassung des Overlays.")
    
    time.sleep(2)

    try:
        while True:
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('w'):
                overlay_alpha = min(1.0, overlay_alpha + 0.05)
            elif key == ord('s'):
                overlay_alpha = max(0.0, overlay_alpha - 0.05)

            if picam_frame is not None and thermal_frame is not None:
                if picam_frame.shape[0] == 0 or thermal_frame.shape[0] == 0:
                    continue

                h_picam, w_picam, _ = picam_frame.shape
                h_thermal, w_thermal, _ = thermal_frame.shape
                
                target_aspect_ratio = w_thermal / h_thermal
                new_w_picam = int(h_picam * target_aspect_ratio)
                start_x = (w_picam - new_w_picam) // 2
                picam_cropped = picam_frame[:, start_x : start_x + new_w_picam]
                
                h_crop, w_crop, _ = picam_cropped.shape
                thermal_resized_for_overlay = cv2.resize(thermal_frame, (w_crop, h_crop))
                
                overlay_frame = cv2.addWeighted(
                    picam_cropped, 1 - overlay_alpha, 
                    thermal_resized_for_overlay, overlay_alpha, 0
                )
                
                info_text = f"Thermal Overlay: {int(overlay_alpha * 100)}% (W/S)"
                cv2.putText(overlay_frame, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(overlay_frame, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)

                # --- NEUE LOGIK FÜR BILDSCHIRMFÜLLENDE SKALIERUNG (COVER/FILL) ---
                _, _, screen_w, screen_h = cv2.getWindowImageRect(WINDOW_NAME)
                if screen_w > 0 and screen_h > 0:
                    h_overlay, w_overlay, _ = overlay_frame.shape
                    
                    # Berechne Skalierungsfaktoren für Höhe und Breite
                    scale_w = screen_w / w_overlay
                    scale_h = screen_h / h_overlay
                    
                    # Wähle den GRÖSSEREN Faktor, um den Bildschirm zu füllen
                    scale = max(scale_w, scale_h)
                    
                    # Berechne die neuen Dimensionen; eine davon wird größer als der Bildschirm sein
                    new_w = int(w_overlay * scale)
                    new_h = int(h_overlay * scale)
                        
                    resized_overlay = cv2.resize(overlay_frame, (new_w, new_h))
                    
                    # Berechne die Startpunkte für einen zentrierten Crop
                    x_offset = (new_w - screen_w) // 2
                    y_offset = (new_h - screen_h) // 2
                    
                    # Schneide das Bild auf die exakte Bildschirmgröße zu
                    display_frame = resized_overlay[y_offset:y_offset+screen_h, x_offset:x_offset+screen_w]
                    
                    cv2.imshow(WINDOW_NAME, display_frame)

    finally:
        print("Beende Programm...")
        stop_threads = True
        picam_thread.join()
        thermal_thread.join()
        cv2.destroyAllWindows()