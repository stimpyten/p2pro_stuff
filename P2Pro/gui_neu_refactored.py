import threading
import time
from typing import Tuple

import cv2
import numpy as np
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Rectangle
from kivy.graphics.texture import Texture
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.widget import Widget

from P2Pro.services.thermal_service import PALETTE_NAMES, ThermalService


def draw_text_with_outline(img, text, org, font, font_scale, color_fg, color_outline=(0, 0, 0), thickness_fg=1, thickness_outline=3):
    cv2.putText(img, text, org, font, font_scale, color_outline, thickness_outline, cv2.LINE_AA)
    cv2.putText(img, text, org, font, font_scale, color_fg, thickness_fg, cv2.LINE_AA)


def draw_cross_with_outline(img, pos, color_fg=(255, 255, 255), color_outline=(0, 0, 0), size=6, thickness_fg=1, thickness_outline=3):
    x, y = pos
    cv2.line(img, (x - size, y), (x + size, y), color_outline, thickness_outline, cv2.LINE_AA)
    cv2.line(img, (x, y - size), (x, y + size), color_outline, thickness_outline, cv2.LINE_AA)
    cv2.line(img, (x - size, y), (x + size, y), color_fg, thickness_fg, cv2.LINE_AA)
    cv2.line(img, (x, y - size), (x, y + size), color_fg, thickness_fg, cv2.LINE_AA)


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
        x_img = int(np.clip(x_rel * w_tex, 0, w_tex - 1))
        y_img = int(np.clip((1 - y_rel) * h_tex, 0, h_tex - 1))

        if self.click_callback:
            self.click_callback((x_img, y_img), button=getattr(touch, "button", "left"))
        return super().on_touch_down(touch)


