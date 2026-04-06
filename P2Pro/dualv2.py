# 1. Notwendige Bibliotheken importieren
import cv2
import numpy as np
import threading
import time
from picamera2 import Picamera2
from libcamera import controls

# Versuch, die P2 Pro Bibliothek zu importieren
try:
    from P2Pro.video import Video
    P2PRO_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    print("WARNUNG: P2Pro.video konnte nicht importiert werden.")
    P2PRO_AVAILABLE = False

# 2. Globale Konfiguration und Variablen
TEMP_LO_C = 30.0  # Untere Schwelle in Celsius für die Hervorhebung
TEMP_HI_C = 50.0  # Obere Schwelle in Celsius für die Hervorhebung

WINDOW_NAME = "Thermal Overlay auf Vollbild"
picam_frame = None
p2pro_data = None  # Speichert das Daten-Dict der P2Pro
stop_threads = False

# 3. Thread-Funktion für die PiCamera
def picam_capture_thread():
    """Liest kontinuierlich Bilder von der PiCamera (limitiert auf 25 FPS)."""
    global picam_frame, stop_threads
    print("Initialisiere PiCamera...")
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (853, 480)}, raw={"size": (2304, 1296)}, format="RGB888"
    )
    picam2.configure(config)
    picam2.set_controls({"FrameRate": 25, "AfMode": controls.AfModeEnum.Continuous})
    picam2.start()
    print("PiCamera-Thread gestartet (25 FPS).")
    while not stop_threads:
        picam_frame = cv2.cvtColor(picam2.capture_array(), cv2.COLOR_RGB2BGR)
        time.sleep(0.005)
    picam2.stop()
    print("PiCamera-Thread gestoppt.")

# 4. Thread-Funktion für die P2 Pro Wärmebildkamera
def thermal_capture_thread():
    """Liest Rohdaten von der P2 Pro Kamera."""
    global p2pro_data, stop_threads
    if not P2PRO_AVAILABLE:
        print("P2 Pro nicht verfügbar. Nutze Platzhalter.")
        placeholder = {"thermal_data": np.full((384, 256), fill_value=int((25 + 273.16) * 64), dtype=np.uint16)}
        while not stop_threads:
            p2pro_data = placeholder
            time.sleep(0.1)
        return

    print("Initialisiere P2 Pro Kamera...")
    p2pro_video = Video()
    try:
        thermal_cam_id = p2pro_video.get_P2Pro_cap_id()
        if thermal_cam_id is None: raise ConnectionError("P2 Pro Kamera nicht gefunden.")
        
        video_thread = threading.Thread(target=p2pro_video.open, args=(thermal_cam_id,), daemon=True)
        video_thread.start()
        print("P2 Pro Kamera-Thread gestartet.")
        while not stop_threads:
            if not p2pro_video.frame_queue[0].empty():
                p2pro_data = p2pro_video.frame_queue[0].get()
            time.sleep(0.01)
    except Exception as e:
        print(f"Fehler im P2 Pro Thread: {e}. Nutze Platzhalter.")
        placeholder = {"thermal_data": np.full((384, 256), fill_value=int((25 + 273.16) * 64), dtype=np.uint16)}
        while not stop_threads:
            p2pro_data = placeholder
            time.sleep(0.1)
    finally:
        if 'p2pro_video' in locals() and p2pro_video.video_running:
            p2pro_video.video_running = False
        print("P2 Pro Kamera-Thread gestoppt.")

def create_highlight_overlay(thermal_data, target_dims):
    """Erzeugt ein halbtransparentes BGRA-Overlay basierend auf Temperaturschwellen."""
    temp_c = (thermal_data.astype(np.float32) / 64.0) - 273.16
    temp_map_resized = cv2.resize(temp_c, target_dims, interpolation=cv2.INTER_NEAREST)
    
    overlay = np.zeros((target_dims[1], target_dims[0], 4), dtype=np.uint8)
    mask_highlight = (temp_map_resized >= TEMP_LO_C) & (temp_map_resized <= TEMP_HI_C)
    
    if np.any(mask_highlight):
        temps_in_range = temp_map_resized[mask_highlight]
        norm = (temps_in_range - TEMP_LO_C) / (TEMP_HI_C - TEMP_LO_C + 1e-8)
        
        overlay[mask_highlight, 0] = 0  # B
        overlay[mask_highlight, 1] = (norm * 255).astype(np.uint8)  # G
        overlay[mask_highlight, 2] = 255  # R
        overlay[mask_highlight, 3] = 150  # Alpha
        
    return overlay

def blend_overlay(background, overlay_bgra):
    """Mischt ein BGRA-Overlay auf ein BGR-Hintergrundbild."""
    alpha = overlay_bgra[:, :, 3] / 255.0
    alpha_3d = alpha[..., np.newaxis]
    
    blended = (1 - alpha_3d) * background + alpha_3d * overlay_bgra[:, :, :3]
    return blended.astype(np.uint8)

# 5. Hauptprogramm
if __name__ == "__main__":
    picam_thread = threading.Thread(target=picam_capture_thread)
    thermal_thread = threading.Thread(target=thermal_capture_thread)
    picam_thread.start()
    thermal_thread.start()
    
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    print("\nAnwendung gestartet. Drücke 'q' zum Beenden.")
    time.sleep(2)

    try:
        while True:
            if cv2.waitKey(1) & 0xFF == ord('q'): break

            if picam_frame is None or p2pro_data is None or "thermal_data" not in p2pro_data:
                continue

            # --- NEUE VERARBEITUNGSREIHENFOLGE ---

            # 1. PiCam-Bild als bildschirmfüllenden Hintergrund vorbereiten
            screen_w, screen_h = 1280, 800
            h_picam, w_picam, _ = picam_frame.shape
            
            scale = max(screen_w / w_picam, screen_h / h_picam)
            new_w, new_h = int(w_picam * scale), int(h_picam * scale)
            resized_picam = cv2.resize(picam_frame, (new_w, new_h))
            
            y_off, x_off = (new_h - screen_h) // 2, (new_w - screen_w) // 2
            picam_fullscreen_bg = resized_picam[y_off:y_off+screen_h, x_off:x_off+screen_w]

            # 2. Thermal-Overlay in der Größe des Hintergrunds erzeugen
            thermal_overlay_fullscreen = create_highlight_overlay(
                p2pro_data["thermal_data"],
                target_dims=(screen_w, screen_h) # Zielgröße ist jetzt der ganze Bildschirm
            )
            
            # 3. Overlay und Hintergrund mischen
            blended_frame = blend_overlay(picam_fullscreen_bg, thermal_overlay_fullscreen)

            # 4. Info-Text hinzufügen
            info_text = f"Highlight: {TEMP_LO_C:.1f}C - {TEMP_HI_C:.1f}C"
            cv2.putText(blended_frame, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(blended_frame, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
            
            # 5. Das finale Bild anzeigen (hat bereits die richtige Größe)
            cv2.imshow(WINDOW_NAME, blended_frame)

    finally:
        print("\nBeende Anwendung...")
        stop_threads = True
        picam_thread.join()
        thermal_thread.join()
        cv2.destroyAllWindows()