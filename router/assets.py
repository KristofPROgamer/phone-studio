"""Bounded raster normalization and durable opaque asset storage."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import threading
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import RouterError, identifier
from .journal import now_ms


class AssetStore:
    def __init__(self, config, journal):
        self.config, self.journal = config, journal
        self.local = config.root / "assets"
        self.persistent = config.drive / "assets"
        self.local.mkdir(parents=True, exist_ok=True)
        self.persistent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def ingest(self, source: Path, kind="image"):
        if kind not in ("image", "mask"):
            raise RouterError("Upload kind must be image or mask.")
        source = Path(source)
        if source.stat().st_size > self.config.max_upload_bytes:
            raise RouterError("Image file is too large; the upload limit is 24 MiB.", 413, "asset_too_large")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as raw:
                    if raw.format not in {"PNG", "JPEG", "WEBP"} or getattr(raw, "n_frames", 1) != 1:
                        raise RouterError("Use a still PNG, JPEG or WebP image.")
                    if raw.width * raw.height > self.config.max_image_pixels:
                        raise RouterError("Image dimensions exceed the 16-megapixel limit.", 413, "asset_too_large")
                    if raw.width < 8 or raw.height < 8:
                        raise RouterError("Source images must be at least 8 by 8 pixels.")
                    raw.load()
                    oriented = ImageOps.exif_transpose(raw)
                    mode = "L" if kind == "mask" else ("RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB")
                    image = oriented.convert(mode)
                    normalization = "EXIF orientation applied; decoded raster PNG; metadata removed"
                    if kind == "image" and raw.info.get("icc_profile"):
                        try:
                            from PIL import ImageCms
                            profile = ImageCms.ImageCmsProfile(io.BytesIO(raw.info["icc_profile"]))
                            converted = ImageCms.profileToProfile(image, profile, ImageCms.createProfile("sRGB"), outputMode=mode)
                            image.close(); image = converted
                            normalization += "; ICC profile converted to sRGB"
                        except (OSError, ValueError, ImportError):
                            normalization += "; invalid or unsupported ICC profile ignored"
        except RouterError:
            raise
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise RouterError("This file could not be decoded safely as an image.") from exc
        with self._lock:
            temporary = self.local / f"upload-{uuid.uuid4()}.part"
            try:
                image.save(temporary, format="PNG", compress_level=1)
                size = temporary.stat().st_size
                if size > self.config.max_upload_bytes:
                    raise RouterError("The normalized image exceeds the 24 MiB image limit. Resize it before uploading.", 413, "asset_too_large")
                digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                # Kind is included: one image cannot masquerade as a user mask.
                asset_id = f"{kind}-{digest}"
                try:
                    existing = self.journal.asset(asset_id)
                    self.path(asset_id)
                    return existing
                except RouterError as exc:
                    if exc.status != 404:
                        raise
                used = sum(item["bytes"] for item in self.journal.assets())
                if used + size > self.config.asset_quota_bytes:
                    raise RouterError("Router image storage is full. Archive old images from the notebook before uploading more.", 507, "asset_quota")
                for directory in (self.local, self.persistent):
                    if shutil.disk_usage(directory).free - size < self.config.disk_reserve_bytes:
                        raise RouterError("The router does not have enough free storage for this image.", 507, "disk_full")
                target = self.local / f"{asset_id}.png"
                os.replace(temporary, target)
                part = self.persistent / f"{asset_id}.png.part"
                with target.open("rb") as src, part.open("wb") as dst:
                    shutil.copyfileobj(src, dst); dst.flush(); os.fsync(dst.fileno())
                os.replace(part, self.persistent / f"{asset_id}.png")
                result = {"assetId": asset_id, "width": image.width, "height": image.height,
                          "sha256": digest, "bytes": size, "kind": kind, "contentType": "image/png",
                          "createdAtMillis": now_ms(), "normalization": normalization}
                self.journal.put_asset(result)
                return result
            finally:
                image.close()
                temporary.unlink(missing_ok=True)

    def path(self, asset_id):
        identifier(asset_id, "Asset ID")
        self.journal.asset(asset_id)
        path = self.local / f"{asset_id}.png"
        if path.is_file():
            return path
        durable = self.persistent / f"{asset_id}.png"
        if not durable.is_file():
            raise RouterError("The stored image file is missing from router Drive.", 404, "not_found")
        # Serve persistent original directly after a reset; avoid duplicating the
        # whole durable library onto the fresh VM merely to display it.
        return durable

