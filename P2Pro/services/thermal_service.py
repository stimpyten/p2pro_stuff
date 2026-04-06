from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

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
    "Rainbow 3": cv2.COLORMAP_PARULA if hasattr(cv2, "COLORMAP_PARULA") else cv2.COLORMAP_WINTER,
    "Red Hot": cv2.COLORMAP_HOT,
    "Hot Red": cv2.COLORMAP_AUTUMN,
    "Black Hot": cv2.COLORMAP_BONE,
}


@dataclass
class FrameSnapshot:
    frame_num: int
    rgb_data: np.ndarray
    thermal_data: np.ndarray
    temp_min_c: float
    temp_max_c: float


class ThermalService:
    def __init__(self, screenshot_dir: str = "screenshots", video_dir: str = "videos"):
        self.screenshot_dir = os.path.abspath(screenshot_dir)
        self.video_dir = os.path.abspath(video_dir)

        self.video = Video()
        self.p2pro: Optional[P2Pro] = None
        self.camera_initialized = False
        self.video_thread: Optional[threading.Thread] = None

        self.palette_name = "White Hot"
        self.gain_state = 0
        self.measure_points: List[Tuple[int, int]] = []

        self.last_rgb: Optional[np.ndarray] = None
        self.last_thermal: Optional[np.ndarray] = None
        self.last_frame_num = -1
        self.latest_snapshot: Optional[FrameSnapshot] = None

        self.is_recording = False
        self.recording_dir: Optional[str] = None
        self.raw_frames: List[np.ndarray] = []
        self.rgb_writer: Optional[cv2.VideoWriter] = None

        self._lock = threading.RLock()

    def initialize(self, palette_name: str = "White Hot", gain_mode: str = "Low") -> None:
        with self._lock:
            if self.camera_initialized:
                return

            self.p2pro = P2Pro()
            self.palette_name = palette_name
            self.set_palette(palette_name)
            time.sleep(0.1)
            self.set_gain_mode(gain_mode)
            self.camera_initialized = True

    def start_video(self, camera_id: int | str = -1) -> None:
        with self._lock:
            if self.video_thread and self.video_thread.is_alive():
                return

            self.video_thread = threading.Thread(
                target=self.video.open,
                args=(camera_id,),
                daemon=True,
                name="P2ProVideoThread",
            )
            self.video_thread.start()

    def stop(self) -> None:
        with self._lock:
            if self.is_recording:
                self.stop_recording()
            self.video.video_running = False

    def set_palette(self, palette_name: str) -> None:
        with self._lock:
            self.palette_name = palette_name
            if not self.p2pro:
                return
            palette = PALETTE_MAP.get(palette_name, PseudoColorTypes.PSEUDO_WHITE_HOT)
            self.p2pro.pseudo_color_set(0, palette)

    def set_gain_mode(self, gain_mode: str) -> int:
        with self._lock:
            if not self.p2pro:
                return self.gain_state
            new_state = 1 if str(gain_mode).lower() == "high" else 0
            self.p2pro.set_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL, new_state)
            time.sleep(0.05)
            return self.get_gain_status()

    def get_gain_status(self) -> int:
        with self._lock:
            if not self.p2pro:
                return self.gain_state
            val = self.p2pro.get_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL)
            self.gain_state = int(val)
            return self.gain_state

    def toggle_gain(self) -> int:
        with self._lock:
            new_state = 0 if self.gain_state == 1 else 1
            if self.p2pro:
                self.p2pro.set_prop_tpd_params(PropTpdParams.TPD_PROP_GAIN_SEL, new_state)
                time.sleep(0.05)
                return self.get_gain_status()
            self.gain_state = new_state
            return self.gain_state

    def set_emissivity(self, emissivity: float) -> None:
        with self._lock:
            if self.p2pro:
                self.p2pro.set_emissivity(emissivity)

    def toggle_measure_point(self, x: int, y: int, threshold: int = 8) -> List[Tuple[int, int]]:
        with self._lock:
            for idx, (mx, my) in enumerate(self.measure_points):
                if abs(mx - x) <= threshold and abs(my - y) <= threshold:
                    del self.measure_points[idx]
                    return list(self.measure_points)
            self.measure_points.append((int(x), int(y)))
            return list(self.measure_points)

    def set_measure_points(self, points: List[Tuple[int, int]]) -> None:
        with self._lock:
            self.measure_points = [(int(x), int(y)) for x, y in points]

    def get_measure_points(self) -> List[Tuple[int, int]]:
        with self._lock:
            return list(self.measure_points)

    def _make_snapshot(self, frame_data: dict) -> Optional[FrameSnapshot]:
        thermal = frame_data.get("thermal_data")
        rgb_picture = frame_data.get("rgb_data")
        frame_num = int(frame_data.get("frame_num", -1))

        if thermal is None or rgb_picture is None:
            return None

        temp_min_val = round((float(np.min(thermal)) / 64.0) - 273.16, 1)
        temp_max_val = round((float(np.max(thermal)) / 64.0) - 273.16, 1)

        snapshot = FrameSnapshot(
            frame_num=frame_num,
            rgb_data=np.array(rgb_picture, copy=True),
            thermal_data=np.array(thermal, copy=True),
            temp_min_c=temp_min_val,
            temp_max_c=temp_max_val,
        )

        with self._lock:
            self.last_frame_num = snapshot.frame_num
            self.last_rgb = snapshot.rgb_data.copy()
            self.last_thermal = snapshot.thermal_data.copy()
            self.latest_snapshot = FrameSnapshot(
                frame_num=snapshot.frame_num,
                rgb_data=snapshot.rgb_data.copy(),
                thermal_data=snapshot.thermal_data.copy(),
                temp_min_c=snapshot.temp_min_c,
                temp_max_c=snapshot.temp_max_c,
            )
            if self.is_recording:
                self._record_frame(snapshot.rgb_data, snapshot.thermal_data)

        return snapshot

    def get_latest_frame(self, queue_index: int = 1) -> Optional[FrameSnapshot]:
        frame_data = None
        queue_obj = self.video.frame_queue[queue_index]

        while not queue_obj.empty():
            frame_data = queue_obj.get()

        if isinstance(frame_data, dict):
            snapshot = self._make_snapshot(frame_data)
            if snapshot is not None:
                return snapshot

        with self._lock:
            if self.latest_snapshot is None:
                return None
            return FrameSnapshot(
                frame_num=self.latest_snapshot.frame_num,
                rgb_data=self.latest_snapshot.rgb_data.copy(),
                thermal_data=self.latest_snapshot.thermal_data.copy(),
                temp_min_c=self.latest_snapshot.temp_min_c,
                temp_max_c=self.latest_snapshot.temp_max_c,
            )

    def wait_for_frame(self, timeout: float = 1.0, poll_interval: float = 0.02) -> Optional[FrameSnapshot]:
        end_time = time.time() + timeout
        snapshot = self.get_latest_frame()
        if snapshot is not None:
            return snapshot

        while time.time() < end_time:
            snapshot = self.get_latest_frame()
            if snapshot is not None:
                return snapshot
            time.sleep(poll_interval)
        return None

    def save_screenshot(self, timeout: float = 1.0) -> Optional[str]:
        snapshot = self.wait_for_frame(timeout=timeout)
        if snapshot is None:
            return None

        with self._lock:
            rgb = self.last_rgb.copy() if self.last_rgb is not None else snapshot.rgb_data.copy()
            thermal = self.last_thermal.copy() if self.last_thermal is not None else snapshot.thermal_data.copy()
            points = [[int(x), int(y)] for (x, y) in self.measure_points]

        ts = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(self.screenshot_dir, exist_ok=True)
        base = os.path.join(self.screenshot_dir, f"screenshot_{ts}")

        ok = cv2.imwrite(f"{base}.png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        if not ok:
            return None

        np.save(f"{base}_raw.npy", thermal)
        data = {"measure_points": points}
        with open(f"{base}_points.json", "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

        return f"{base}.png"

    def start_recording(self) -> Optional[str]:
        with self._lock:
            if self.is_recording:
                return self.recording_dir

            ts = time.strftime("%Y%m%d_%H%M%S")
            os.makedirs(self.video_dir, exist_ok=True)
            rec_dir = os.path.join(self.video_dir, f"rec_{ts}")
            os.makedirs(rec_dir, exist_ok=True)

            self.recording_dir = rec_dir
            self.raw_frames = []
            self.rgb_writer = None
            self.is_recording = True
            return rec_dir

    def stop_recording(self) -> Optional[str]:
        with self._lock:
            if not self.is_recording:
                return self.recording_dir

            self.is_recording = False
            recording_dir = self.recording_dir
            if recording_dir is None:
                return None

            if self.rgb_writer is not None:
                self.rgb_writer.release()
                self.rgb_writer = None

            if self.raw_frames:
                np.save(os.path.join(recording_dir, "rawframes.npy"), np.stack(self.raw_frames, axis=0))

            data = {"measure_points": [[int(x), int(y)] for (x, y) in self.measure_points]}
            with open(os.path.join(recording_dir, "measure_points.json"), "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)

            avi_path = os.path.join(recording_dir, "video.avi")
            mkv_path = os.path.join(recording_dir, "video.mkv")
            if os.path.exists(avi_path):
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            avi_path,
                            "-c:v",
                            "libx264",
                            "-crf",
                            "20",
                            "-pix_fmt",
                            "yuv420p",
                            mkv_path,
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    os.remove(avi_path)
                except Exception as exc:
                    print(f"[WARN] ffmpeg-Umwandlung oder Löschen fehlgeschlagen: {exc}")

            self.raw_frames = []
            return recording_dir

    def toggle_recording(self) -> Dict[str, Optional[str]]:
        with self._lock:
            if self.is_recording:
                path = self.stop_recording()
                return {"is_recording": False, "recording_dir": path}
            path = self.start_recording()
            return {"is_recording": True, "recording_dir": path}

    def build_colormap_bar(self, temp_min: float, temp_max: float) -> np.ndarray:
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

    def _record_frame(self, rgb_picture: np.ndarray, thermal: np.ndarray) -> None:
        if self.recording_dir is None:
            return

        h, w, _ = rgb_picture.shape
        if self.rgb_writer is None:
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self.rgb_writer = cv2.VideoWriter(
                os.path.join(self.recording_dir, "video.avi"),
                fourcc,
                30.0,
                (w, h),
            )

        self.rgb_writer.write(cv2.cvtColor(rgb_picture, cv2.COLOR_RGB2BGR))
        self.raw_frames.append(np.array(thermal, dtype=thermal.dtype))