class ColorScale(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.texture = None
        self.rect = None
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_texture(self, rgb_bar_img):
        bar_width = int(self.width) if self.width else 16
        bar = np.repeat(rgb_bar_img, bar_width, axis=1)
        self.texture = Texture.create(size=(bar_width, 256), colorfmt="rgb")
        self.texture.blit_buffer(bar.tobytes(), colorfmt="rgb")
        self.texture.flip_vertical()
        self.update_canvas()

    def update_canvas(self, *args):
        self.canvas.clear()
        if self.texture:
            with self.canvas:
                self.rect = Rectangle(texture=self.texture, pos=self.pos, size=self.size)


class ThermalApp(App):
    def build_config(self, config):
        config.setdefaults("Pfade", {"screenshot_dir": "screenshots", "video_dir": "videos"})
        config.setdefaults("Standardwerte", {"palette": "White Hot", "gain": "Low"})
        config.setdefaults("Anzeige", {"fullscreen": "1"})

    def build_settings(self, settings):
        settings.add_json_panel("App Einstellungen", self.config, "settings.json")
        settings.interface.bind(on_close=self.on_settings_close)

    def on_settings_close(self, *args):
        print("Einstellungsfenster geschlossen.")

    def on_config_change(self, config, section, key, value):
        print(f"Konfiguration geändert: Sektion={section}, Key={key}, Wert={value}")
        if not self.camera_initialized:
            print("Änderung wird ignoriert, da die Kamera noch nicht bereit ist.")
            return

        if key == "palette":
            self.palette_spinner.text = value
            self.service.set_palette(value)
        elif key == "gain":
            self.service.set_gain_mode(value)
            self.refresh_gain_button()
        elif section == "Anzeige" and key == "fullscreen":
            print("Vollbildmodus-Einstellung geändert. Bitte App neu starten.")

    def build(self):
        try:
            if self.config.getboolean("Anzeige", "fullscreen"):
                Window.fullscreen = "auto"
            else:
                Window.fullscreen = False
        except Exception as exc:
            print(f"Fehler beim Setzen des Vollbildmodus: {exc}. Verwende Standard (auto).")
            Window.fullscreen = "auto"

        self.use_kivy_settings = True
        self.camera_initialized = False
        self.service = ThermalService(
            screenshot_dir=self.config.get("Pfade", "screenshot_dir"),
            video_dir=self.config.get("Pfade", "video_dir"),
        )

        root_layout = AnchorLayout()
        main_content = BoxLayout(orientation="horizontal", padding=10, spacing=10)

        self.image = ClickableImage(allow_stretch=True)
        self.image.click_callback = self.on_image_click
        main_content.add_widget(self.image)

        scale_container = BoxLayout(orientation="vertical", size_hint_x=None, width=54)
        self.temp_max_label = Label(text="max", size_hint_y=None, height=20, font_size=12, halign="center", valign="middle")
        self.scale_widget = ColorScale(size_hint_y=1, width=16)
        self.temp_min_label = Label(text="min", size_hint_y=None, height=20, font_size=12, halign="center", valign="middle")
        scale_container.add_widget(self.temp_max_label)
        scale_widget_box = BoxLayout(orientation="horizontal")
        scale_widget_box.add_widget(Widget())
        scale_widget_box.add_widget(self.scale_widget)
        scale_widget_box.add_widget(Widget())
        scale_container.add_widget(scale_widget_box)
        scale_container.add_widget(self.temp_min_label)
        main_content.add_widget(scale_container)

        sidebar = BoxLayout(orientation="vertical", size_hint_x=None, width=120, spacing=10)
        sidebar.add_widget(Widget())
        self.palette_spinner = Spinner(text="...", values=PALETTE_NAMES, size_hint_y=None, height=44)
        self.palette_spinner.bind(text=self.change_palette)
        sidebar.add_widget(self.palette_spinner)

        action_btn_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=44, spacing=10)
        screenshot_btn = Button(text="Foto", size_hint_x=0.5)
        screenshot_btn.bind(on_press=self.save_screenshot)
        self.record_btn = Button(text="● Rec", size_hint_x=0.5, background_color=(1, 0, 0, 1))
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

        exit_btn_layout = AnchorLayout(anchor_x="right", anchor_y="top")
        exit_btn = Button(text="X", size_hint=(None, None), size=(60, 40), background_color=(0.8, 0.2, 0.2, 1))
        exit_btn.bind(on_press=self.exit_app)
        exit_btn_layout.add_widget(exit_btn)
        root_layout.add_widget(exit_btn_layout)

        threading.Thread(target=self.initialize_camera_and_video, daemon=True).start()
        Clock.schedule_interval(self.update, 1.0 / 30.0)
        return root_layout

    def initialize_camera_and_video(self):
        try:
            print("Initialisiere Kamera-Hardware...")
            palette_name = self.config.get("Standardwerte", "palette")
            gain_mode = self.config.get("Standardwerte", "gain")

            self.service.initialize(palette_name=palette_name, gain_mode=gain_mode)
            self.service.start_video(-1)

            self.palette_spinner.text = palette_name
            self.refresh_gain_button()
            self.camera_initialized = True
            print("Initialisierung abgeschlossen. UI-Updates werden jetzt aktiviert.")
        except Exception as exc:
            print(f"FATAL: Fehler bei der Kamera-Initialisierung oder Video-Erfassung: {exc}")

    def exit_app(self, *args):
        self.service.stop()
        time.sleep(0.1)
        App.get_running_app().stop()

    def refresh_gain_button(self):
        gain_state = self.service.get_gain_status()
        self.gain_btn.text = "Gain: High" if gain_state == 1 else "Gain: Low"

    def toggle_gain(self, *args):
        try:
            self.service.toggle_gain()
            self.refresh_gain_button()
        except Exception as exc:
            print(f"Gain konnte nicht gesetzt werden: {exc}")

    def toggle_recording(self, *args):
        try:
            result = self.service.toggle_recording()
            if result["is_recording"]:
                self.record_btn.text = "■ Stop"
                self.record_btn.background_color = (0.4, 0.4, 0.4, 1)
                print(f"[INFO] Aufnahme gestartet in {result['recording_dir']}")
            else:
                self.record_btn.text = "● Rec"
                self.record_btn.background_color = (1, 0, 0, 1)
                print("[INFO] Aufnahme gestoppt.")
        except Exception as exc:
            print(f"[WARN] Aufnahme konnte nicht umgeschaltet werden: {exc}")

    def change_palette(self, spinner, text):
        try:
            self.service.set_palette(text)
        except Exception as exc:
            print(f"Palette-Set-Fehler: {exc}")

    def on_image_click(self, pos: Tuple[int, int], button="left"):
        x, y = pos
        self.service.toggle_measure_point(x, y)

    def draw_measure_marker(self, rgb_img, thermal_data, pos):
        x, y = pos
        if 0 <= x < rgb_img.shape[1] and 0 <= y < rgb_img.shape[0]:
            temp_val = thermal_data[y, x]
            temp_c = round((temp_val / 64.0) - 273.16, 1)
            draw_cross_with_outline(rgb_img, (x, y))
            draw_text_with_outline(rgb_img, f"{temp_c:.1f}", (x + 10, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255))

    def save_screenshot(self, *args):
        path = self.service.save_screenshot()
        if path:
            print(f"Screenshot gespeichert: {path}")

    def update(self, dt):
        if not self.camera_initialized:
            return

        frame = self.service.get_latest_frame(queue_index=1)
        if frame is None:
            return

        self.temp_min_label.text = f"{frame.temp_min_c:.1f}"
        self.temp_max_label.text = f"{frame.temp_max_c:.1f}"

        try:
            bar_rgb = self.service.build_colormap_bar(frame.temp_min_c, frame.temp_max_c)
            self.scale_widget.update_texture(bar_rgb)
        except Exception as exc:
            print("Fehler Farbbalken:", exc)

        rgb_with_markers = frame.rgb_data.copy()
        for pt in self.service.get_measure_points():
            self.draw_measure_marker(rgb_with_markers, frame.thermal_data, pt)

        h, w, _ = rgb_with_markers.shape
        texture = Texture.create(size=(w, h), colorfmt="rgb")
        texture.blit_buffer(rgb_with_markers.tobytes(), colorfmt="rgb")
        texture.flip_vertical()
        self.image.texture = texture


if __name__ == "__main__":
    ThermalApp().run()
