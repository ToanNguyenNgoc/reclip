import os
from flask import Flask, render_template
from dotenv import load_dotenv

load_dotenv()

from api import register_routes

app = Flask(__name__)

register_routes(app)


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
