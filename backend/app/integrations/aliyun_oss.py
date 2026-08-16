"""Aliyun OSS adapter for private QC images."""

from __future__ import annotations

import oss2

from app.core.config import settings


class OssError(RuntimeError):
    pass


def upload_image(bucket_name: str, object_key: str, image: bytes, content_type: str = "image/jpeg") -> None:
    if not all((settings.oss_endpoint, settings.oss_access_key_id.strip(), settings.oss_access_key_secret.strip(), bucket_name)):
        raise OssError("Aliyun OSS is not configured")
    auth = oss2.Auth(settings.oss_access_key_id.strip(), settings.oss_access_key_secret.strip())
    result = oss2.Bucket(auth, settings.oss_endpoint, bucket_name).put_object(
        object_key, image, headers={"Content-Type": content_type},
    )
    if result.status not in {200, 201}:
        raise OssError(f"OSS upload failed with HTTP {result.status}")


def delete_image(bucket_name: str, object_key: str) -> None:
    auth = oss2.Auth(settings.oss_access_key_id.strip(), settings.oss_access_key_secret.strip())
    oss2.Bucket(auth, settings.oss_endpoint, bucket_name).delete_object(object_key)


def signed_download_url(bucket_name: str, object_key: str, expires_in: int = 300, download_name: str | None = None) -> str:
    auth = oss2.Auth(settings.oss_access_key_id.strip(), settings.oss_access_key_secret.strip())
    params = {"response-content-disposition": f'attachment; filename="{download_name}"'} if download_name else None
    return oss2.Bucket(auth, settings.oss_endpoint, bucket_name).sign_url("GET", object_key, expires_in, params=params)
