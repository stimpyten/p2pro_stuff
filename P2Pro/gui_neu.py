import threading
import numpy as np
import time
import cv2
import json
import os
import subprocess
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.graphics.texture import Texture
from kivy.graphics import Rectangle
from kivy.clock import Clock
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.core.window import Window
from kivy.uix.settings import SettingsWithSidebar

from P2Pro.video import Video
from P2Pro.P2Pro_cmd import P2Pro, PseudoColorTypes, PropTpdParams

PALETTE_MAP = {
    "White Hot": PseudoColorTypes.PSEUDO_WHITE_HOT,
    "Iron Red": PseudoColorTypes.PSEUDO_IRON_RED,
    "Rainbow 1": PseudoColorTypes.PSEUDO_RAINBOW_1,
    "Rainbow 2": PseudoColorTypes.PSEUDO_RAINBOW_2,
    "Rainbow 3": PseudoColorTypes.PSEUDO_RAINBOW_3,
    "Red Hot": PseudoColorTypes.PSEUDO_RED_HOT,
    "Hot Red": PseudoColorTypes.PSEUDO_HOT_RED,
    "Black Hot": PseudoColorTypes.PSEUDO_BLACK_HOT,
}
PALETTE_NAMES = list(PALETTE_MAP.keys())

OPENCV_COLORMAP_MAP = {
    "White Hot": None,
    "Iron Red": cv2.COLORMAP_INFERNO,
    "Rainbow 1": cv2.COLORMAP_RAINBOW,
    "Rainbow 2": cv2.COLORMAP_JET,
    "Rainbow 3": cv2.COLORMAP_PARULA if hasattr(cv2, 'COLORMAP_PARULA') else cv2.COLORMAP_WINTER,
    "Red Hot": cv2.COLORMAP_HOT,
    "Hot Red": cv2.COLORMAP_AUTUMN,
    "Black Hot": cv2.COLORMAP_BONE,
}

def draw_text_with_outline(img, text, org, font, font_scale, color_fg, color_outline=(0,0,0), thickness_fg=1, thickness_outline=3):
    cv2.putText(img, text, org, font, font_scale, color_outline, thickness_outline, cv2.LINE_AA)
    cv2.putText(img, text, org, font, font_scale, color_fg, thickness_fg, cv2.LINE_AA)

def draw_cross_with_outline(img, pos, color_fg=(255,255,255), color_outline=(0,0,0), size=6, thickness_fg=1, thickness_outline=3):
    x, y = pos
    cv2.line(img, (x-size, y), (x+size, y), color_outline, thickness_outline, cv2.LINE_AA)
    cv2.line(img, (x, y-size), (x, y+size), color_outline, thickness_outline, cv2.LINE_AA)
    cv2.line(img, (x-size, y), (x+size, y), color_fg, thickness_fg, cv2.LINE_AA)
    cv2.line(img, (x, y-size), (x, y+size), color_fg, thickness_fg, cv2.LINE_AA)

class ClickableImage(Image):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.click_callback = None

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        if self.texture is None:
            return super().on_touch_down(touch)

        w_tex, h_tex = self.texture.size
        w_widget, h_widget = self.size
        x_widget, y_widget = self.pos

        aspect_tex = w_tex / h_tex
        aspect_widget = w_widget / h_widget

        if aspect_tex > aspect_widget:
            scale = w_widget / w_tex
            disp_w = w_widget
            disp_h = h_tex * scale
            offset_x = x_widget
            offset_y = y_widget + (h_widget - disp_h) / 2
        else:
            scale = h_widget / h_tex
            disp_w = w_tex * scale
            disp_h = h_widget
            offset_x = x_widget + (w_widget - disp_w) / 2
            offset_y = y_widget

        if not (offset_x <= touch.x <= offset_x + disp_w and offset_y <= touch.y <= offset_y + disp_h):
            return super().on_touch_down(touch)

        x_rel = (touch.x - offset_x) / disp_w
        y_rel = (touch.y - offset_y) / disp_h
        x_img = int(np.clip(x_rel * w_tex, 0, w_tex-1))
        y_img = int(np.clip((1 - y_rel) * h_tex, 0, h_tex-1))

        if self.click_callback:
            self.click_callback((x_img, y_img), button=touch.button)
        return super().on_touch_down(touch)

