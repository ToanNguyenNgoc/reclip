import os
import shutil

DOUYIN_DOMAINS = ("douyin.com", "tiktok.com")
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "..", "cookies.txt")
PREFERRED_BROWSERS = ["chrome", "firefox", "safari", "edge"]


def needs_cookies(url: str) -> bool:
    return any(d in url for d in DOUYIN_DOMAINS)


def get_cookie_args(url: str) -> list:
    """Return yt-dlp cookie arguments for URLs that require authentication."""
    if not needs_cookies(url):
        return []
    if os.path.isfile(COOKIES_FILE):
        return ["--cookies", COOKIES_FILE]
    for browser in PREFERRED_BROWSERS:
        if shutil.which(browser) or True:  # always try, yt-dlp handles the check
            return ["--cookies-from-browser", browser]
    return []
