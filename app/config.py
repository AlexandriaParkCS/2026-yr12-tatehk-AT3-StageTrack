from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


class Config:
    SECRET_KEY = "change-me-in-production"
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{INSTANCE_DIR / 'backstage.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    QR_FOLDER = str(BASE_DIR / "app" / "static" / "qr_codes")
    RESET_TOKEN_HOURS = 24