class ColorScale(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.texture = None
        self.rect = None
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_texture(self, rgb_bar_img):
        BAR_WIDTH = int(self.width) if self.width else 16
        bar = np.repeat(rgb_bar_img, BAR_WIDTH, axis=1)
        self.texture = Texture.create(size=(BAR_WIDTH, 256), colorfmt='rgb')
        self.texture.blit_buffer(bar.tobytes(), colorfmt='rgb')
        self.texture.flip_vertical()
        self.update_canvas()

    def update_canvas(self, *args):
        self.canvas.clear()
        if self.texture:
            with self.canvas:
                self.rect = Rectangle(texture=self.texture, pos=self.pos, size=self.size)

class ThermalApp(App):
    def build_config(self, config):
        config.setdefaults('Pfade', {'screenshot_dir': 'screenshots', 'video_dir': 'videos'})
        config.setdefaults('Standardwerte', {'palette': 'White Hot', 'gain': 'Low'})
        # <<< NEU: Standardwert für die Vollbild-Einstellung hinzufügen >>>
        config.setdefaults('Anzeige', {'fullscreen': '1'}) # '1' für True

    def build_settings(self, settings):
        settings.add_json_panel('App Einstellungen', self.config, 'settings.json')
        settings.interface.bind(on_close=self.on_settings_close)

    def on_config_change(self, config, section, key, value):
        print(f"Konfiguration geändert: Sektion={section}, Key={key}, Wert={value}")
        if not self.camera_initialized:
            print("Änderung wird ignoriert, da die Kamera noch nicht bereit ist.")
            return
        
        if key == 'palette':
            self.palette_spinner.text = value
            self.set_camera_palette(value)
        elif key == 'gain':
            self.set_gain_from_config(value)
        # <<< NEU: Benutzer über notwendigen Neustart informieren >>>
        elif section == 'Anzeige' and key == 'fullscreen':
            print("Vollbildmodus-Einstellung geändert. Bitte starten Sie die App neu, damit die Änderung wirksam wird.")

    def on_settings_close(self, *args):
        print("Einstellungsfenster geschlossen.")
        
    def set_gain_from_config(self, gain_str):
        if not self.p2pro: return
        try:
            new_state = 1 if gain_str.lower() == 'high' else 0
            self.p2pro.set_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL, new_state)
            time.sleep(0.05)
            self.get_gain_status()
        except Exception as e:
            print(f"Gain konnte nicht aus Konfiguration gesetzt werden: {e}")
            
    def initialize_camera_and_video(self):
        try:
            print("Initialisiere Kamera-Hardware...")
            self.p2pro = P2Pro()

            self.palette_name = self.config.get('Standardwerte', 'palette')
            self.default_gain = self.config.get('Standardwerte', 'gain')
            
            print(f"Setze Start-Farbpalette auf: {self.palette_name}")
            self.set_camera_palette(self.palette_name)
            time.sleep(0.1)

            print(f"Setze Start-Gain-Modus auf: {self.default_gain}")
            self.set_gain_from_config(self.default_gain)
            
            self.palette_spinner.text = self.palette_name

            print("Initialisierung abgeschlossen. UI-Updates werden jetzt aktiviert.")
            self.camera_initialized = True

            print("Starte Video-Erfassungsschleife...")
            self.video.open(-1)

        except Exception as e:
            print(f"FATAL: Fehler bei der Kamera-Initialisierung oder Video-Erfassung: {e}")

    def build(self):
        # <<< NEU: Vollbildmodus basierend auf der Config direkt am Anfang setzen >>>
        try:
            if self.config.getboolean('Anzeige', 'fullscreen'):
                Window.fullscreen = 'auto'
            else:
                Window.fullscreen = False
        except Exception as e:
            print(f"Fehler beim Setzen des Vollbildmodus: {e}. Verwende Standard (auto).")
            Window.fullscreen = 'auto'

        self.use_kivy_settings = True
        
        self.video = Video()
        self.last_rgb = None
        self.last_thermal = None
        self.measure_points = []
        self.is_recording = False
        self.recording_dir = None
        self.raw_frames = []
        self.gain_state = 0
        self.p2pro = None
        self.camera_initialized = False

        self.screenshots_dir = self.config.get('Pfade', 'screenshot_dir')
        self.videos_dir = self.config.get('Pfade', 'video_dir')

        root_layout = AnchorLayout()
        main_content = BoxLayout(orientation='horizontal', padding=10, spacing=10)
        
        self.image = ClickableImage(allow_stretch=True)
        self.image.click_callback = self.on_image_click
        main_content.add_widget(self.image)

        scale_container = BoxLayout(orientation='vertical', size_hint_x=None, width=54)
        self.temp_max_label = Label(text="max", size_hint_y=None, height=20, font_size=12, halign="center", valign="middle")
        self.scale_widget = ColorScale(size_hint_y=1, width=16)
        self.temp_min_label = Label(text="min", size_hint_y=None, height=20, font_size=12, halign="center", valign="middle")
        scale_container.add_widget(self.temp_max_label)
        scale_widget_box = BoxLayout(orientation='horizontal')
        scale_widget_box.add_widget(Widget())
        scale_widget_box.add_widget(self.scale_widget)
        scale_widget_box.add_widget(Widget())
        scale_container.add_widget(scale_widget_box)
        scale_container.add_widget(self.temp_min_label)
        main_content.add_widget(scale_container)

        sidebar = BoxLayout(orientation='vertical', size_hint_x=None, width=120, spacing=10)
        sidebar.add_widget(Widget())
        self.palette_spinner = Spinner(text="...", values=PALETTE_NAMES, size_hint_y=None, height=44)
        self.palette_spinner.bind(text=self.change_palette)
        sidebar.add_widget(self.palette_spinner)
        action_btn_box = BoxLayout(orientation='horizontal', size_hint_y=None, height=44, spacing=10)
        screenshot_btn = Button(text="Foto", size_hint_x=0.5)
        screenshot_btn.bind(on_press=self.save_screenshot)
        self.record_btn = Button(text="● Rec", size_hint_x=0.5, background_color=(1,0,0,1))
        self.record_btn.bind(on_press=self.toggle_recording)
        action_btn_box.add_widget(screenshot_btn)
        action_btn_box.add_widget(self.record_btn)
        sidebar.add_widget(action_btn_box)
        self.gain_btn = Button(text="Gain: ...", size_hint_y=None, height=44)
        self.gain_btn.bind(on_press=self.toggle_gain)
        sidebar.add_widget(self.gain_btn)
        settings_btn = Button(text="Einst.", size_hint_y=None, height=44)
        settings_btn.bind(on_press=self.open_settings)
        sidebar.add_widget(settings_btn)
        sidebar.add_widget(Widget())
        main_content.add_widget(sidebar)
        root_layout.add_widget(main_content)
        exit_btn_layout = AnchorLayout(anchor_x='right', anchor_y='top')
        exit_btn = Button(text="X", size_hint=(None, None), size=(60, 40), background_color=(0.8, 0.2, 0.2, 1))
        exit_btn.bind(on_press=self.exit_app)
        exit_btn_layout.add_widget(exit_btn)
        root_layout.add_widget(exit_btn_layout)

        threading.Thread(target=self.initialize_camera_and_video, daemon=True).start()
        Clock.schedule_interval(self.update, 1.0 / 30.0)
        return root_layout

    def exit_app(self, *args):
        if self.camera_initialized:
            self.video.video_running = False
            time.sleep(0.1)
        App.get_running_app().stop()

    def get_gain_status(self):
        if not self.p2pro: return
        try:
            val = self.p2pro.get_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL)
            self.gain_state = int(val)
            self.gain_btn.text = "Gain: High" if self.gain_state == 1 else "Gain: Low"
        except Exception as e:
            print(f"Gain-Status konnte nicht gelesen werden: {e}")

    def toggle_gain(self, *args):
        if not self.p2pro: return
        new_state = 0 if self.gain_state == 1 else 1
        try:
            self.p2pro.set_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL, new_state)
            time.sleep(0.05)
            self.get_gain_status()
        except Exception as e:
            print(f"Gain konnte nicht gesetzt werden: {e}")

    def toggle_recording(self, *args):
        ts = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(self.videos_dir, exist_ok=True)
        if not self.is_recording:
            rec_dir = os.path.join(self.videos_dir, f"rec_{ts}")
            os.makedirs(rec_dir, exist_ok=True)
            self.recording_dir = rec_dir
            self.raw_frames = []
            self.is_recording = True
            self.record_btn.text = "■ Stop"
            self.record_btn.background_color = (0.4,0.4,0.4,1)
            self.rgb_writer = None
            print(f"[INFO] Aufnahme gestartet in {rec_dir}")
        else:
            self.is_recording = False
            self.record_btn.text = "● Rec"
            self.record_btn.background_color = (1,0,0,1)
            if hasattr(self, 'rgb_writer') and self.rgb_writer is not None:
                self.rgb_writer.release()
                self.rgb_writer = None
            if self.raw_frames:
                np.save(os.path.join(self.recording_dir, "rawframes.npy"), np.stack(self.raw_frames, axis=0))
            data = {"measure_points": [ [int(x), int(y)] for (x, y) in self.measure_points ]}
            with open(os.path.join(self.recording_dir, "measure_points.json"), "w") as f:
                json.dump(data, f, indent=2)
            avi_path = os.path.join(self.recording_dir, "video.avi")
            mkv_path = os.path.join(self.recording_dir, "video.mkv")
            if os.path.exists(avi_path):
                try:
                    subprocess.run(["ffmpeg", "-y", "-i", avi_path, "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", mkv_path], check=True, capture_output=True, text=True)
                    os.remove(avi_path)
                except Exception as e:
                    print(f"[WARN] ffmpeg-Umwandlung oder Löschen fehlgeschlagen: {e}")
            print(f"[INFO] Aufnahme gestoppt.")

    def set_camera_palette(self, palette_name):
        if not self.p2pro: return
        self.palette_name = palette_name
        palette = PALETTE_MAP.get(palette_name, PseudoColorTypes.PSEUDO_WHITE_HOT)
        try:
            self.p2pro.pseudo_color_set(0, palette)
        except Exception as e:
            print(f"Palette-Set-Fehler: {e}")

    def change_palette(self, spinner, text):
        self.set_camera_palette(text)

    def on_image_click(self, pos, button='left'):
        x, y = pos
        threshold = 8
        for idx, (mx, my) in enumerate(self.measure_points):
            if abs(mx - x) <= threshold and abs(my - y) <= threshold:
                del self.measure_points[idx]
                return
        self.measure_points.append((x, y))

    def draw_measure_marker(self, rgb_img, thermal_data, pos):
        x, y = pos
        if 0 <= x < rgb_img.shape[1] and 0 <= y < rgb_img.shape[0]:
            temp_val = thermal_data[y, x]
            temp_c = round((temp_val / 64.0) - 273.16, 1)
            draw_cross_with_outline(rgb_img, (x, y))
            draw_text_with_outline(rgb_img, f"{temp_c:.1f}", (x + 10, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255,255,255))

    def get_colormap_bar(self, temp_min, temp_max):
        cv_colormap = OPENCV_COLORMAP_MAP.get(self.palette_name, None)
        temps_c = np.linspace(temp_max, temp_min, 256)
        rawvals = np.clip((temps_c + 273.16) * 64.0, 0, 65535).astype(np.uint16)
        ptp_val = np.ptp(rawvals) + 1e-8
        norm = ((rawvals - rawvals.min()) / ptp_val * 255).astype(np.uint8)
        bar = norm.reshape((256, 1))
        if cv_colormap is not None:
            bar_rgb = cv2.applyColorMap(bar, cv_colormap)
            bar_rgb = cv2.cvtColor(bar_rgb, cv2.COLOR_BGR2RGB)
        else:
            bar_rgb = np.repeat(bar, 3, axis=1).reshape((256, 1, 3))
        return bar_rgb

    def update(self, dt):
        if not self.camera_initialized:
            return

        if not self.video.frame_queue[1].empty():
            frame_data = self.video.frame_queue[1].get()
            if not isinstance(frame_data, dict): return
            thermal = frame_data.get("thermal_data")
            rgb_picture = frame_data.get("rgb_data")
            if thermal is not None and rgb_picture is not None:
                temp_min_val = round((np.min(thermal) / 64.0) - 273.16, 1)
                temp_max_val = round((np.max(thermal) / 64.0) - 273.16, 1)
                self.temp_min_label.text = f"{temp_min_val:.1f}"
                self.temp_max_label.text = f"{temp_max_val:.1f}"
                try:
                    bar_rgb = self.get_colormap_bar(temp_min_val, temp_max_val)
                    self.scale_widget.update_texture(bar_rgb)
                except Exception as e:
                    print("Fehler Farbbalken:", e)
                rgb_with_markers = rgb_picture.copy()
                for pt in self.measure_points:
                    self.draw_measure_marker(rgb_with_markers, thermal, pt)
                h, w, _ = rgb_with_markers.shape
                texture = Texture.create(size=(w, h), colorfmt='rgb')
                texture.blit_buffer(rgb_with_markers.tobytes(), colorfmt='rgb')
                texture.flip_vertical()
                self.image.texture = texture
                self.last_rgb = rgb_picture.copy()
                self.last_thermal = thermal.copy()
                if self.is_recording:
                    if not hasattr(self, 'rgb_writer') or self.rgb_writer is None:
                        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                        self.rgb_writer = cv2.VideoWriter(os.path.join(self.recording_dir, "video.avi"), fourcc, 30.0, (w, h))
                    self.rgb_writer.write(cv2.cvtColor(rgb_picture, cv2.COLOR_RGB2BGR))
                    self.raw_frames.append(np.array(thermal, dtype=thermal.dtype))

    def save_screenshot(self, *args):
        if self.last_rgb is None: return
        ts = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        base = os.path.join(self.screenshots_dir, f"screenshot_{ts}")
        cv2.imwrite(f"{base}.png", cv2.cvtColor(self.last_rgb, cv2.COLOR_RGB2BGR))
        np.save(f"{base}_raw.npy", self.last_thermal)
        data = {"measure_points": [ [int(x), int(y)] for (x, y) in self.measure_points ]}
        with open(f"{base}_points.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"Screenshot gespeichert: {base}.png")

if __name__ == "__main__":
    ThermalApp().run()