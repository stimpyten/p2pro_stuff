from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

import cv2
import numpy as np


@dataclass
class ScreenshotBundle:
    image_file: str
    raw_file: str
    points_file: str | None
    rgb_image: np.ndarray
    thermal: np.ndarray
    measure_points: List[Tuple[int, int]]


@dataclass
class VideoBundle:
    video_file: str
    raw_file: str
    points_file: str | None
    rgb_frames: List[np.ndarray]
    thermal_frames: np.ndarray
    measure_points: List[Tuple[int, int]]


class MediaService:
    def __init__(self, screenshots_dir: str = "screenshots", videos_dir: str = "videos"):
        self.screenshots_dir = screenshots_dir
        self.videos_dir = videos_dir

    def list_screenshots(self) -> List[str]:
        if not os.path.isdir(self.screenshots_dir):
            return []
        files = [
            os.path.join(self.screenshots_dir, name)
            for name in os.listdir(self.screenshots_dir)
            if name.lower().endswith(".png")
        ]
        files.sort(reverse=True)
        return files

    def list_videos(self) -> List[str]:
        if not os.path.isdir(self.videos_dir):
            return []

        video_files: List[str] = []
        for root, _, files in os.walk(self.videos_dir):
            for name in files:
                if name.lower().endswith((".mp4", ".avi", ".mkv")):
                    video_files.append(os.path.join(root, name))
        video_files.sort(reverse=True)
        return video_files

    def load_screenshot(self, image_file: str) -> ScreenshotBundle:
        base = os.path.splitext(image_file)[0]
        raw_file = base + "_raw.npy"
        points_file = base + "_points.json"

        if not os.path.exists(raw_file):
            raise FileNotFoundError(f"Rohdaten nicht gefunden: {raw_file}")

        img_bgr = cv2.imread(image_file)
        if img_bgr is None:
            raise ValueError(f"Bild konnte nicht geladen werden: {image_file}")

        rgb_image = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        thermal = np.load(raw_file)
        measure_points = self._load_measure_points(points_file)

        return ScreenshotBundle(
            image_file=image_file,
            raw_file=raw_file,
            points_file=points_file if os.path.exists(points_file) else None,
            rgb_image=rgb_image,
            thermal=thermal,
            measure_points=measure_points,
        )

    def save_screenshot_measure_points(self, image_file: str, measure_points: List[Tuple[int, int]]) -> str:
        base = os.path.splitext(image_file)[0]
        points_file = base + "_points.json"
        self._save_measure_points(points_file, measure_points)
        return points_file

    def load_video(self, video_file: str) -> VideoBundle:
        video_dir = os.path.dirname(video_file)
        raw_file = os.path.join(video_dir, "rawframes.npy")
        points_file = os.path.join(video_dir, "measure_points.json")

        if not os.path.exists(raw_file):
            raise FileNotFoundError(f"Rohdaten nicht gefunden: {raw_file}")

        cap = cv2.VideoCapture(video_file)
        rgb_frames: List[np.ndarray] = []
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            rgb_frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        cap.release()

        thermal_frames = np.load(raw_file, mmap_mode='r')
        if len(thermal_frames.shape) == 2:
            thermal_frames = thermal_frames[None, ...]

        measure_points = self._load_measure_points(points_file)

        return VideoBundle(
            video_file=video_file,
            raw_file=raw_file,
            points_file=points_file if os.path.exists(points_file) else None,
            rgb_frames=rgb_frames,
            thermal_frames=thermal_frames,
            measure_points=measure_points,
        )

    def save_video_measure_points(self, video_file: str, measure_points: List[Tuple[int, int]]) -> str:
        video_dir = os.path.dirname(video_file)
        points_file = os.path.join(video_dir, "measure_points.json")
        self._save_measure_points(points_file, measure_points)
        return points_file

    def save_video_frame_as_screenshot(
        self,
        video_file: str,
        frame_index: int,
        rgb_frame: np.ndarray,
        thermal_frame: np.ndarray,
        measure_points: List[Tuple[int, int]],
    ) -> Dict[str, str]:
        if not os.path.exists(self.screenshots_dir):
            os.makedirs(self.screenshots_dir, exist_ok=True)

        ts = f"{os.path.splitext(os.path.basename(video_file))[0]}_{frame_index:06d}"
        base = os.path.join(self.screenshots_dir, f"video_frame_{ts}")
        img_file = base + ".png"
        raw_file = base + "_raw.npy"
        points_file = base + "_points.json"

        cv2.imwrite(img_file, cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR))
        np.save(raw_file, thermal_frame)
        self._save_measure_points(points_file, measure_points)

        return {
            "image_file": img_file,
            "raw_file": raw_file,
            "points_file": points_file,
        }

    def _load_measure_points(self, points_file: str) -> List[Tuple[int, int]]:
        if not os.path.exists(points_file):
            return []
        with open(points_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return [tuple(map(int, pt)) for pt in data.get("measure_points", [])]

    def _save_measure_points(self, points_file: str, measure_points: List[Tuple[int, int]]) -> None:
        data = {"measure_points": [[int(x), int(y)] for x, y in measure_points]}
        with open(points_file, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
