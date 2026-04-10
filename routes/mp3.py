import os
import re
import uuid
import glob
import subprocess
import threading

from flask import Blueprint, request, jsonify, send_file

from utils.ytdlp import get_cookie_args
from utils.auth import require_api_key

MP3_DIR = os.path.join(os.path.dirname(__file__), "..", "downloads", "mp3")
os.makedirs(MP3_DIR, exist_ok=True)

mp3_bp = Blueprint("mp3", __name__)

mp3_jobs = {}

# Pattern: [download]  45.3% of 4.20MiB at 1.23MiB/s ETA 00:02
_PROGRESS_RE = re.compile(
    r"\[download\]\s+([\d.]+)%"
    r"(?:\s+of\s+[\d.]+\S+)?"
    r"(?:\s+at\s+([\d.]+\S+))?"
    r"(?:\s+ETA\s+(\S+))?"
)


def _build_media_url(req, job_id: str) -> str:
    """Build the public URL for a finished MP3 job."""
    base = req.host_url.rstrip("/")
    return f"{base}/media/{job_id}.mp3"


def _run_mp3_download(job_id: str, url: str) -> None:
    """Background worker: download URL as MP3, tracking progress."""
    job = mp3_jobs[job_id]
    out_template = os.path.join(MP3_DIR, f"{job_id}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--newline",              # one progress line per update
        "-o", out_template,
        "-x", "--audio-format", "mp3",
        "--audio-quality", "0",   # best quality
    ]
    cmd += get_cookie_args(url)
    cmd.append(url)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Read stdout line-by-line to capture progress
        for line in proc.stdout:
            m = _PROGRESS_RE.search(line.rstrip())
            if m:
                pct = round(float(m.group(1)), 1)
                job["progress"] = pct
                if m.group(2):
                    job["speed"] = m.group(2)
                if m.group(3):
                    job["eta"] = m.group(3)
                # Download hit 100% → yt-dlp hands off to ffmpeg for conversion
                if pct >= 100.0 and job["status"] == "downloading":
                    job["status"] = "converting"

        _, stderr_output = proc.communicate(timeout=300)
        stderr_lines = stderr_output.strip().splitlines()

        if proc.returncode != 0:
            job["status"] = "error"
            job["error"] = stderr_lines[-1] if stderr_lines else "Unknown error"
            return

        files = glob.glob(os.path.join(MP3_DIR, f"{job_id}.*"))
        mp3_files = [f for f in files if f.endswith(".mp3")]
        chosen = mp3_files[0] if mp3_files else (files[0] if files else None)

        if not chosen:
            job["status"] = "error"
            job["error"] = "Download completed but no file was found"
            return

        job["progress"] = 100.0
        job["status"] = "done"
        job["file"] = chosen
    except subprocess.TimeoutExpired:
        proc.kill()
        job["status"] = "error"
        job["error"] = "Download timed out (5 min limit)"
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)


@mp3_bp.route("/api/mp3", methods=["POST"])
@require_api_key
def mp3_start():
    """Async: start MP3 download, return job_id immediately.

    Body: { "url": "<video_url>" }
    Response: { "job_id": "...", "status_url": "...", "media_url": "..." }
    """
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = uuid.uuid4().hex[:12]
    mp3_jobs[job_id] = {"status": "downloading", "url": url}

    thread = threading.Thread(target=_run_mp3_download, args=(job_id, url))
    thread.daemon = True
    thread.start()

    base = request.host_url.rstrip("/")
    return jsonify({
        "job_id": job_id,
        "status": "downloading",
        "status_url": f"{base}/api/mp3/status/{job_id}",
        "media_url": f"{base}/media/{job_id}.mp3",
        "origin_url": f"/media/{job_id}.mp3"
    })


@mp3_bp.route("/api/mp3/sync", methods=["POST"])
@require_api_key
def mp3_sync():
    """Sync: block until MP3 is ready, return media link.

    Body: { "url": "<video_url>" }
    Response (success): { "job_id": "...", "media_url": "..." }
    Response (error):   { "error": "..." }
    """
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = uuid.uuid4().hex[:12]
    mp3_jobs[job_id] = {"status": "downloading", "url": url}

    _run_mp3_download(job_id, url)

    job = mp3_jobs[job_id]
    if job["status"] == "error":
        return jsonify({"error": job.get("error", "Unknown error")}), 500

    return jsonify({
        "job_id": job_id,
        "status": "done",
        "media_url": _build_media_url(request, job_id),
    })


@mp3_bp.route("/api/mp3/status/<job_id>")
def mp3_status(job_id):
    """Poll the status of an async MP3 download job.

    Response (downloading): { "status": "downloading", "progress": 45.3, "speed": "1.23MiB/s", "eta": "00:02" }
    Response (converting):  { "status": "converting",  "progress": 100.0 }
    Response (done):        { "status": "done",         "progress": 100.0, "media_url": "..." }
    Response (error):       { "status": "error",        "error": "..." }
    """
    job = mp3_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    resp = {
        "status": job["status"],
        "progress": job.get("progress", 0.0),
    }
    if job["status"] == "downloading":
        if "speed" in job:
            resp["speed"] = job["speed"]
        if "eta" in job:
            resp["eta"] = job["eta"]
    elif job["status"] == "done":
        resp["media_url"] = _build_media_url(request, job_id)
    elif job["status"] == "error":
        resp["error"] = job.get("error")
    # "converting" — only returns progress=100, no extra fields needed
    return jsonify(resp)


@mp3_bp.route("/media/<job_id>.mp3")
def serve_mp3(job_id):
    """Stream the finished MP3 file inline (not as attachment).

    Priority:
      1. File path recorded in the job dict (fastest).
      2. Direct disk lookup (survives server restarts / race conditions).
    """
    job = mp3_jobs.get(job_id)
    disk_path = os.path.join(MP3_DIR, f"{job_id}.mp3")

    if job and job["status"] == "done" and job.get("file"):
        file_path = job["file"]
    elif os.path.isfile(disk_path):
        # File already on disk — serve regardless of in-memory status.
        # Handles: server restart, ffmpeg conversion race, etc.
        file_path = disk_path
    elif job and job["status"] == "error":
        return jsonify({"error": job.get("error", "Download failed")}), 500
    else:
        status = job["status"] if job else "not found"
        return jsonify({"error": f"File not ready ({status}), please wait"}), 202

    if not os.path.isfile(file_path):
        return jsonify({"error": "File missing on server"}), 404

    return send_file(
        file_path,
        mimetype="audio/mpeg",
        as_attachment=False,          # inline — browsers/players can stream it
        download_name=os.path.basename(file_path),
        conditional=True,             # enables Range / ETags
    )
