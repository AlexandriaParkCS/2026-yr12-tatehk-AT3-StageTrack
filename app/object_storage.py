from io import BytesIO
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app


QR_PREFIX = "qr_codes"


def _configured():
    return (
        current_app.config.get("OBJECT_STORAGE_PROVIDER") == "r2"
        and current_app.config.get("OBJECT_STORAGE_BUCKET")
        and current_app.config.get("OBJECT_STORAGE_ACCESS_KEY")
        and current_app.config.get("OBJECT_STORAGE_SECRET_KEY")
    )


def _normalized_endpoint():
    endpoint = (current_app.config.get("OBJECT_STORAGE_ENDPOINT") or "").rstrip("/")
    bucket = (current_app.config.get("OBJECT_STORAGE_BUCKET") or "").strip()
    if bucket and endpoint.endswith(f"/{bucket}"):
        return endpoint[: -(len(bucket) + 1)]
    return endpoint


def _client():
    return boto3.client(
        "s3",
        region_name=current_app.config.get("OBJECT_STORAGE_REGION") or "auto",
        endpoint_url=_normalized_endpoint() or None,
        aws_access_key_id=current_app.config.get("OBJECT_STORAGE_ACCESS_KEY"),
        aws_secret_access_key=current_app.config.get("OBJECT_STORAGE_SECRET_KEY"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _qr_key(filename):
    return f"{QR_PREFIX}/{filename}"


def storage_enabled():
    return _configured()


def upload_qr(filename, content_bytes):
    if not storage_enabled():
        return False
    _client().put_object(
        Bucket=current_app.config["OBJECT_STORAGE_BUCKET"],
        Key=_qr_key(filename),
        Body=content_bytes,
        ContentType="image/png",
    )
    return True


def qr_exists(filename):
    if not storage_enabled():
        return False
    try:
        _client().head_object(Bucket=current_app.config["OBJECT_STORAGE_BUCKET"], Key=_qr_key(filename))
        return True
    except ClientError:
        return False


def download_qr(filename):
    if not storage_enabled():
        return None
    try:
        response = _client().get_object(Bucket=current_app.config["OBJECT_STORAGE_BUCKET"], Key=_qr_key(filename))
    except (ClientError, BotoCoreError):
        current_app.logger.warning("QR download failed for %s from object storage.", filename)
        return None
    return BytesIO(response["Body"].read())


def delete_qr(filename):
    if not storage_enabled():
        return False
    try:
        _client().delete_object(Bucket=current_app.config["OBJECT_STORAGE_BUCKET"], Key=_qr_key(filename))
        return True
    except (ClientError, BotoCoreError):
        return False


def local_qr_path(filename):
    return Path(current_app.config["QR_FOLDER"]) / filename


def storage_status():
    status = {
        "enabled": storage_enabled(),
        "provider": current_app.config.get("OBJECT_STORAGE_PROVIDER") or "local",
        "bucket": current_app.config.get("OBJECT_STORAGE_BUCKET") or "",
        "endpoint": current_app.config.get("OBJECT_STORAGE_ENDPOINT") or "",
        "ok": False,
        "message": "",
    }
    if not status["enabled"]:
        status["message"] = "Object storage is not configured, so StageTrack is using local QR files."
        return status

    try:
        _client().list_objects_v2(Bucket=current_app.config["OBJECT_STORAGE_BUCKET"], MaxKeys=1)
    except Exception as exc:
        status["message"] = str(exc)
        return status

    status["ok"] = True
    status["message"] = "Cloudflare R2 connection succeeded."
    return status
