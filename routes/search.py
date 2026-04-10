import json
import subprocess

from flask import Blueprint, request, jsonify

from utils.auth import require_api_key

search_bp = Blueprint("search", __name__)

# Maximum results the caller can request (hard cap to avoid abuse)
MAX_RESULTS = 50


def _format_duration(seconds) -> str:
    """Convert raw seconds (int/float/None) → 'MM:SS' or 'HH:MM:SS'."""
    if not seconds:
        return "0:00"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_views(n) -> str:
    """Compact number: 1_234_567 → '1.2M'."""
    if n is None:
        return ""
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


@search_bp.route("/api/search", methods=["GET"])
@require_api_key
def search_youtube():
    """Search YouTube and return a list of video results.

    Query params:
        q        (required) — search keywords
        limit    (optional) — number of results, 1–50, default 10
        lang     (optional) — preferred language code (e.g. 'vi', 'en'), default none

    Response 200:
    {
        "query": "lo-fi music",
        "total": 10,
        "results": [
            {
                "id":          "dQw4w9WgXcQ",
                "url":         "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title":       "Rick Astley - Never Gonna Give You Up",
                "channel":     "Rick Astley",
                "channel_url": "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw",
                "thumbnail":   "https://...",
                "duration":    "3:33",
                "duration_s":  213,
                "views":       "1.4B",
                "views_raw":   1400000000,
                "upload_date": "2009-10-25"
            },
            ...
        ]
    }
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        return jsonify({"error": "Parameter 'limit' must be an integer"}), 400

    limit = max(1, min(limit, MAX_RESULTS))

    # yt-dlp: ytsearchN:<query> fetches N results from YouTube search
    search_url = f"ytsearch{limit}:{query}"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--flat-playlist",      # don't download, just extract metadata
        "--dump-single-json",   # output all entries as one JSON object
        "--no-warnings",
        search_url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Search timed out (30 s limit)"}), 504

    if result.returncode != 0:
        err = result.stderr.strip().splitlines()
        return jsonify({"error": err[-1] if err else "yt-dlp search failed"}), 502

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse yt-dlp output"}), 502

    entries = data.get("entries") or []
    items = []
    for entry in entries:
        if not entry:
            continue

        video_id = entry.get("id") or entry.get("url", "")
        # Normalise URL
        url = entry.get("webpage_url") or (
            f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        )

        # Upload date: yt-dlp returns "YYYYMMDD"
        raw_date = entry.get("upload_date") or ""
        upload_date = (
            f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            if len(raw_date) == 8
            else raw_date
        )

        duration_s = entry.get("duration")
        views_raw = entry.get("view_count")

        # --flat-playlist exposes a 'thumbnails' list, not a single 'thumbnail'.
        # Pick the highest-resolution entry (largest width).
        thumbnails = entry.get("thumbnails") or []
        if thumbnails:
            best = max(thumbnails, key=lambda t: t.get("width") or 0)
            thumbnail = best.get("url", "")
        else:
            thumbnail = entry.get("thumbnail") or ""

        items.append({
            "id":          video_id,
            "url":         url,
            "title":       entry.get("title") or "",
            "channel":     entry.get("uploader") or entry.get("channel") or "",
            "channel_url": entry.get("uploader_url") or entry.get("channel_url") or "",
            "thumbnail":   thumbnail,
            "duration":    _format_duration(duration_s),
            "duration_s":  duration_s,
            "views":       _format_views(views_raw),
            "views_raw":   views_raw,
            "upload_date": upload_date,
        })

    return jsonify({
        "query":   query,
        "total":   len(items),
        "results": items,
    })
