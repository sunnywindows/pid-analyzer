"""PDF 转图片与图像工具。"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from pdf2image import convert_from_bytes
from PIL import Image

# AI 视觉大模型单边最大像素，超过则等比缩放，控制 token 消耗
MAX_AI_EDGE = 4096
# 预览缩略图单边像素
PREVIEW_EDGE = 1200


def _to_rgb(img: Image.Image) -> Image.Image:
    return img if img.mode == "RGB" else img.convert("RGB")


def _resize_edge(img: Image.Image, max_edge: int) -> Image.Image:
    w, h = img.size
    scale = min(1.0, max_edge / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def load_as_images(data: bytes, filename: str) -> list[Image.Image]:
    """把上传文件统一转成 PIL Image 列表（保留原始分辨率，供 OCR 使用）。

    - 图片：直接解码
    - PDF：逐页渲染
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        images = convert_from_bytes(data, dpi=200, fmt="png")
        return [_to_rgb(im) for im in images]
    img = Image.open(io.BytesIO(data))
    img.load()
    return [_to_rgb(img)]


def normalize_for_ai(img: Image.Image) -> Image.Image:
    """等比缩放，控制视觉大模型输入尺寸。"""
    return _resize_edge(_to_rgb(img), MAX_AI_EDGE)


def preview_b64(img: Image.Image) -> str:
    """生成前端展示用的 JPEG 缩略图 base64。"""
    thumb = _resize_edge(_to_rgb(img), PREVIEW_EDGE)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def image_to_b64_png(img: Image.Image) -> str:
    """PIL Image -> base64 PNG 字符串（用于视觉大模型请求）。"""
    buf = io.BytesIO()
    _to_rgb(img).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
