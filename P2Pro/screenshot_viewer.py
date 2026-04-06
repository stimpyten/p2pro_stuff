# screenshot_viewer.py

import os
import numpy as np
import cv2
import json
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.widget import Widget
from kivy.graphics.texture import Texture

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

class ScreenshotViewerScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_imgfile = None
        self.last_rawfile = None
        self.last_pointsfile = None
        self.rgb_img = None
        self.thermal = None
        self.measure_points = []

        layout = BoxLayout(orientation='horizontal', padding=10, spacing=10)
        leftbar = BoxLayout(orientation='vertical', size_hint=(None, 1), width=300, spacing=8)
        # Zurück-Button oben links
        backbtn = Button(text="← Zurück", size_hint=(1, None), height=40)
        backbtn.bind(on_press=lambda *a: setattr(self.manager, 'current', 'menu'))
        leftbar.add_widget(backbtn)

        self.filechooser = FileChooserIconView(filters=['*.png'], path='./screenshots')
        self.filechooser.bind(on_selection=self.on_file_selected)
        leftbar.add_widget(self.filechooser)
        btn_load = Button(text="Screenshot öffnen", size_hint=(1, None), height=40)
        btn_load.bind(on_press=self.on_file_open_button)
        leftbar.add_widget(btn_load)
        btn_save = Button(text="Messpunkte speichern", size_hint=(1, None), height=40)
        btn_save.bind(on_press=self.save_measure_points)
        leftbar.add_widget(btn_save)
        self.info_label = Label(text="Bitte Screenshot auswählen", size_hint=(1, None), height=60)
        leftbar.add_widget(self.info_label)
        layout.add_widget(leftbar)
        self.image = ClickableImage(allow_stretch=True)
        self.image.click_callback = self.on_image_click
        layout.add_widget(self.image)
        self.add_widget(layout)

    def on_file_selected(self, filechooser, selection):
        if selection:
            self.load_image_file(selection[0])

    def on_file_open_button(self, *args):
        sel = self.filechooser.selection
        if sel:
            self.load_image_file(sel[0])

    def load_image_file(self, img_file):
        self.last_imgfile = img_file
        base = os.path.splitext(img_file)[0]
        raw_file = base + "_raw.npy"
        points_file = base + "_points.json"
        if not os.path.exists(raw_file):
            self.info_label.text = "Fehler: Rohdaten (.npy) nicht gefunden!"
            self.rgb_img = None
            self.thermal = None
            self.image.texture = None
            return
        self.last_rawfile = raw_file
        self.last_pointsfile = points_file if os.path.exists(points_file) else None
        img_bgr = cv2.imread(img_file)
        if img_bgr is None:
            self.info_label.text = "Fehler beim Laden des Bilds!"
            return
        self.rgb_img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        self.thermal = np.load(raw_file)
        self.measure_points = []
        if self.last_pointsfile:
            try:
                with open(self.last_pointsfile, "r") as f:
                    data = json.load(f)
                    self.measure_points = [tuple(pt) for pt in data.get("measure_points", [])]
            except Exception as e:
                print(f"WARN: Punkte nicht geladen: {e}")
        self.update_image()
        self.info_label.text = f"{os.path.basename(img_file)}\nRohdaten geladen.\nMesspunkte: {len(self.measure_points)}"

    def on_image_click(self, pos, button='left'):
        if self.rgb_img is None or self.thermal is None:
            return
        x, y = pos
        threshold = 8
        for idx, (mx, my) in enumerate(self.measure_points):
            if abs(mx - x) <= threshold and abs(my - y) <= threshold:
                del self.measure_points[idx]
                self.update_image()
                return
        self.measure_points.append((x, y))
        self.update_image()

    def update_image(self):
        if self.rgb_img is None:
            self.image.texture = None
            return
        disp_img = self.rgb_img.copy()
        for pt in self.measure_points:
            x, y = pt
            if 0 <= x < disp_img.shape[1] and 0 <= y < disp_img.shape[0]:
                temp_val = self.thermal[y, x]
                temp_c = round((temp_val / 64.0) - 273.16, 1)
                draw_cross_with_outline(
                    disp_img, (x, y),
                    color_fg=(255,255,255), color_outline=(0,0,0),
                    size=6, thickness_fg=1, thickness_outline=3
                )
                draw_text_with_outline(
                    disp_img,
                    f"{temp_c:.1f}",
                    (x + 10, y + 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (255,255,255),
                    color_outline=(0,0,0),
                    thickness_fg=1,
                    thickness_outline=3
                )
        h, w, _ = disp_img.shape
        texture = Texture.create(size=(w, h), colorfmt='rgb')
        texture.blit_buffer(disp_img.tobytes(), colorfmt='rgb')
        texture.flip_vertical()
        self.image.texture = texture

    def save_measure_points(self, *args):
        if not self.last_imgfile:
            self.info_label.text = "Kein Screenshot ausgewählt."
            return
        base = os.path.splitext(self.last_imgfile)[0]
        points_file = base + "_points.json"
        data = {"measure_points": [ [int(x), int(y)] for (x, y) in self.measure_points ]}
        try:
            with open(points_file, "w") as f:
                json.dump(data, f, indent=2)
            self.info_label.text = f"Messpunkte gespeichert in:\n{os.path.basename(points_file)}"
        except Exception as e:
            self.info_label.text = f"Fehler beim Speichern:\n{e}"

