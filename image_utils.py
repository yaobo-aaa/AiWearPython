import base64
import io

from PIL import Image


def detect_image(image_bytes: bytes):
    """用 PIL 校验字节可解码，返回真实格式与 MIME。

    Args:
        image_bytes: 图片原始字节

    Returns:
        (format, mime) 元组，例如 ("PNG", "image/png")；
        无法解码时返回 None（用于拦下非图片文件/伪造扩展名）。
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img_format = img.format or "JPEG"
            img.verify()
    except Exception:
        return None
    return img_format, f"image/{img_format.lower()}"


def build_data_url(image_bytes: bytes, mime: str) -> str:
    """把图片字节拼成 base64 data URL，供多模态接口使用。"""
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime};base64,{image_b64}"
