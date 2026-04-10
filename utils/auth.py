import os
from functools import wraps

from flask import request, jsonify


def require_api_key(f):
    """Decorator: reject requests that don't carry a valid X-API-Key header.

    Usage:
        @mp3_bp.route("/api/mp3", methods=["POST"])
        @require_api_key
        def mp3_start():
            ...

    The expected key is read from the X_API_KEY environment variable.
    Returns 401 if the header is missing or the key doesn't match.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        expected_key = os.environ.get("X_API_KEY", "")
        if not expected_key:
            # Fail-safe: if no key is configured, deny all requests
            return jsonify({"error": "API key not configured on server"}), 500

        client_key = request.headers.get("X-API-Key", "").strip()
        if not client_key:
            return jsonify({"error": "Missing X-API-Key header"}), 401

        if client_key != expected_key:
            return jsonify({"error": "Invalid API key"}), 401

        return f(*args, **kwargs)
    return decorated
