"""Media reference normalization, resolution and base64 conversions."""
import os
import re
import base64
import urllib.parse
import logging
from io import BytesIO
from typing import Any, Dict, List, Optional, Callable
from PIL import Image

from core.providers import BASE_DIR, ASSETS_DIR, OUTPUT_DIR, OUTPUT_OUTPUT_DIR

logger = logging.getLogger("infinite_canvas.media")

_storage_file_resolver: Optional[Callable[[str, str], Optional[str]]] = None

def set_storage_file_resolver(fn: Callable[[str, str], Optional[str]]) -> None:
    global _storage_file_resolver
    _storage_file_resolver = fn

def content_type_for_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in [".mp4", ".m4v"]:
        return "video/mp4"
    if ext == ".webm":
        return "video/webm"
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".avi":
        return "video/x-msvideo"
    if ext == ".mkv":
        return "video/x-matroska"
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    if ext == ".avif":
        return "image/avif"
    if ext in [".mp3"]:
        return "audio/mpeg"
    if ext in [".wav"]:
        return "audio/wav"
    if ext in [".m4a"]:
        return "audio/mp4"
    if ext in [".ogg"]:
        return "audio/ogg"
    if ext in [".flac"]:
        return "audio/flac"
    if ext in [".json"]:
        return "application/json"
    if ext in [".zip"]:
        return "application/zip"
    return "application/octet-stream"

def output_file_from_url(url: Any) -> Optional[str]:
    if isinstance(url, dict):
        url = url.get("url", "")
    if not url:
        return None
    clean = urllib.parse.unquote(str(url).split("?", 1)[0]).replace("\\", "/")
    if clean.startswith("/api/storage-files/"):
        rest = clean[len("/api/storage-files/"):].lstrip("/")
        kind, _, rel = rest.partition("/")
        if _storage_file_resolver:
            try:
                return _storage_file_resolver(kind, rel)
            except Exception:
                pass
        return None
    if not (clean.startswith("/output/") or clean.startswith("/assets/")):
        return None
    if clean.startswith("/assets/"):
        root = ASSETS_DIR
        rel = clean[len("/assets/"):]
    else:
        rel = clean[len("/output/"):]
    rel = rel.lstrip("/")
    if not rel:
        return None
    roots = [ASSETS_DIR] if clean.startswith("/assets/") else [OUTPUT_OUTPUT_DIR, OUTPUT_DIR]
    for root in roots:
        path = os.path.abspath(os.path.join(root, rel))
        output_root = os.path.abspath(root)
        try:
            if os.path.commonpath([output_root, path]) == output_root and os.path.exists(path):
                return path
        except ValueError:
            continue
    return None

