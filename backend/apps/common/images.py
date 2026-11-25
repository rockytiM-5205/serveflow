"""Safe image uploads. Nothing the browser sends is trusted: the bytes are opened with Pillow, checked, resized and re-encoded
as WebP under a random name. That removes metadata (including GPS in photos), any hidden payload, and the original file name
and extension. Only JPEG, PNG and WebP are accepted.

Every stored picture has a fixed width and height for its kind, whatever was uploaded, so an odd-shaped upload can't disturb
the layout: a logo is a 512x512 square with the whole logo kept (empty space is added around it), a cover picture is
588x312 and a menu photo is 1000x750 (both cropped from the centre to fill the frame)."""
import io
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}  # MPO is how Pillow names many phone JPEGs
MAX_PIXELS = 36_000_000  # refuses "decompression bombs": small files that expand into enormous images
SIZES = {"menu": (1000, 750), "logo": (512, 512), "cover": (588, 312)}  # exact (width, height) in pixels, per kind of picture
CONTAIN = {"logo"}  # these keep the whole picture and pad the rest; every other kind fills the frame and crops the edges


class ImageRejected(Exception):
    """The upload can't be used. `message` is safe to show to the person who uploaded it."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def to_fixed_size(image, size, contain):
    """Exactly `size` pixels. contain: the whole picture, centred on a white (or transparent) canvas. Otherwise it fills the
    frame and the overflow is cropped equally from both sides."""
    width, height = size
    if not contain:
        return ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    scale = min(width / image.width, height / image.height)
    inner = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
    transparent = "A" in image.getbands()
    canvas = Image.new("RGBA" if transparent else "RGB", size, (0, 0, 0, 0) if transparent else (255, 255, 255))
    canvas.paste(inner, ((width - inner.width) // 2, (height - inner.height) // 2), inner if transparent else None)
    return canvas


def process_image(upload, kind):
    """Validate an uploaded file and return a ContentFile of the cleaned-up WebP image."""
    limit = getattr(settings, "MAX_IMAGE_UPLOAD_BYTES", 3 * 1024 * 1024)
    if upload is None:
        raise ImageRejected("Choose a picture to upload.")
    if upload.size > limit:
        raise ImageRejected(f"That picture is too large. The limit is {limit // (1024 * 1024)} MB.")
    data = b"".join(upload.chunks())
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ALLOWED_FORMATS:
            raise ImageRejected("Use a JPEG, PNG or WebP picture.")
        width, height = probe.size
        if width < 1 or height < 1 or width * height > MAX_PIXELS:
            raise ImageRejected("That picture has too many pixels. Use a smaller one.")
        probe.verify()  # catches truncated or corrupt files; the image must be reopened afterwards
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)  # honour the phone's rotation, then drop the metadata
        has_alpha = "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)
        image = image.convert("RGBA" if has_alpha else "RGB")
        image = to_fixed_size(image, SIZES[kind], contain=kind in CONTAIN)
        out = io.BytesIO()
        image.save(out, "WEBP", quality=82, method=4)
    except ImageRejected:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ImageRejected("That file isn't a picture we can read. Use a JPEG, PNG or WebP.") from None
    return ContentFile(out.getvalue(), name=f"{uuid.uuid4().hex}.webp")


def media_url(field_file):
    """The public path of a stored picture (relative, so it works behind any host), or None."""
    return field_file.url if field_file else None
