"""Zero-Compute Video Shot Breakdown Router (逐帧拉片).

Extracts storyboard keyframe groups (2x3 grids), key dynamic motion clips,
audio track, and structured reverse shot breakdown scripts using local FFmpeg/FFprobe.
"""
import asyncio
import concurrent.futures
import json
import logging
import math
import os
import re
import shutil
import subprocess
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.media import output_file_from_url
from core.security import safe_download_bytes
from routers.assets import output_path_for, output_url_for

logger = logging.getLogger("infinite_canvas.video_breakdown")

router = APIRouter()

# Concurrency gate: prevent multiple heavy FFmpeg pipelines from saturating CPU
_BREAKDOWN_SEM = asyncio.Semaphore(2)
# Maximum local video file size (500 MB)
_MAX_VIDEO_BYTES = 500 * 1024 * 1024

class VideoBreakdownRequest(BaseModel):
    video_url: str
    extract_storyboard: bool = True
    extract_motion: bool = True
    extract_audio: bool = True
    extract_script: bool = False
    scene_threshold: float = 0.22
    group_size: int = 6
    max_shots: int = 18
    max_motion_clips: int = 4


def _fmt_mmss(seconds: float) -> str:
    sec = max(0, int(round(seconds)))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _fmt_timecode(seconds: float) -> str:
    sec = max(0.0, float(seconds))
    mins = int(sec // 60)
    rem = sec - mins * 60
    return f"{mins:02d}:{rem:04.1f}"


async def _resolve_video_file(video_ref: str) -> str:
    ref = str(video_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="请先上传或连接参考视频")
    local_path = output_file_from_url(ref)
    if local_path and os.path.isfile(local_path):
        _guard_video_path(local_path)
        return local_path
    if ref.startswith(("http://", "https://")):
        data, _ = await safe_download_bytes(ref, timeout=45.0, max_bytes=150 * 1024 * 1024, allow_private=False)
        filename = f"sb_src_{uuid.uuid4().hex[:10]}.mp4"
        dest = output_path_for(filename, "input")
        with open(dest, "wb") as fp:
            fp.write(data)
        return dest
    raise HTTPException(status_code=404, detail="未找到本地视频文件，请重新上传视频后再试")


def _guard_video_path(path: str) -> None:
    """Validate that resolved video path is within allowed directories and within size limit."""
    from routers.assets import ASSETS_DIR, OUTPUT_DIR
    real = os.path.realpath(path)
    allowed_prefixes = [os.path.realpath(d) for d in (ASSETS_DIR, OUTPUT_DIR)]
    if not any(real.startswith(pfx + os.sep) or real == pfx for pfx in allowed_prefixes):
        raise HTTPException(status_code=403, detail="视频路径不在允许的目录范围内")
    try:
        fsize = os.path.getsize(real)
    except OSError:
        raise HTTPException(status_code=404, detail="视频文件不存在或无法读取")
    if fsize > _MAX_VIDEO_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"视频文件过大（{fsize // (1024*1024)}MB），最大支持 {_MAX_VIDEO_BYTES // (1024*1024)}MB",
        )


def probe_video_file(video_path: str) -> Dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise HTTPException(status_code=503, detail="系统未安装 ffprobe，无法解析视频参数")
    proc = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
            "-of", "json",
            video_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=20,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=400, detail="视频文件解析失败，请确认格式有效")
    try:
        info = json.loads(proc.stdout or "{}")
    except Exception:
        info = {}
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    width = 0
    height = 0
    fps = 24.0
    has_audio = False
    for st in streams:
        ctype = str(st.get("codec_type") or "").lower()
        if ctype == "video" and not width:
            width = int(st.get("width") or 0)
            height = int(st.get("height") or 0)
            rate_str = str(st.get("r_frame_rate") or "24/1")
            if "/" in rate_str:
                num, den = rate_str.split("/", 1)
                try:
                    fps = round(float(num) / max(1.0, float(den)), 2)
                except Exception:
                    fps = 24.0
        elif ctype == "audio":
            has_audio = True
    try:
        duration = max(0.1, float(fmt.get("duration") or 0.0))
    except Exception:
        duration = 0.1
    return {
        "duration": round(duration, 2),
        "duration_text": _fmt_mmss(duration),
        "width": width,
        "height": height,
        "fps": fps,
        "has_audio": has_audio,
    }


