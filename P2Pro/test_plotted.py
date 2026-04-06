import threading
import numpy as np
import time
import cv2
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.core.window import Window
from P2Pro.video import Video
from P2Pro.P2Pro_cmd import P2Pro, PropTpdParams

TEMP_LO_C = 32.0
TEMP_HI_C = 35.0
GAIN_MODE = "low"  # Hier kann "low" oder "high" eingestellt werden

class RawThermalApp(App):
    def build(self):
        # --- ANPASSUNG FÜR TOUCHSCREEN ---
        # Setze explizit die Größe und den Vollbildmodus
        Window.size = Window.system_size
        Window.fullscreen = 'auto'  # 'auto' ist oft zuverlässiger als True
        
        self.video = Video()
        self.last_thermal = None
        self.temp_lo = TEMP_LO_C
        self.temp_hi = TEMP_HI_C

        # --- GAIN-MODUS SETZEN ---
        print(f"Versuche, den Gain-Modus auf '{GAIN_MODE}' zu setzen...")
        try:
            p2pro = P2Pro()
            gain_value = 1 if GAIN_MODE.lower() == "high" else 0
            p2pro.set_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL, gain_value)
            time.sleep(0.1) # Kurze Pause, um der Kamera Zeit zur Anpassung zu geben
            current_gain = p2pro.get_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL)
            print(f"Gain-Modus erfolgreich gesetzt auf: {'High' if current_gain == 1 else 'Low'}")
        except Exception as e:
            print(f"WARNUNG: Gain-Modus konnte nicht gesetzt werden: {e}")

        layout = BoxLayout(orientation='vertical')
        self.image = Image(allow_stretch=True)
        layout.add_widget(self.image)

        # Füge eine Touch-Funktion hinzu, die das App beendet
        layout.on_touch_down = self.exit_on_click

        threading.Thread(target=self.video.open, args=(-1,), daemon=True).start()
        Clock.schedule_interval(self.update, 1.0 / 30.0)
        return layout

    def exit_on_click(self, instance, touch):
        App.get_running_app().stop()
        return True  # Event als verarbeitet markieren

    def update(self, dt):
        if not self.video.frame_queue[1].empty():
            frame_data = self.video.frame_queue[1].get()
            if not isinstance(frame_data, dict):
                return
            thermal = frame_data.get("thermal_data")
            if thermal is None:
                return

            temp_c = (thermal.astype(np.float32) / 64.0) - 273.16
            h, w = temp_c.shape
            img = np.zeros((h, w, 3), dtype=np.uint8)

            mask_cold = temp_c < self.temp_lo
            mask_hot = temp_c > self.temp_hi
            mask_red = (~mask_cold) & (~mask_hot)

            # --- Graustufen für alles außerhalb des roten Bereichs ---
            if np.any(mask_cold):
                t_min_cold = np.min(temp_c[mask_cold])
                t_max_cold = np.max(temp_c[mask_cold])
                gray_cold = np.clip((temp_c[mask_cold] - t_min_cold) / (t_max_cold - t_min_cold + 1e-8), 0, 1)
                gray_cold = (gray_cold * 255).astype(np.uint8)
                img[mask_cold] = np.stack([gray_cold]*3, axis=-1)

            if np.any(mask_hot):
                t_min_hot = np.min(temp_c[mask_hot])
                t_max_hot = np.max(temp_c[mask_hot])
                gray_hot = np.clip((temp_c[mask_hot] - t_min_hot) / (t_max_hot - t_min_hot + 1e-8), 0, 1)
                gray_hot = (gray_hot * 255).astype(np.uint8)
                img[mask_hot] = np.stack([gray_hot]*3, axis=-1)

            # --- Dynamischer Rotverlauf im gewählten Bereich ---
            if np.any(mask_red):
                tmin_dyn = np.min(temp_c[mask_red])
                tmax_dyn = np.max(temp_c[mask_red])
                if tmax_dyn - tmin_dyn < 1e-3:
                    norm_red = np.zeros_like(temp_c[mask_red])
                else:
                    norm_red = (temp_c[mask_red] - tmin_dyn) / (tmax_dyn - tmin_dyn)
                r = np.full_like(norm_red, 255, dtype=np.uint8)
                g = (200 * (1 - norm_red)).astype(np.uint8)
                b = (200 * (1 - norm_red)).astype(np.uint8)
                img[mask_red] = np.stack([r, g, b], axis=-1)

            tmax = np.max(temp_c)
            # ---- Maximaltemperatur unten links einblenden ----
            text = f"{tmax:.1f}"
            x = 5
            y = h - 10
            cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)

            texture = Texture.create(size=(w, h), colorfmt='rgb')
            texture.blit_buffer(img.tobytes(), colorfmt='rgb')
            texture.flip_vertical()
            self.image.texture = texture
            self.last_thermal = temp_c.copy()

if __name__ == "__main__":
    RawThermalApp().run()
