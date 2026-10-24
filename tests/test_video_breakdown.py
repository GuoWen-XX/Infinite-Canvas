"""Tests for Zero-Compute Video Shot Breakdown Router (routers/video_breakdown.py)."""
import os
import shutil
import subprocess
import pytest
from fastapi.testclient import TestClient

from main import app
from routers.assets import output_path_for, output_url_for


@pytest.fixture
def sample_video_url():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed")
    fname = "test_sb_sample.mp4"
    out_path = output_path_for(fname, "input")
    # Generate a 3-second synthetic 3-scene video + sine audio track
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=1",
            "-f", "lavfi", "-i", "color=c=green:s=320x180:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map", "[v]", "-map", "3:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            out_path,
        ],
        check=True,
        timeout=20,
    )
    yield output_url_for(fname, "input")
    try:
        if os.path.exists(out_path):
            os.remove(out_path)
    except OSError:
        pass


def test_video_probe_and_breakdown(sample_video_url):
    client = TestClient(app)

    # 1. Probe metadata
    r_probe = client.get("/api/video/probe", params={"url": sample_video_url})
    assert r_probe.status_code == 200
    probe_data = r_probe.json()
    assert probe_data["ok"] is True
    assert probe_data["width"] == 320
    assert probe_data["height"] == 180
    assert probe_data["has_audio"] is True

    # 2. Full breakdown (storyboard + motion + audio + script)
    r_bd = client.post(
        "/api/video/breakdown",
        json={
            "video_url": sample_video_url,
            "extract_storyboard": True,
            "extract_motion": True,
            "extract_audio": True,
            "extract_script": True,
            "scene_threshold": 0.18,
            "group_size": 6,
            "max_shots": 12,
            "max_motion_clips": 3,
        },
    )
    assert r_bd.status_code == 200
    data = r_bd.json()
    assert data["ok"] is True
    assert len(data["storyboard_groups"]) >= 1
    first_group = data["storyboard_groups"][0]
    assert first_group["cols"] == 2
    assert len(first_group["items"]) >= 2
    assert data["motion_group"] is not None
    assert len(data["motion_group"]["items"]) >= 1
    assert data["audio"] is not None
    assert data["audio"]["url"].endswith(".mp3")
    assert "运镜构图参考" in data["script_text"]

    # Clean up generated output files
    from core.media import output_file_from_url
    urls = [data["audio"]["url"]]
    for grp in data["storyboard_groups"]:
        urls.extend(item["url"] for item in grp["items"])
    for item in data["motion_group"]["items"]:
        urls.append(item["url"])
    for u in urls:
        p = output_file_from_url(u)
        if p and os.path.exists(p):
            os.remove(p)


def test_breakdown_returns_503_when_ffmpeg_missing(monkeypatch):
    """When ffmpeg/ffprobe is not installed, the API should return HTTP 503."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    client = TestClient(app)

    # probe endpoint
    r = client.get("/api/video/probe", params={"url": "/output/fake.mp4"})
    assert r.status_code in (503, 404)  # 503 if path resolves, 404 if not

    # breakdown endpoint
    r = client.post(
        "/api/video/breakdown",
        json={
            "video_url": "/output/fake.mp4",
            "extract_storyboard": True,
        },
    )
    assert r.status_code in (503, 404)
    if r.status_code == 503:
        assert "ffmpeg" in r.json().get("detail", "").lower() or "ffprobe" in r.json().get("detail", "").lower()


def test_breakdown_rejects_empty_dimensions():
    """When no extraction dimension is selected, the API should return HTTP 400."""
    client = TestClient(app)
    r = client.post(
        "/api/video/breakdown",
        json={
            "video_url": "/output/fake.mp4",
            "extract_storyboard": False,
            "extract_motion": False,
            "extract_audio": False,
            "extract_script": False,
        },
    )
    assert r.status_code == 400
