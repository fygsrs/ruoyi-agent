"""Validate uploaded image bytes at the external file boundary."""

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .errors import ImageInputError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_FORMATS = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}


def image_info(data: bytes) -> tuple[str, str, int, int]:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageInputError("图片不能为空，且每张不能超过 10 MB。")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in IMAGE_FORMATS:
                raise ImageInputError("请上传 PNG、JPG 或 WebP 图片。")
            width, height = image.size
            if max(width, height) > 8000 or max(width, height) > min(width, height) * 10:
                raise ImageInputError("图片宽高不能超过 8000 像素，长宽比不能超过 10:1。")
            media_type, suffix = IMAGE_FORMATS[image.format]
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ImageInputError("图片文件损坏或格式无效。") from exc
    return media_type, suffix, width, height
