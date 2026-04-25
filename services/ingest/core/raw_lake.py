"""Raw lake — immutable content-addressed storage for raw payloads.

Design:

* Keys are content-addressed (:func:`libs.provenance.derive_raw_object_key`)
  so repeat fetches of the same bytes deduplicate naturally.
* ``put`` is idempotent: if the key exists we validate the hash matches
  and return the existing object's metadata without re-writing. This
  preserves object-lock integrity (immutability guarantee) and avoids
  spurious version churn.
* No personal-data filtering happens here — that is the extraction
  layer's job. The lake holds the bytes as fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from libs.provenance import compute_raw_sha256, derive_raw_object_key

if TYPE_CHECKING:
    from datetime import datetime

    from botocore.client import BaseClient


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Handle returned by :meth:`RawLake.put`."""

    bucket: str
    object_key: str
    content_sha256: str
    size_bytes: int
    content_type: str
    existed_before: bool


class RawLake(Protocol):
    """Common interface. Connectors depend on this, not on S3 directly."""

    async def put(
        self,
        *,
        source_id: str,
        payload: bytes,
        content_type: str,
        fetched_at_utc: datetime,
        extension: str,
    ) -> StoredArtifact: ...

    async def get(self, object_key: str) -> bytes: ...

    async def exists(self, object_key: str) -> bool: ...


class S3RawLake:
    """S3-backed implementation. Compatible with AWS S3 and Minio.

    boto3 is sync; we offload to a thread via :func:`asyncio.to_thread` so
    the rest of the connector can stay async. This is fine for the write
    volumes DIP targets (~100k records/day) and keeps the dependency tree
    small — the async s3 libraries (aiobotocore) add significant surface
    for marginal throughput gains at our scale.
    """

    def __init__(
        self,
        *,
        bucket: str,
        client: BaseClient,
    ) -> None:
        self._bucket = bucket
        self._client = client

    async def put(
        self,
        *,
        source_id: str,
        payload: bytes,
        content_type: str,
        fetched_at_utc: datetime,
        extension: str,
    ) -> StoredArtifact:
        import asyncio

        sha = compute_raw_sha256(payload)
        key = derive_raw_object_key(
            source_id=source_id,
            fetched_at_utc=fetched_at_utc,
            raw_sha256=sha,
            extension=extension,
        )

        existed = await asyncio.to_thread(self._head, key)
        if existed is not None:
            # Same key => same bytes (content addressed). Verify hash for
            # paranoia; reject if somehow mismatched.
            if existed != sha:
                raise RuntimeError(
                    f"Raw lake integrity error: object {key} hash mismatch "
                    f"(found {existed}, expected {sha})"
                )
            return StoredArtifact(
                bucket=self._bucket,
                object_key=key,
                content_sha256=sha,
                size_bytes=len(payload),
                content_type=content_type,
                existed_before=True,
            )

        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
            Metadata={"sha256": sha, "source_id": source_id},
        )
        return StoredArtifact(
            bucket=self._bucket,
            object_key=key,
            content_sha256=sha,
            size_bytes=len(payload),
            content_type=content_type,
            existed_before=False,
        )

    async def get(self, object_key: str) -> bytes:
        import asyncio

        resp = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self._bucket,
            Key=object_key,
        )
        body = resp["Body"]
        try:
            return bytes(body.read())
        finally:
            body.close()

    async def exists(self, object_key: str) -> bool:
        import asyncio

        return (await asyncio.to_thread(self._head, object_key)) is not None

    # ── internals ────────────────────────────────────────────────
    def _head(self, key: str) -> str | None:
        """Return the stored sha256 if the object exists, else None."""
        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=key)
        except self._client.exceptions.ClientError as e:  # type: ignore[union-attr]
            code = e.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        meta = resp.get("Metadata", {}) or {}
        sha_value = meta.get("sha256")
        return sha_value if isinstance(sha_value, str) else None
