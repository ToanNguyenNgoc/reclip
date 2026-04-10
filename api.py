from routes.video import video_bp
from routes.mp3 import mp3_bp
from routes.search import search_bp


def register_routes(app):
    """Register all API blueprints onto the Flask app."""
    app.register_blueprint(video_bp)
    app.register_blueprint(mp3_bp)
    app.register_blueprint(search_bp)
