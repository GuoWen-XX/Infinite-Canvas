"""Unit tests for core/media.py.

Tests reference normalization, image/video discrimination, JPG conversion,
base64 encoding/compression, and asset URL inspection.
"""

import os
import uuid
import base64
from io import BytesIO
import pytest
from PIL import Image

from core.media import (
    is_image_reference_value,
    is_video_reference_value,
    convert_output_to_jpg,
    reference_to_data_url,
    is_image_reference,
    image_references,
    media_reference_to_url,
    is_private_asset_url,
    looks_like_image_media_url,
    compress_data_url_image,
)
from routers.assets import OUTPUT_DIR, ASSETS_DIR


@pytest.fixture
def temp_output_image():
    """Create a temporary PNG image in OUTPUT_DIR and cleanup afterwards."""
    filename = f"test_media_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
    img.save(filepath, "PNG")
    rel_url = f"/output/{filename}"

    yield filepath, rel_url

    # Cleanup
    for ext in (".png", ".jpg", ".jpeg"):
        cleanup_path = os.path.splitext(filepath)[0] + ext
        if os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except OSError:
                pass


@pytest.fixture
def temp_output_video():
    """Create a temporary fake video file in OUTPUT_DIR and cleanup afterwards."""
    filename = f"test_video_{uuid.uuid4().hex[:8]}.mp4"
    filepath = os.path.join(OUTPUT_DIR, filename)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(b"\x00\x00\x00 ftypisom")  # Minimal MP4 header
    rel_url = f"/output/{filename}"

    yield filepath, rel_url

    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass


@pytest.fixture
def temp_assets_image():
    """Create a temporary PNG image in ASSETS_DIR and cleanup afterwards."""
    filename = f"test_asset_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(ASSETS_DIR, filename)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    img = Image.new("RGB", (60, 60), (0, 255, 0))
    img.save(filepath, "PNG")
    rel_url = f"/assets/{filename}"

    yield filepath, rel_url

    for ext in (".png", ".jpg", ".jpeg"):
        cleanup_path = os.path.splitext(filepath)[0] + ext
        if os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except OSError:
                pass


# =========================================================================
# 1. is_image_reference_value
# =========================================================================

class TestIsImageReferenceValue:
    def test_non_string_and_empty(self):
        assert is_image_reference_value(None) is False
        assert is_image_reference_value("") is False
        assert is_image_reference_value(12345) is False
        assert is_image_reference_value([]) is False
        assert is_image_reference_value({}) is False

    def test_data_image_url(self):
        assert is_image_reference_value("data:image/png;base64,iVBORw0KGgo=") is True
        assert is_image_reference_value("data:image/jpeg;base64,/9j/4AAQSkZJRg==") is True
        assert is_image_reference_value("data:image/webp;base64,UklGR===") is True

    def test_data_non_image_url(self):
        assert is_image_reference_value("data:video/mp4;base64,AAAA") is False
        assert is_image_reference_value("data:text/plain;charset=utf-8,hello") is False
        assert is_image_reference_value("data:application/json,{}") is False

    def test_output_and_assets_image_files(self, temp_output_image, temp_assets_image):
        _, output_url = temp_output_image
        _, assets_url = temp_assets_image
        assert is_image_reference_value(output_url) is True
        assert is_image_reference_value(assets_url) is True

    def test_output_video_file(self, temp_output_video):
        _, output_video_url = temp_output_video
        assert is_image_reference_value(output_video_url) is False

    def test_output_non_existent_file(self):
        assert is_image_reference_value("/output/non_existent_file_9999.png") is False
        assert is_image_reference_value("/assets/non_existent_file_9999.png") is False

    def test_external_urls(self):
        assert is_image_reference_value("https://example.com/photo.png") is True
        assert is_image_reference_value("https://example.com/photo.jpg?query=1") is True
        assert is_image_reference_value("https://example.com/photo.webp#anchor") is True
        # Video extensions
        assert is_image_reference_value("https://example.com/clip.mp4") is False
        assert is_image_reference_value("https://example.com/clip.webm?token=xyz") is False
        assert is_image_reference_value("https://example.com/clip.mov") is False
        assert is_image_reference_value("https://example.com/clip.m4v") is False
        assert is_image_reference_value("https://example.com/clip.avi") is False
        assert is_image_reference_value("https://example.com/clip.mkv") is False
        # Audio extensions
        assert is_image_reference_value("https://example.com/song.mp3") is False
        assert is_image_reference_value("https://example.com/track.wav") is False
        assert is_image_reference_value("https://example.com/audio.m4a") is False
        assert is_image_reference_value("https://example.com/sound.aac") is False
        assert is_image_reference_value("https://example.com/audio.ogg") is False
        assert is_image_reference_value("https://example.com/lossless.flac") is False


