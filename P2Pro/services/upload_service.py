"""Pi-side upload client for the P2Pro media server.

Uploads new media bundles (screenshots + videos) to a remote server via HTTP + API key auth.
Tracks which files have already been uploaded in upload_state.json.

Configuration: upload.conf (see upload.conf.example — do not commit the real file)
Status file:   upload_status.json  (written here, read by web_api for /api/upload/status)

Usage:
    python3 -m P2Pro.services.upload_service       # run manually / called by systemd
"""

from __future__ import annotations

import configparser
import io
import json
import os
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

CONFIG_FILE = Path("upload.conf")
STATE_FILE = Path("upload_state.json")
STATUS_FILE = Path("upload_status.json")

_upload_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Status helpers (written to STATUS_FILE so web_api can expose them)
# ---------------------------------------------------------------------------

def _write_status(state: str, total: int = 0, uploaded: int = 0, current: str = "", error: str | None = None) -> None:
    data: dict[str, Any] = {
        "state": state,          # "idle" | "running" | "done" | "error"
        "total": total,
        "uploaded": uploaded,
        "current": current,
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_error": error,
    }
    STATUS_FILE.write_text(json.dumps(data, indent=2))


def read_status() -> dict[str, Any]:
    """Read current upload status. Returns idle status if file doesn't exist."""
    if not STATUS_FILE.exists():
        return {"state": "idle", "total": 0, "uploaded": 0, "current": "", "last_run": None, "last_error": None}
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {"state": "idle", "total": 0, "uploaded": 0, "current": "", "last_run": None, "last_error": None}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> tuple[str, str, str, str]:
    """Returns (server_url, api_key, screenshots_dir, videos_dir)."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}. Copy upload.conf.example to upload.conf and fill in your values.")

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)

    server_url = cfg.get("server", "url").rstrip("/")
    api_key = cfg.get("server", "api_key")
    screenshots_dir = cfg.get("paths", "screenshots_dir", fallback="screenshots")
    videos_dir = cfg.get("paths", "videos_dir", fallback="videos")

    return server_url, api_key, screenshots_dir, videos_dir


# ---------------------------------------------------------------------------
# State tracking (which bundles have already been uploaded)
# ---------------------------------------------------------------------------

def _load_state() -> set[str]:
    """Returns a set of already-uploaded bundle IDs."""
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("uploaded", []))
    except Exception:
        return set()


def _save_state(uploaded: set[str]) -> None:
    STATE_FILE.write_text(json.dumps({"uploaded": sorted(uploaded)}, indent=2))


# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------

def _collect_bundles(screenshots_dir: str, videos_dir: str) -> list[dict[str, Any]]:
    """Return a list of bundle dicts, each with id, type, and file paths."""
    bundles: list[dict[str, Any]] = []

    # Screenshots: {stem}.png + {stem}_raw.npy + optional {stem}_points.json
    ss_path = Path(screenshots_dir)
    if ss_path.exists():
        for png in sorted(ss_path.glob("*.png")):
            stem = png.stem
            raw = ss_path / f"{stem}_raw.npy"
            points = ss_path / f"{stem}_points.json"
            if raw.exists():
                bundles.append({
                    "id": f"screenshot:{stem}",
                    "type": "screenshot",
                    "files": [png, raw] + ([points] if points.exists() else []),
                })

    # Videos: rec_*/ directories containing video.mp4 (or .avi) + rawframes.npy
    vid_path = Path(videos_dir)
    if vid_path.exists():
        for rec_dir in sorted(vid_path.glob("rec_*")):
            if not rec_dir.is_dir():
                continue
            video_file = next(
                (rec_dir / name for name in ("video.mp4", "video.avi", "video.mkv") if (rec_dir / name).exists()),
                None,
            )
            raw = rec_dir / "rawframes.npy"
            if video_file and raw.exists():
                files = [video_file, raw]
                for optional in ("thumbnail.jpg", "measure_points.json"):
                    f = rec_dir / optional
                    if f.exists():
                        files.append(f)
                bundles.append({
                    "id": f"video:{rec_dir.name}",
                    "type": "video",
                    "files": files,
                    "dir_name": rec_dir.name,
                })

    return bundles


# ---------------------------------------------------------------------------
# Upload logic
# ---------------------------------------------------------------------------

def _upload_bundle(bundle: dict[str, Any], server_url: str, api_key: str) -> None:
    """Upload a single bundle to the server as a flat zip via multipart POST.

    POST {server_url}/api/upload/ingest
    Fields: bundle_type, bundle_id, file (zip archive of all bundle files, flat — no subdirs)
    Auth: X-API-Key header
    Response: {"ingested": "<bundle_id>", "type": "<bundle_type>"}
    """
    bundle_type = bundle["type"]
    if bundle_type == "screenshot":
        bundle_id = bundle["id"].split(":", 1)[1]   # strip "screenshot:" prefix → stem
    else:
        bundle_id = bundle["dir_name"]              # e.g. rec_2024-01-15_10-30-00

    # Build zip in memory — flat (no subdirectories)
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in bundle["files"]:
            zf.write(f, arcname=Path(f).name)
    zip_bytes = zip_buf.getvalue()

    # Encode as multipart/form-data
    boundary = "P2ProUploadBoundary"
    parts: list[bytes] = []

    def _field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()

    parts.append(_field("bundle_type", bundle_type))
    parts.append(_field("bundle_id", bundle_id))
    parts.append(
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{bundle_id}.zip"\r\n'
        f'Content-Type: application/zip\r\n\r\n'.encode()
        + zip_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(parts)

    req = urllib.request.Request(
        f"{server_url}/api/upload/ingest",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-API-Key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise RuntimeError(f"Server returned {exc.code}: {body_text}") from exc

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Unexpected server response: {raw!r}")

    if result.get("ingested") != bundle_id:
        raise RuntimeError(f"Unexpected ingest response: {result}")


# ---------------------------------------------------------------------------
# Main upload loop
# ---------------------------------------------------------------------------

def run_upload() -> None:
    """Collect all bundles, skip already-uploaded ones, upload the rest."""
    if not _upload_lock.acquire(blocking=False):
        print("Upload already in progress, skipping.")
        return

    try:
        try:
            server_url, api_key, screenshots_dir, videos_dir = _load_config()
        except Exception as exc:
            _write_status("error", error=str(exc))
            print(f"Upload config error: {exc}")
            return

        already_uploaded = _load_state()
        all_bundles = _collect_bundles(screenshots_dir, videos_dir)
        pending = [b for b in all_bundles if b["id"] not in already_uploaded]

        if not pending:
            _write_status("done", total=0, uploaded=0)
            print("Nothing to upload.")
            return

        _write_status("running", total=len(pending), uploaded=0)

        for i, bundle in enumerate(pending):
            _write_status("running", total=len(pending), uploaded=i, current=bundle["id"])
            try:
                _upload_bundle(bundle, server_url, api_key)
                already_uploaded.add(bundle["id"])
                _save_state(already_uploaded)
                print(f"Uploaded {bundle['id']}")
            except NotImplementedError:
                _write_status("error", total=len(pending), uploaded=i, error="Upload not yet implemented")
                print("Upload not yet implemented.")
                return
            except Exception as exc:
                _write_status("error", total=len(pending), uploaded=i, current=bundle["id"], error=str(exc))
                print(f"Failed to upload {bundle['id']}: {exc}")
                return

        _write_status("done", total=len(pending), uploaded=len(pending))
        print(f"Upload complete: {len(pending)} bundle(s) uploaded.")

    finally:
        _upload_lock.release()


def run_in_background() -> threading.Thread:
    """Trigger upload in a background thread (called by web_api on manual trigger)."""
    t = threading.Thread(target=run_upload, daemon=True, name="upload-service")
    t.start()
    return t


if __name__ == "__main__":
    run_upload()
