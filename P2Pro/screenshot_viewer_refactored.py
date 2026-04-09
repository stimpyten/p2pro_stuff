import os
from typing import Tuple

import cv2
import numpy as np
from kivy.graphics.texture import Texture
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from P2Pro.gui_utils import ClickableImage, draw_cross_with_outline, draw_text_with_outline, toggle_point
from P2Pro.services.media_service import MediaService
from P2Pro.thermal_utils import thermal_to_celsius


class ScreenshotViewerScreen(Screen):
    def __init__(self, screenshots_dir: str = "./screenshots", videos_dir: str = "./videos", **kwargs):
        super().__init__(**kwargs)
        self.media_service = MediaService(screenshots_dir=screenshots_dir, videos_dir=videos_dir)
        self.last_imgfile = None
        self.rgb_img = None
        self.thermal = None
        self.measure_points = []

        layout = BoxLayout(orientation="horizontal", padding=10, spacing=10)
        leftbar = BoxLayout(orientation="vertical", size_hint=(None, 1), width=300, spacing=8)

        backbtn = Button(text="← Zurück", size_hint=(1, None), height=40)
        backbtn.bind(on_press=lambda *a: setattr(self.manager, "current", "menu"))
        leftbar.add_widget(backbtn)

        self.filechooser = FileChooserIconView(filters=["*.png"], path=screenshots_dir)
        self.filechooser.bind(on_selection=self.on_file_selected)
        leftbar.add_widget(self.filechooser)

        btn_load = Button(text="Screenshot öffnen", size_hint=(1, None), height=40)
        btn_load.bind(on_press=self.on_file_open_button)
        leftbar.add_widget(btn_load)

        btn_refresh = Button(text="Liste aktualisieren", size_hint=(1, None), height=40)
        btn_refresh.bind(on_press=self.refresh_filechooser)
        leftbar.add_widget(btn_refresh)

        btn_save = Button(text="Messpunkte speichern", size_hint=(1, None), height=40)
        btn_save.bind(on_press=self.save_measure_points)
        leftbar.add_widget(btn_save)

        self.info_label = Label(text="Bitte Screenshot auswählen", size_hint=(1, None), height=90)
        leftbar.add_widget(self.info_label)

        layout.add_widget(leftbar)

        self.image = ClickableImage(allow_stretch=True)
        self.image.click_callback = self.on_image_click
        layout.add_widget(self.image)
        self.add_widget(layout)

    def on_pre_enter(self, *args):
        self.refresh_filechooser()

    def refresh_filechooser(self, *args):
        os.makedirs(self.media_service.screenshots_dir, exist_ok=True)
        self.filechooser.path = self.media_service.screenshots_dir
        self.filechooser._update_files()

    def on_file_selected(self, filechooser, selection):
        if selection:
            self.load_image_file(selection[0])

    def on_file_open_button(self, *args):
        sel = self.filechooser.selection
        if sel:
            self.load_image_file(sel[0])

    def load_image_file(self, img_file: str):
        try:
            bundle = self.media_service.load_screenshot(img_file)
        except Exception as exc:
            self.last_imgfile = None
            self.rgb_img = None
            self.thermal = None
            self.measure_points = []
            self.image.texture = None
            self.info_label.text = f"Fehler beim Laden:\n{exc}"
            return

        self.last_imgfile = bundle.image_file
        self.rgb_img = bundle.rgb_image
        self.thermal = bundle.thermal
        self.measure_points = list(bundle.measure_points)
        self.update_image()
        self.info_label.text = (
            f"{os.path.basename(bundle.image_file)}\n"
            f"Rohdaten geladen.\n"
            f"Messpunkte: {len(self.measure_points)}"
        )

    def on_image_click(self, pos: Tuple[int, int], button="left"):
        if self.rgb_img is None or self.thermal is None:
            return
        self.measure_points = toggle_point(self.measure_points, *pos)
        self.update_image()

    def update_image(self):
        if self.rgb_img is None:
            self.image.texture = None
            return

        disp_img = self.rgb_img.copy()
        for x, y in self.measure_points:
            if 0 <= x < disp_img.shape[1] and 0 <= y < disp_img.shape[0]:
                temp_c = thermal_to_celsius(self.thermal[y, x])
                draw_cross_with_outline(disp_img, (x, y))
                draw_text_with_outline(
                    disp_img,
                    f"{temp_c:.1f}",
                    (x + 10, y + 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (255, 255, 255),
                )

        h, w, _ = disp_img.shape
        texture = Texture.create(size=(w, h), colorfmt="rgb")
        texture.blit_buffer(disp_img.tobytes(), colorfmt="rgb")
        texture.flip_vertical()
        self.image.texture = texture

    def save_measure_points(self, *args):
        if not self.last_imgfile:
            self.info_label.text = "Kein Screenshot ausgewählt."
            return

        try:
            points_file = self.media_service.save_screenshot_measure_points(self.last_imgfile, self.measure_points)
            self.info_label.text = f"Messpunkte gespeichert in:\n{os.path.basename(points_file)}"
        except Exception as exc:
            self.info_label.text = f"Fehler beim Speichern:\n{exc}"