# =========================================================================
# 2. is_video_reference_value
# =========================================================================

class TestIsVideoReferenceValue:
    def test_non_string_and_empty(self):
        assert is_video_reference_value(None) is False
        assert is_video_reference_value("") is False
        assert is_video_reference_value(999) is False
        assert is_video_reference_value([]) is False

    def test_data_video_url(self):
        assert is_video_reference_value("data:video/mp4;base64,AAAA") is True
        assert is_video_reference_value("data:video/webm;base64,AAAA") is True
        assert is_video_reference_value("data:video/quicktime;base64,AAAA") is True

    def test_data_non_video_url(self):
        assert is_video_reference_value("data:image/png;base64,iVBORw0KGgo=") is False
        assert is_video_reference_value("data:text/plain,hello") is False

    def test_output_video_file(self, temp_output_video):
        _, output_video_url = temp_output_video
        assert is_video_reference_value(output_video_url) is True

    def test_output_image_file(self, temp_output_image):
        _, output_image_url = temp_output_image
        assert is_video_reference_value(output_image_url) is False

    def test_output_non_existent_file(self):
        assert is_video_reference_value("/output/non_existent_file_9999.mp4") is False

    def test_video_extensions(self):
        assert is_video_reference_value("https://example.com/video.mp4") is True
        assert is_video_reference_value("https://example.com/video.webm") is True
        assert is_video_reference_value("https://example.com/video.mov") is True
        assert is_video_reference_value("https://example.com/video.m4v") is True
        assert is_video_reference_value("https://example.com/video.avi") is True
        assert is_video_reference_value("https://example.com/video.mkv") is True
        assert is_video_reference_value("https://example.com/video.mp4?auth=123") is True

    def test_non_video_extensions(self):
        assert is_video_reference_value("https://example.com/photo.png") is False
        assert is_video_reference_value("https://example.com/photo.jpg") is False
        assert is_video_reference_value("https://example.com/document.pdf") is False
        assert is_video_reference_value("https://example.com/song.mp3") is False


# =========================================================================
# 3. convert_output_to_jpg
# =========================================================================

class TestConvertOutputToJpg:
    def test_non_existent_file(self):
        url = "/output/does_not_exist_xyz.png"
        assert convert_output_to_jpg(url) == url

    def test_external_url(self):
        url = "https://example.com/image.png"
        assert convert_output_to_jpg(url) == url

    def test_already_jpg(self):
        filename = f"test_already_jpg_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(OUTPUT_DIR, filename)
        img = Image.new("RGB", (50, 50), (100, 100, 100))
        img.save(filepath, "JPEG")
        rel_url = f"/output/{filename}"

        try:
            assert convert_output_to_jpg(rel_url) == rel_url
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_rgba_png_conversion(self, temp_output_image):
        _, output_url = temp_output_image
        converted_url = convert_output_to_jpg(output_url, quality=90)

        assert converted_url.startswith("/output/")
        assert converted_url.endswith(".jpg")

        # Verify that output jpg file exists and is RGB
        jpg_filename = converted_url.split("/output/")[1]
        jpg_path = os.path.join(OUTPUT_DIR, jpg_filename)
        assert os.path.exists(jpg_path)

        with Image.open(jpg_path) as converted_img:
            assert converted_img.format == "JPEG"
            assert converted_img.mode == "RGB"

    def test_assets_conversion(self, temp_assets_image):
        _, assets_url = temp_assets_image
        converted_url = convert_output_to_jpg(assets_url)

        assert converted_url.startswith("/assets/")
        assert converted_url.endswith(".jpg")

        jpg_filename = converted_url.split("/assets/")[1]
        jpg_path = os.path.join(ASSETS_DIR, jpg_filename)
        assert os.path.exists(jpg_path)

    def test_palette_image_with_transparency(self):
        filename = f"test_palette_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(OUTPUT_DIR, filename)
        img = Image.new("RGBA", (40, 40), (255, 0, 0, 0))
        img_p = img.convert("P")
        img_p.save(filepath, "PNG", transparency=0)
        rel_url = f"/output/{filename}"

        try:
            converted_url = convert_output_to_jpg(rel_url)
            assert converted_url.endswith(".jpg")
        finally:
            for ext in (".png", ".jpg"):
                p = os.path.splitext(filepath)[0] + ext
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    def test_corrupt_file_returns_original_url(self):
        filename = f"test_corrupt_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(b"not an image content")
        rel_url = f"/output/{filename}"

        try:
            assert convert_output_to_jpg(rel_url) == rel_url
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)


