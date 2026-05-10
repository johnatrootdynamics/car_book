from uuid import uuid4

import boto3
from botocore.client import Config


def upload_public_image(
    file_storage,
    bucket,
    endpoint_url,
    access_key,
    secret_key,
    key_prefix,
    public_base_url=None,
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

    base_url = (public_base_url or endpoint_url).rstrip("/")
    return f"{base_url}/{bucket}/{object_key}"
