import os


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


class Config:
    """Configuration is read from the environment; no secret is hard-coded."""

    def __init__(self):
        self.DB_HOST = os.environ.get("DB_HOST", "localhost")
        self.DB_PORT = int(os.environ.get("DB_PORT", "5432"))
        self.DB_NAME = os.environ.get("DB_NAME", "uni_records")
        self.DB_USER = _required("DB_USER")
        self.DB_PASSWORD = _required("DB_PASSWORD")

        self.COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
        self.SESSION_COOKIE = "__Host-urs_session" if self.COOKIE_SECURE else "urs_session"
        self.SESSION_IDLE_MINUTES = 30
        self.SESSION_ABSOLUTE_HOURS = 8

        self.LOCKOUT_THRESHOLD = 5
        self.LOCKOUT_MINUTES = 15
        self.MIN_PASSWORD_LENGTH = 12