def is_image_reference_value(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("data:image/"):
        return True
    if value.startswith("data:"):
        return False
    if value.startswith("/output/") or value.startswith("/assets/"):
        path = output_file_from_url(value)
        return bool(path and content_type_for_path(path).startswith("image/"))
    clean = value.split("?", 1)[0].lower()
    if re.search(r"\.(mp4|webm|mov|m4v|avi|mkv|mp3|wav|m4a|aac|ogg|flac)$", clean):
        return False
    return True

def is_video_reference_value(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("data:video/"):
        return True
    if value.startswith("data:"):
        return False
    if value.startswith("/output/") or value.startswith("/assets/"):
        path = output_file_from_url(value)
        return bool(path and content_type_for_path(path).startswith("video/"))
    clean = value.split("?", 1)[0].lower()
    return bool(re.search(r"\.(mp4|webm|mov|m4v|avi|mkv)$", clean))

def convert_output_to_jpg(url: str, quality: int = 88) -> str:
    path = output_file_from_url(url)
    if not path:
        return url
    root, ext = os.path.splitext(path)
    if ext.lower() in [".jpg", ".jpeg"]:
        return url
    jpg_path = f"{root}.jpg"
    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(jpg_path, "JPEG", quality=quality, optimize=True)
        try:
            root_dir = ASSETS_DIR if os.path.commonpath([os.path.abspath(ASSETS_DIR), os.path.abspath(jpg_path)]) == os.path.abspath(ASSETS_DIR) else OUTPUT_DIR
        except ValueError:
            root_dir = OUTPUT_DIR
        rel = os.path.relpath(jpg_path, root_dir).replace("\\", "/")
        prefix = "/assets" if root_dir == ASSETS_DIR else "/output"
        return f"{prefix}/{rel}"
    except Exception as e:
        logger.warning(f"转换 JPG 失败: {e}")
        return url

def reference_to_data_url(ref: Dict[str, Any], max_size: Optional[int] = 2048) -> str:
    """把本地输出文件转为 data URL（base64）。max_size 限制最长边像素，避免 payload 过大（默认 2048px）。"""
    raw_url = str(ref.get("url") or "").strip()
    if raw_url.startswith("data:image/"):
        return compress_data_url_image(raw_url, max_size=max_size or 2048, jpeg_quality=85)
    path = output_file_from_url(raw_url)
    if path and os.path.isfile(path):
        target_max_size = max_size or 2048
        try:
            with Image.open(path) as img:
                img.load()
                w, h = img.size
                if max(w, h) > target_max_size:
                    img.thumbnail((target_max_size, target_max_size), Image.LANCZOS)
                has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
                if has_alpha:
                    if img.mode != "RGBA":
                        img = img.convert("RGBA")
                    fmt, mime = "PNG", "image/png"
                else:
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    fmt, mime = "JPEG", "image/jpeg"
                buf = BytesIO()
                if fmt == "JPEG":
                    img.save(buf, format=fmt, quality=85, optimize=True)
                else:
                    img.save(buf, format=fmt, optimize=True)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                return f"data:{mime};base64,{encoded}"
        except Exception as e:
            logger.warning(f"reference resize failed, fallback to raw: {e}")
            try:
                with open(path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("ascii")
                return f"data:{content_type_for_path(path)};base64,{encoded}"
            except Exception as read_err:
                logger.warning(f"reference read failed: {read_err}")
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    return ""

def is_image_reference(ref: Any) -> bool:
    if not isinstance(ref, dict):
        return False
    kind = str(ref.get("kind") or "").strip().lower()
    if kind:
        return kind == "image"
    mime = str(ref.get("mime") or "").strip().lower()
    if mime:
        return mime.startswith("image/")
    url = str(ref.get("url") or "").strip()
    if url.lower().startswith("data:image/"):
        return True
    if re.search(r"\.(png|jpe?g|webp|gif|bmp|tiff?)(\?|#|$)", url, re.I):
        return True
    if url.startswith("/output/") or url.startswith("/assets/"):
        path = output_file_from_url(url)
        return bool(path and content_type_for_path(path).startswith("image/"))
    return False

def image_references(refs: Any) -> List[Dict[str, Any]]:
    return [ref for ref in (refs or []) if is_image_reference(ref)]

def media_reference_to_url(value: Any, max_image_size: Optional[int] = None) -> str:
    if not isinstance(value, str) or not value:
        return ""
    if value.startswith("/output/") or value.startswith("/assets/"):
        return reference_to_data_url({"url": value}, max_size=max_image_size)
    return value

def is_private_asset_url(value: str) -> bool:
    return isinstance(value, str) and value.strip().startswith("asset://")

def looks_like_image_media_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith("data:image/"):
        return True
    if text.startswith("asset://"):
        return False
    path = urllib.parse.urlparse(text).path or text
    return bool(re.search(r"\.(png|jpe?g|webp|gif|bmp|tiff)$", path))

def compress_data_url_image(value: str, max_size: int = 1536, jpeg_quality: int = 88) -> str:
    if not isinstance(value, str) or not value.startswith("data:image/") or ";base64," not in value:
        return value
    header, encoded = value.split(";base64,", 1)
    try:
        raw = base64.b64decode(encoded)
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if max_size and max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.LANCZOS)
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            if has_alpha:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                fmt, mime = "PNG", "image/png"
            else:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                fmt, mime = "JPEG", "image/jpeg"
            buf = BytesIO()
            if fmt == "JPEG":
                img.save(buf, format=fmt, quality=jpeg_quality, optimize=True)
            else:
                img.save(buf, format=fmt, optimize=True)
            return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception as e:
        logger.warning(f"data url image compress failed, fallback to raw: {e}")
        return value
