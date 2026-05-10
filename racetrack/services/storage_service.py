from uuid import uuid4
from urllib.parse import urlparse

import boto3
from botocore.client import Config


def upload_public_image(
    file_storage,
    bucket,
    endpoint_url,
    access_key,
    secret_key,
    key_prefix,
):
    clean_name = (file_storage.filename or "upload.bin").strip().replace(" ", "_")
    object_key = f"{key_prefix}/{uuid4().hex}_{clean_name}"

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

    file_storage.stream.seek(0)
    s3.upload_fileobj(
        file_storage.stream,
        bucket,
        object_key,
        ExtraArgs={"ContentType": file_storage.mimetype or "application/octet-stream"},
    )

    return object_key


def _extract_object_key(stored_value, bucket):
    if not stored_value:
        return None
    if stored_value.startswith("http://") or stored_value.startswith("https://"):
        parsed = urlparse(stored_value)
        path = (parsed.path or "").lstrip("/")
        bucket_prefix = f"{bucket}/"
        if path.startswith(bucket_prefix):
            return path[len(bucket_prefix):]
        return path
    return stored_value


def build_presigned_read_url(stored_value, bucket, endpoint_url, access_key, secret_key, expires_seconds=3600):
    object_key = _extract_object_key(stored_value, bucket)
    if not object_key:
        return None

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=expires_seconds,
    )
