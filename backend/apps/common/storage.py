"""Cloudinary storage for uploaded pictures (restaurant logo, cover and menu photos).

Production only: set CLOUDINARY_URL (cloudinary://API_KEY:API_SECRET@CLOUD_NAME) and config/settings/production.py switches the default
file storage to this class. Everything above it (apps/common/images.py, the views, the serializers) already talks to the storage
interface (save, delete, exists, url), so nothing else changes.

A stored name looks like ``restaurants/3/logo/<random>.webp``. Cloudinary's public id is that name without the extension, and the
address served to browsers is https://res.cloudinary.com/<cloud>/image/upload/restaurants/3/logo/<random>.webp. Names are random per
upload, so a replaced picture always has a new address and old copies are never served from a stale cache.
"""
import io
import os

from django.core.files.storage import Storage


class CloudinaryMediaStorage(Storage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import cloudinary

        cloudinary.config(secure=True)  # https addresses only (the site is https; http pictures would be blocked)

    @staticmethod
    def _public_id(name: str) -> str:
        return os.path.splitext(name)[0]

    def get_available_name(self, name, max_length=None):
        return name  # names are random, so there is nothing to avoid, and checking would cost a Cloudinary API call

    def _save(self, name, content):
        import cloudinary.uploader

        content.seek(0)
        cloudinary.uploader.upload(
            io.BytesIO(content.read()),  # a file-like object: the SDK uploads those as a real file (raw bytes are not)
            public_id=self._public_id(name),
            resource_type="image",
            overwrite=True,
            invalidate=True,
            unique_filename=False,
            use_filename=False,
        )
        return name

    def delete(self, name):
        import cloudinary.uploader

        if name:
            cloudinary.uploader.destroy(self._public_id(name), resource_type="image", invalidate=True)

    def exists(self, name):
        import cloudinary.api
        from cloudinary.exceptions import NotFound

        try:
            cloudinary.api.resource(self._public_id(name), resource_type="image")
        except NotFound:
            return False
        return True

    def url(self, name):
        from cloudinary.utils import cloudinary_url

        return cloudinary_url(self._public_id(name), format=os.path.splitext(name)[1].lstrip(".") or "webp",
                              resource_type="image", type="upload", secure=True)[0]

    def _open(self, name, mode="rb"):
        raise NotImplementedError("Cloudinary pictures are served from their own address; they are never opened by the server.")

    def size(self, name):
        raise NotImplementedError("The size of a Cloudinary picture is not looked up.")