def detect_video_shots(
    video_path: str,
    duration: float,
    threshold: float = 0.22,
    max_shots: int = 18,
) -> List[Dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="系统未安装 ffmpeg，无法执行逐帧拉片")
    thr = max(0.08, min(0.60, float(threshold or 0.22)))
    vf_expr = f"scale=320:-2,select='gt(scene,{thr:.2f})',showinfo"
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i", video_path,
            "-vf", vf_expr,
            "-an",
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=90,
    )
    raw_cuts = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr or "")]
    min_gap = 0.45
    cuts: List[float] = []
    for t in sorted(raw_cuts):
        if t < 0.35 or t > max(0.4, duration - 0.35):
            continue
        if not cuts or (t - cuts[-1]) >= min_gap:
            cuts.append(t)

    boundaries = [0.0] + cuts + [duration]
    intervals = []
    max_single_span = max(4.2, duration / 4.5)
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        span = e - s
        if span <= 0.15:
            continue
        # 对一镜到底或超长单镜头做均匀子切分，确保分镜拆解饱满
        if span > max_single_span and len(boundaries) <= 6:
            sub_count = max(2, min(6, int(round(span / 2.4))))
            step = span / sub_count
            for k in range(sub_count):
                intervals.append((s + k * step, s + (k + 1) * step))
        else:
            intervals.append((s, e))

    if not intervals:
        intervals = [(0.0, duration)]

    cap = max(3, min(36, int(max_shots or 18)))
    if len(intervals) > cap:
        # 均匀抽样保留全片叙事结构
        picked = []
        for idx in range(cap):
            pos = int(round(idx * (len(intervals) - 1) / max(1, cap - 1)))
            picked.append(intervals[pos])
        intervals = picked

    shots: List[Dict[str, Any]] = []
    for idx, (s, e) in enumerate(intervals, 1):
        dur = max(0.1, e - s)
        mid = s + dur * 0.5
        shots.append({
            "shot_index": idx,
            "start": round(s, 2),
            "end": round(e, 2),
            "duration": round(dur, 2),
            "mid": round(mid, 2),
            "timecode": f"{_fmt_timecode(s)} - {_fmt_timecode(e)}",
            "badge": f"#{idx:02d} · {_fmt_timecode(s)}",
        })
    return shots


def _group_pacing_tag(group_shots: List[Dict[str, Any]]) -> str:
    if not group_shots:
        return "空间展开 · 视线流动"
    avg_dur = sum(s["duration"] for s in group_shots) / len(group_shots)
    if avg_dur < 1.1:
        return "高频快切 · 动态冲击"
    if avg_dur < 2.2:
        return "空间展开 · 视线流动-缓推"
    return "景别递进 · 稳定叙事镜头"


