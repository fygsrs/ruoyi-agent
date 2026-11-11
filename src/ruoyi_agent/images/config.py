"""Server-side image provider and persistent file configuration."""

from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class ImageSettings:
    api_key: str = field(repr=False)
    base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    model: str = "qwen-image-3.0"
    data_dir: Path = Path(__file__).resolve().parents[3] / "data" / "images"
    timeout_seconds: float = 60
    poll_interval_seconds: float = 3


def load_image_settings() -> ImageSettings:
    return ImageSettings(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.environ.get("IMAGE_API_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").rstrip("/"),
        model=os.environ.get("IMAGE_MODEL", "qwen-image-3.0"),
        data_dir=Path(os.environ.get("IMAGE_DATA_DIR", str(ImageSettings.data_dir))).resolve(),
    )
