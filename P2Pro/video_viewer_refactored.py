import os
from typing import Tuple

import cv2
import numpy as np
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from P2Pro.gui_utils import ClickableImage, draw_cross_with_outline, draw_text_with_outline
from P2Pro.services.media_service import MediaService


class VideoViewerScreen(Screen):
    def __init__(self, screenshots_dir: str = "./screenshots", videos_dir: str = "./videos", **kwargs):
        super().__init__(**kwargs)
        self.media_service = MediaService(screenshots_dir=screenshots_dir, videos_dir=videos_dir)
        self.last_vidfile = None
        self.rgb_frames = []
        self.thermal_frames = np.array([])
        self.measure_points = []
        self.current_frame_idx = 0
        self.is_playing = False
        self._clock_ev = None

        layout = BoxLayout(orientation="horizontal", padding=10, spacing=10)
        leftbar = BoxLayout(orientation="vertical", size_hint=(None, 1), width=300, spacing=8)

        backbtn = Button(text="< Menu", size_hint=(1, None), height=40)
        backbtn.bind(on_press=lambda *a: setattr(self.manager, "current", "menu"))
        leftbar.add_widget(backbtn)

        self.filechooser = FileChooserIconView(filters=["*.mp4", "*.avi", "*.mkv"], path=videos_dir)
        self.filechooser.bind(on_selection=self.on_file_selected)
        leftbar.add_widget(self.filechooser)

        btn_load = Button(text="Video öffnen", size_hint=(1, None), height=40)
        btn_load.bind(on_press=self.on_file_open_button)
        leftbar.add_widget(btn_load)

        btn_refresh = Button(text="Liste aktualisieren", size_hint=(1, None), height=40)
        btn_refresh.bind(on_press=self.refresh_filechooser)
        leftbar.add_widget(btn_refresh)

        btn_box = BoxLayout(orientation="horizontal", size_hint=(1, None), height=40)
        self.btn_prev = Button(text="<", size_hint=(0.3, 1))
        self.btn_playpause = Button(text="|>", size_hint=(0.4, 1))
        self.btn_next = Button(text=">", size_hint=(0.3, 1))
        self.btn_prev.bind(on_press=self.prev_frame)
        self.btn_playpause.bind(on_press=self.toggle_playpause)
        self.btn_next.bind(on_press=self.next_frame)
        btn_box.add_widget(self.btn_prev)
        btn_box.add_widget(self.btn_playpause)
        btn_box.add_widget(self.btn_next)
        leftbar.add_widget(btn_box)

        btn_screenshot = Button(text="Screenshot speichern", size_hint=(1, None), height=40)
        btn_screenshot.bind(on_press=self.save_screenshot_from_video)
        leftbar.add_widget(btn_screenshot)

        btn_save = Button(text="Messpunkte speichern", size_hint=(1, None), height=40)
        btn_save.bind(on_press=self.save_measure_points)
        leftbar.add_widget(btn_save)

        self.info_label = Label(text="Bitte Video auswählen", size_hint=(1, None), height=90)
        leftbar.add_widget(self.info_label)

        layout.add_widget(leftbar)

        self.image = ClickableImage(allow_stretch=True)
        self.image.click_callback = self.on_image_click
        layout.add_widget(self.image)

        self.add_widget(layout)

    def on_pre_enter(self, *args):
        self.refresh_filechooser()

    def on_leave(self, *args):
        self.stop_playback()

    def refresh_filechooser(self, *args):
        os.makedirs(self.media_service.videos_dir, exist_ok=True)
        self.filechooser.path = self.media_service.videos_dir
        self.filechooser._update_files()

    def on_file_selected(self, filechooser, selection):
        if selection:
            self.load_video_file(selection[0])

    def on_file_open_button(self, *args):
        sel = self.filechooser.selection
        if sel:
            self.load_video_file(sel[0])

    def load_video_file(self, vid_file: str):
        self.stop_playback()
        try:
            bundle = self.media_service.load_video(vid_file)
        except Exception as exc:
            self.last_vidfile = None
            self.rgb_frames = []
            self.thermal_frames = np.array([])
            self.measure_points = []
            self.current_frame_idx = 0
            self.image.texture = None
            self.info_label.text = f"Fehler beim Laden:\n{exc}"
            return

        self.last_vidfile = bundle.video_file
        self.rgb_frames = bundle.rgb_frames
        self.thermal_frames = bundle.thermal_frames
        self.measure_points = list(bundle.measure_points)
        self.current_frame_idx = 0
        self.btn_playpause.text = "|>"
        self.update_image()
        self.info_label.text = (
            f"{os.path.basename(vid_file)}\n"
            f"Frames: {len(self.rgb_frames)} | Messpunkte: {len(self.measure_points)}"
        )

    def on_image_click(self, pos: Tuple[int, int], button="left"):
        if not self.rgb_frames or self.thermal_frames.size == 0:
            return

        x, y = pos
        threshold = 8
        for idx, (mx, my) in enumerate(self.measure_points):
            if abs(mx - x) <= threshold and abs(my - y) <= threshold:
                del self.measure_points[idx]
                self.update_image()
                return

        self.measure_points.append((int(x), int(y)))
        self.update_image()

    def update_image(self):
        if not self.rgb_frames:
            self.image.texture = None
            return

        idx = self.current_frame_idx
        disp_img = self.rgb_frames[idx].copy()
        thermal = self.thermal_frames[idx]

        for x, y in self.measure_points:
            if 0 <= x < disp_img.shape[1] and 0 <= y < disp_img.shape[0]:
                temp_val = thermal[y, x]
                temp_c = round((temp_val / 64.0) - 273.16, 1)
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
        self.info_label.text = f"Frame {self.current_frame_idx + 1}/{len(self.rgb_frames)} | Messpunkte: {len(self.measure_points)}"

    def prev_frame(self, *args):
        if not self.rgb_frames:
            return
        self.current_frame_idx = max(0, self.current_frame_idx - 1)
        self.update_image()

    def next_frame(self, *args):
        if not self.rgb_frames:
            return
        self.current_frame_idx = min(len(self.rgb_frames) - 1, self.current_frame_idx + 1)
        self.update_image()

    def toggle_playpause(self, *args):
        if self.is_playing:
            self.stop_playback()
        else:
            self.start_playback()

    def start_playback(self, *args):
        if self._clock_ev is not None or not self.rgb_frames:
            return
        self.is_playing = True
        self.btn_playpause.text = "||"
        self._clock_ev = Clock.schedule_interval(self._playback_step, 1.0 / 30.0)

    def _playback_step(self, dt):
        if not self.rgb_frames:
            self.stop_playback()
            return False
        self.current_frame_idx += 1
        if self.current_frame_idx >= len(self.rgb_frames):
            self.current_frame_idx = 0
        self.update_image()
        return self.is_playing

    def stop_playback(self, *args):
        self.is_playing = False
        self.btn_playpause.text = "|>"
        if self._clock_ev is not None:
            self._clock_ev.cancel()
            self._clock_ev = None

    def save_screenshot_from_video(self, *args):
        if not self.rgb_frames or self.thermal_frames.size == 0 or not self.last_vidfile:
            self.info_label.text = "Kein Frame geladen!"
            return

        idx = self.current_frame_idx
        try:
            result = self.media_service.save_video_frame_as_screenshot(
                video_file=self.last_vidfile,
                frame_index=idx,
                rgb_frame=self.rgb_frames[idx],
                thermal_frame=self.thermal_frames[idx],
                measure_points=self.measure_points,
            )
            self.info_label.text = f"Screenshot gespeichert:\n{os.path.basename(result['image_file'])}"
        except Exception as exc:
            self.info_label.text = f"Fehler beim Speichern:\n{exc}"

    def save_measure_points(self, *args):
        if not self.last_vidfile:
            self.info_label.text = "Kein Video ausgewählt."
            return

        try:
            points_file = self.media_service.save_video_measure_points(self.last_vidfile, self.measure_points)
            self.info_label.text = f"Messpunkte gespeichert in:\n{os.path.basename(points_file)}"
        except Exception as exc:
            self.info_label.text = f"Fehler beim Speichern:\n{exc}"
