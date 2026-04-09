from typing import List, Tuple

import cv2
import numpy as np
from kivy.uix.image import Image


def toggle_point(
    points: List[Tuple[int, int]], x: int, y: int, threshold: int = 8
) -> List[Tuple[int, int]]:
    """Remove the nearest point within threshold, or append a new one. Returns the updated list."""
    for idx, (px, py) in enumerate(points):
        if abs(px - x) <= threshold and abs(py - y) <= threshold:
            return points[:idx] + points[idx + 1:]
    return points + [(int(x), int(y))]


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
        self.move_callback = None

    def _touch_to_image_coords(self, touch):
        """Map a touch position to image pixel coordinates. Returns (x, y) or None if outside the image area."""
        if not self.collide_point(*touch.pos) or self.texture is None:
            return None

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
            return None

        x_rel = (touch.x - offset_x) / disp_w
        y_rel = (touch.y - offset_y) / disp_h
        x_img = int(np.clip(x_rel * w_tex, 0, w_tex - 1))
        y_img = int(np.clip((1 - y_rel) * h_tex, 0, h_tex - 1))
        return x_img, y_img

    def on_touch_down(self, touch):
        coords = self._touch_to_image_coords(touch)
        if coords and self.click_callback:
            self.click_callback(coords, button=getattr(touch, "button", "left"))
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        coords = self._touch_to_image_coords(touch)
        if coords and self.move_callback:
            self.move_callback(coords)
        return super().on_touch_move(touch)
