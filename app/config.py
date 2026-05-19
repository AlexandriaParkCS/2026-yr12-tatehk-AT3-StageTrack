import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def default_sqlite_uri():
    return f"sqlite:///{INSTANCE_DIR / 'backstage.db'}"


def normalize_database_url(value):
    if not value:
        return default_sqlite_uri()
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql://", 1)
    return value


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    QR_FOLDER = str(BASE_DIR / "app" / "static" / "qr_codes")
    BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
    RESET_TOKEN_HOURS = 24
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", "http")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    OBJECT_STORAGE_PROVIDER = os.getenv("OBJECT_STORAGE_PROVIDER", "").strip().lower()
    OBJECT_STORAGE_BUCKET = os.getenv("OBJECT_STORAGE_BUCKET", "").strip()
    OBJECT_STORAGE_REGION = os.getenv("OBJECT_STORAGE_REGION", "").strip() or "auto"
    OBJECT_STORAGE_ENDPOINT = os.getenv("OBJECT_STORAGE_ENDPOINT", "").strip().rstrip("/")
    OBJECT_STORAGE_ACCESS_KEY = os.getenv("OBJECT_STORAGE_ACCESS_KEY", "").strip()
    OBJECT_STORAGE_SECRET_KEY = os.getenv("OBJECT_STORAGE_SECRET_KEY", "").strip()