# =========================================================================
# 4. reference_to_data_url and compress_data_url_image
# =========================================================================

class TestDataUrlHelpers:
    def test_reference_to_data_url_empty_and_external(self):
        assert reference_to_data_url({}) == ""
        assert reference_to_data_url({"url": ""}) == ""
        assert reference_to_data_url({"url": "https://example.com/pic.png"}) == "https://example.com/pic.png"
        assert reference_to_data_url({"url": "http://example.com/pic.png"}) == "http://example.com/pic.png"

    def test_reference_to_data_url_local_file(self, temp_output_image):
        _, output_url = temp_output_image
        data_url = reference_to_data_url({"url": output_url}, max_size=50)
        assert data_url.startswith("data:image/")
        assert ";base64," in data_url

        # Decode and verify thumbnail sizing
        _, encoded = data_url.split(";base64,", 1)
        raw_bytes = base64.b64decode(encoded)
        with Image.open(BytesIO(raw_bytes)) as decoded_img:
            assert max(decoded_img.size) <= 50

    def test_compress_data_url_image(self):
        img = Image.new("RGB", (3000, 2000), (200, 100, 50))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=95)
        raw_data_url = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"

        compressed = compress_data_url_image(raw_data_url, max_size=1000, jpeg_quality=75)
        assert compressed.startswith("data:image/jpeg;base64,")

        _, encoded = compressed.split(";base64,", 1)
        with Image.open(BytesIO(base64.b64decode(encoded))) as res:
            assert max(res.size) <= 1000

    def test_compress_data_url_invalid(self):
        assert compress_data_url_image("invalid") == "invalid"
        assert compress_data_url_image("data:video/mp4;base64,abc") == "data:video/mp4;base64,abc"


# =========================================================================
# 5. Reference inspection and classification helpers
# =========================================================================

class TestMediaReferenceClassification:
    def test_is_image_reference(self, temp_output_image):
        _, output_url = temp_output_image
        assert is_image_reference("not-a-dict") is False
        assert is_image_reference({"kind": "image"}) is True
        assert is_image_reference({"kind": "video"}) is False
        assert is_image_reference({"mime": "image/jpeg"}) is True
        assert is_image_reference({"mime": "video/mp4"}) is False
        assert is_image_reference({"url": "data:image/png;base64,123"}) is True
        assert is_image_reference({"url": "https://example.com/test.webp"}) is True
        assert is_image_reference({"url": "https://example.com/test.mp4"}) is False
        assert is_image_reference({"url": output_url}) is True
        assert is_image_reference({"url": "/output/unknown_missing"}) is False
        assert is_image_reference({"url": "/output/unknown_missing.bin"}) is False

    def test_image_references(self, temp_output_image):
        _, output_url = temp_output_image
        items = [
            {"kind": "image"},
            {"kind": "video"},
            "invalid",
            {"url": output_url},
            {"mime": "image/png"},
        ]
        result = image_references(items)
        assert len(result) == 3
        assert result[0] == {"kind": "image"}
        assert result[1] == {"url": output_url}
        assert result[2] == {"mime": "image/png"}

    def test_media_reference_to_url(self, temp_output_image):
        _, output_url = temp_output_image
        assert media_reference_to_url("") == ""
        assert media_reference_to_url(None) == ""
        assert media_reference_to_url("https://example.com/image.png") == "https://example.com/image.png"

        converted = media_reference_to_url(output_url, max_image_size=100)
        assert converted.startswith("data:image/")

    def test_is_private_asset_url(self):
        assert is_private_asset_url("asset://library/model.ckpt") is True
        assert is_private_asset_url("  asset://test  ") is True
        assert is_private_asset_url("https://example.com") is False
        assert is_private_asset_url("/output/image.png") is False
        assert is_private_asset_url(None) is False

    def test_looks_like_image_media_url(self):
        assert looks_like_image_media_url("") is False
        assert looks_like_image_media_url(None) is False
        assert looks_like_image_media_url("data:image/png;base64,123") is True
        assert looks_like_image_media_url("asset://test") is False
        assert looks_like_image_media_url("https://example.com/image.png") is True
        assert looks_like_image_media_url("https://example.com/image.jpeg") is True
        assert looks_like_image_media_url("https://example.com/image.webp") is True
        assert looks_like_image_media_url("https://example.com/image.gif") is True
        assert looks_like_image_media_url("https://example.com/image.bmp") is True
        assert looks_like_image_media_url("https://example.com/image.tiff") is True
        assert looks_like_image_media_url("https://example.com/video.mp4") is False