def _run_breakdown_sync(video_path: str, req: VideoBreakdownRequest) -> Dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="系统未安装 ffmpeg，无法执行逐帧拉片")

    meta = probe_video_file(video_path)
    duration = meta["duration"]
    shots = detect_video_shots(
        video_path,
        duration=duration,
        threshold=req.scene_threshold,
        max_shots=req.max_shots,
    )
    batch_id = uuid.uuid4().hex[:8]
    aspect_w = max(1, int(meta.get("width") or 16))
    aspect_h = max(1, int(meta.get("height") or 9))

    storyboard_groups: List[Dict[str, Any]] = []
    if req.extract_storyboard:
        def _extract_one_frame(s):
            fname = f"sb_{batch_id}_s{s['shot_index']:02d}.jpg"
            out_path = output_path_for(fname, "output")
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-ss", f"{s['mid']:.3f}",
                    "-i", video_path,
                    "-frames:v", "1",
                    "-vf", "scale='min(1280,iw)':-2",
                    "-q:v", "2",
                    out_path,
                ],
                capture_output=True,
                timeout=20,
            )
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return {
                    **s,
                    "url": output_url_for(fname, "output"),
                    "name": f"镜头{s['shot_index']:02d}_{_fmt_mmss(s['start'])}.jpg",
                    "w": aspect_w,
                    "h": aspect_h,
                }
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_extract_one_frame, shots))
        extracted_shots = [r for r in results if r is not None]

        gsize = max(2, min(12, int(req.group_size or 6)))
        cols = 2
        for g_idx in range(0, len(extracted_shots), gsize):
            chunk = extracted_shots[g_idx:g_idx + gsize]
            group_num = (g_idx // gsize) + 1
            rows = max(1, math.ceil(len(chunk) / cols))
            tag = _group_pacing_tag(chunk)
            storyboard_groups.append({
                "group_index": group_num,
                "title": f"分镜组{group_num:02d} | {len(chunk)}个镜头 · {tag}",
                "cols": cols,
                "rows": rows,
                "items": [
                    {
                        **item,
                        "row": idx // cols,
                        "col": idx % cols,
                    }
                    for idx, item in enumerate(chunk)
                ],
            })

    motion_group: Optional[Dict[str, Any]] = None
    if req.extract_motion and shots:
        # 优选时长在 0.8s ~ 4.5s 之间的代表性动态镜头，覆盖前/中/后段
        candidates = [s for s in shots if s["duration"] >= 0.65] or shots[:]
        max_clips = max(1, min(6, int(req.max_motion_clips or 4)))
        picked_clips: List[Dict[str, Any]] = []
        if len(candidates) <= max_clips:
            picked_clips = candidates
        else:
            for i in range(max_clips):
                pos = int(round(i * (len(candidates) - 1) / max(1, max_clips - 1)))
                picked_clips.append(candidates[pos])

        clip_items: List[Dict[str, Any]] = []
        for c_idx, s in enumerate(picked_clips, 1):
            clip_dur = min(4.0, max(0.8, s["duration"]))
            fname = f"sb_{batch_id}_m{c_idx:02d}.mp4"
            out_path = output_path_for(fname, "output")
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-y",
                    "-ss", f"{s['start']:.3f}",
                    "-t", f"{clip_dur:.3f}",
                    "-i", video_path,
                    "-vf", "scale='min(960,iw)':-2",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    "-an",
                    "-movflags", "+faststart",
                    out_path,
                ],
                capture_output=True,
                timeout=35,
            )
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                clip_items.append({
                    **s,
                    "duration": round(clip_dur, 2),
                    "url": output_url_for(fname, "output"),
                    "name": f"运镜动作{c_idx:02d}_镜头{s['shot_index']:02d}.mp4",
                    "badge": f"动态{c_idx:02d} · {clip_dur:.1f}s",
                    "w": aspect_w,
                    "h": aspect_h,
                    "row": (c_idx - 1) // 2,
                    "col": (c_idx - 1) % 2,
                })
        if clip_items:
            motion_group = {
                "title": f"运镜动作 | {len(clip_items)}段关键动态",
                "cols": 2,
                "rows": max(1, math.ceil(len(clip_items) / 2)),
                "items": clip_items,
            }

    audio_info: Optional[Dict[str, Any]] = None
    if req.extract_audio and meta.get("has_audio"):
        fname = f"sb_{batch_id}_audio.mp3"
        out_path = output_path_for(fname, "output")
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", video_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-q:a", "2",
                out_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            audio_info = {
                "url": output_url_for(fname, "output"),
                "name": f"音频参考 ({meta['duration_text']}).mp3",
                "duration": duration,
                "duration_text": meta["duration_text"],
            }

    script_text = ""
    if req.extract_script:
        lines = [
            f"运镜构图参考 @视频素材（总时长 {meta['duration_text']} · {meta['width']}×{meta['height']} · 共 {len(shots)} 个分镜）",
            "分镜时间轴拆解：",
        ]
        for s in shots[:12]:
            lines.append(f"- 镜头 {s['shot_index']:02d} [{s['timecode']}]（{s['duration']:.1f}s）：保持原片景别、机位运动与光影节奏")
        lines.append("场景与主体：请结合上方分镜宫格图与运镜动作片段，复刻镜头调度与画面张力。")
        script_text = "\n".join(lines)

    return {
        "ok": True,
        "video_meta": {
            **meta,
            "shot_count": len(shots),
        },
        "storyboard_groups": storyboard_groups,
        "motion_group": motion_group,
        "audio": audio_info,
        "script_text": script_text,
    }


@router.get("/api/video/probe")
async def api_video_probe(video_url: str = Query(..., alias="url")) -> Dict[str, Any]:
    video_path = await _resolve_video_file(video_url)
    meta = await asyncio.to_thread(probe_video_file, video_path)
    return {"ok": True, **meta}


@router.post("/api/video/breakdown")
async def api_video_breakdown(req: VideoBreakdownRequest) -> Dict[str, Any]:
    if not (req.extract_storyboard or req.extract_motion or req.extract_audio or req.extract_script):
        raise HTTPException(status_code=400, detail="请至少选择一个拆解维度（分镜 / 动态 / 音乐）")
    video_path = await _resolve_video_file(req.video_url)
    async with _BREAKDOWN_SEM:
        return await asyncio.to_thread(_run_breakdown_sync, video_path, req)
