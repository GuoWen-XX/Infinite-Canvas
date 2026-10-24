"""Prompt Libraries and Templates Router for Infinite-Canvas.

Decoupled from monolithic main.py to provide clean, modular, and thread-safe
prompt template parsing, markdown presets loading, and prompt library CRUD operations.
"""

import os
import re
import json
import uuid
import time
import logging
from threading import RLock
from typing import Dict, Any, List, Optional, Set

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("infinite_canvas.prompts")

router = APIRouter(tags=["prompts"])

# ===== 目录与路径常量 =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATIC_DIR = os.path.join(BASE_DIR, "static")

PROMPT_LIBRARY_PATH = os.path.join(DATA_DIR, "prompt_libraries.json")
STATIC_PROMPT_TEMPLATE_MD = os.path.join(STATIC_DIR, "system-prompts", "infinite-canvas-prompt-templates.md")
PROMPT_TEMPLATE_PATHS = [STATIC_PROMPT_TEMPLATE_MD]

PROMPT_LOCK = RLock()

PROMPT_BUILTIN_CATEGORY_IDS: Set[str] = {"view", "storyboard", "character", "product", "lighting", "custom"}

PROMPT_TEMPLATE_EN: Dict[str, Dict[str, str]] = {
    "多机位九宫格": {
        "name": "9-Angle Multi-Camera Grid",
        "scene": "Show the same subject or scene from 9 camera angles for character turnarounds, product views, or space scouting.",
    },
    "多机位九宫格4K": {
        "name": "9-Angle Multi-Camera Grid 4K",
        "scene": "A high-resolution 9-angle reference sheet for print-grade output, large displays, and fine material study.",
    },
    "剧情推演四宫格": {
        "name": "4-Panel Story Progression",
        "scene": "Preview four consecutive story beats or emotional stages for storyboard planning and narrative rhythm tests.",
    },
    "角色脸部三视图": {
        "name": "Character Face 3-View Sheet",
        "scene": "Front, side, and three-quarter face references for Actor ID locking and expression consistency.",
    },
    "产品三视图": {
        "name": "Product 3-View Sheet",
        "scene": "Front, side, and top product views for industrial design, ecommerce detail pages, and technical documents.",
    },
    "25宫格连贯分镜": {
        "name": "25-Panel Continuous Storyboard",
        "scene": "A full 5x5 storyboard for continuous scene or action flow, useful for film previews and motion continuity tests.",
    },
    "电影级光影校正": {
        "name": "Cinematic Lighting Comparison",
        "scene": "Compare the same subject or scene under different lighting conditions for mood, color, and lighting choices.",
    },
    "角色设定参考表（胸口特写+全身三视图）": {
        "name": "Character Reference Sheet: Portrait + Full-Body Views",
        "scene": "A consistency reference combining a face anchor and full-body front, side, and back views for Actor ID and costume lock.",
    },
    "6种基础表情胸像（2×3六宫格）": {
        "name": "6 Basic Expression Busts",
        "scene": "Six basic expressions of the same character for expression consistency, emotion baselines, and Seedance Talk-to-Edit reference.",
    },
    "360全景图": {
        "name": "360 Panorama VR Image",
        "scene": "Generate a seamless 360-degree VR panorama with continuous left and right edges and natural pole transitions.",
    },
}

# ===== Pydantic 请求模型 =====

class PromptLibraryRequest(BaseModel):
    name: str = "提示词库"


class PromptLibraryItemRequest(BaseModel):
    library_id: str = ""
    item_id: str = ""
    name: str = "提示词"
    category: str = "custom"
    positive: str = ""
    negative: str = ""
    scene: str = ""


class PromptLibraryBatchDeleteRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)


class PromptLibraryCategoryRequest(BaseModel):
    name: str = "新分组"
    library_id: str = ""


# ===== 辅助工具函数 =====

def now_ms() -> int:
    return int(time.time() * 1000)


def sanitize_asset_name(name: Any, fallback: str = "asset") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(name or fallback)).strip()
    return cleaned or fallback


def prompt_template_markdown_path() -> str:
    for path in PROMPT_TEMPLATE_PATHS:
        if os.path.exists(path):
            return path
    return ""


def prompt_template_category(name: str, scene: str) -> str:
    text = f"{name} {scene}"
    if any(k in text for k in ["光影", "灯光", "光效", "电影级"]):
        return "lighting"
    if any(k in text for k in ["视角", "全景", "VR", "镜头", "俯拍", "仰拍", "景别", "构图", "透视"]):
        return "view"
    if any(k in text for k in ["角色", "脸部", "表情", "Actor", "服装"]):
        return "character"
    if any(k in name for k in ["产品", "电商", "工业"]):
        return "product"
    return "storyboard"


def extract_prompt_template_section(block: str, title: str) -> str:
    pattern = rf"###\s*{re.escape(title)}\s*\n(?P<body>.*?)(?=\n###\s+|\Z)"
    match = re.search(pattern, block, re.S)
    if not match:
        return ""
    body = match.group("body").strip()
    fence = re.search(r"```(?:\w+)?\s*\n(?P<code>.*?)\n```", body, re.S)
    return (fence.group("code") if fence else body).strip()


def parse_prompt_template_markdown(text: str) -> List[Dict[str, Any]]:
    templates: List[Dict[str, Any]] = []
    matches = list(re.finditer(r"^##\s*预设\s*(\d+)\s*[：:]\s*(.+?)\s*$", text, re.M))
    for index, match in enumerate(matches):
        number = match.group(1).strip()
        name = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        scene = extract_prompt_template_section(block, "适用场景")
        positive = extract_prompt_template_section(block, "正向提示词")
        negative = extract_prompt_template_section(block, "负向提示词")
        params_raw = extract_prompt_template_section(block, "平台参数建议")
        params: Dict[str, str] = {}
        for line in params_raw.splitlines():
            item = re.match(r"[-*]\s*\*\*(.+?)\*\*\s*[：:]\s*(.+)", line.strip())
            if item:
                params[item.group(1).strip()] = item.group(2).strip()
        if not positive:
            continue
        templates.append({
            "id": f"builtin_md_{number}",
            "number": number,
            "name": name,
            "name_en": PROMPT_TEMPLATE_EN.get(name, {}).get("name", name),
            "category": prompt_template_category(name, scene),
            "scene": scene,
            "scene_en": PROMPT_TEMPLATE_EN.get(name, {}).get("scene", scene),
            "positive": positive,
            "negative": negative,
            "params": params,
            "builtin": True,
        })
    return templates


def builtin_prompt_templates() -> List[Dict[str, Any]]:
    try:
        template_path = prompt_template_markdown_path()
        if not template_path:
            return []
        with open(template_path, "r", encoding="utf-8") as f:
            return parse_prompt_template_markdown(f.read())
    except Exception as e:
        logger.warning(f"读取提示词模板失败: {e}")
        return []


def defaultPromptTemplateCategories() -> List[Dict[str, str]]:
    return [
        {"id": "view", "name": "视角"},
        {"id": "storyboard", "name": "分镜"},
        {"id": "character", "name": "角色"},
        {"id": "product", "name": "产品"},
        {"id": "lighting", "name": "光影"},
        {"id": "custom", "name": "我的"},
    ]


def normalize_prompt_category_id(category: Any = "custom") -> str:
    raw = str(category or "custom").strip()
    if not raw:
        return "custom"
    if raw.lower() in {"mine", "my", "personal"}:
        return "custom"
    cleaned = re.sub(r'[\/\\:*?"<>|]+', "_", raw).strip()[:40]
    return cleaned or "custom"


def normalize_prompt_template_categories(*category_lists, include_defaults: bool = True) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def add_category(category: Any) -> None:
        if not isinstance(category, dict):
            return
        cat_id = normalize_prompt_category_id(category.get("id") or category.get("name") or "custom")
        if cat_id in seen:
            return
        seen.add(cat_id)
        name = sanitize_asset_name(category.get("name") or cat_id, cat_id)
        normalized.append({"id": cat_id, "name": name})

    for categories in category_lists:
        if isinstance(categories, list):
            for category in categories:
                add_category(category)
    if include_defaults:
        for category in defaultPromptTemplateCategories():
            add_category(category)
    return normalized


def normalize_prompt_library_item(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    name = sanitize_asset_name(item.get("name") or "提示词", "提示词")
    positive = str(item.get("positive") or item.get("text") or "").strip()
    return {
        "id": re.sub(r"[^A-Za-z0-9_-]+", "_", str(item.get("id") or item.get("item_id") or f"tpl_{uuid.uuid4().hex[:12]}"))[:60],
        "name": name,
        "category": normalize_prompt_category_id(item.get("category") or "custom"),
        "scene": str(item.get("scene") or "").strip()[:500],
        "positive": positive,
        "negative": str(item.get("negative") or "").strip(),
        "params": item.get("params") if isinstance(item.get("params"), dict) else {},
        "created_at": int(item.get("created_at") or now_ms()),
        "updated_at": int(item.get("updated_at") or item.get("created_at") or now_ms()),
    }


def seed_system_prompt_library() -> Dict[str, Any]:
    return {
        "id": "system",
        "name": "系统提示词库",
        "type": "prompt",
        "items": builtin_prompt_templates(),
        "categories": defaultPromptTemplateCategories(),
    }


def default_prompt_libraries() -> Dict[str, Any]:
    return {
        "active_library_id": "system",
        "libraries": [seed_system_prompt_library()],
        "updated_at": now_ms(),
    }


def normalize_prompt_libraries(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = default_prompt_libraries()
    raw_libraries = data.get("libraries") if isinstance(data.get("libraries"), list) else []
    raw_libraries = [lib for lib in raw_libraries if isinstance(lib, dict)]
    if not any(lib.get("id") == "system" for lib in raw_libraries):
        raw_libraries = [seed_system_prompt_library()] + raw_libraries
    libraries: List[Dict[str, Any]] = []
    seen_lib_ids: Set[str] = set()
    for raw in raw_libraries:
        is_system = raw.get("id") == "system"
        if is_system:
            lib_id = "system"
        else:
            lib_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(raw.get("id") or f"lib_{uuid.uuid4().hex[:12]}"))[:60] or f"lib_{uuid.uuid4().hex[:12]}"
        if lib_id in seen_lib_ids:
            continue
        seen_lib_ids.add(lib_id)
        items: List[Dict[str, Any]] = []
        seen_items: Set[str] = set()
        for raw_item in (raw.get("items") if isinstance(raw.get("items"), list) else []):
            if not isinstance(raw_item, dict):
                continue
            item = normalize_prompt_library_item(raw_item)
            item_id = item.get("id") or f"tpl_{uuid.uuid4().hex[:12]}"
            if item_id in seen_items:
                continue
            seen_items.add(item_id)
            items.append(item)
        default_name = "系统提示词库" if is_system else "提示词库"
        raw_categories = raw.get("categories") if isinstance(raw.get("categories"), list) else []
        if not is_system:
            raw_categories = [c for c in raw_categories if isinstance(c, dict) and normalize_prompt_category_id(c.get("id") or c.get("name") or "") not in PROMPT_BUILTIN_CATEGORY_IDS]
        libraries.append({
            "id": lib_id,
            "name": sanitize_asset_name(raw.get("name") or default_name, default_name),
            "type": "prompt",
            "readonly": False,
            "system": is_system,
            "categories": normalize_prompt_template_categories(raw_categories, include_defaults=is_system),
            "items": items,
        })
    active = str(data.get("active_library_id") or "system")
    if not any(lib["id"] == active for lib in libraries):
        active = "system" if any(lib["id"] == "system" for lib in libraries) else (libraries[0]["id"] if libraries else "system")
    return {"active_library_id": active, "libraries": libraries, "updated_at": int(data.get("updated_at") or now_ms())}


def load_prompt_libraries() -> Dict[str, Any]:
    with PROMPT_LOCK:
        if not os.path.exists(PROMPT_LIBRARY_PATH):
            data = default_prompt_libraries()
            return save_prompt_libraries(data)
        try:
            with open(PROMPT_LIBRARY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = default_prompt_libraries()
        if not isinstance(data, dict):
            data = default_prompt_libraries()
        normalized = normalize_prompt_libraries(data)
        if normalized.get("active_library_id") != data.get("active_library_id") or normalized.get("libraries") != data.get("libraries"):
            return save_prompt_libraries(normalized)
        return normalized


def save_prompt_libraries(data: Any) -> Dict[str, Any]:
    with PROMPT_LOCK:
        data = normalize_prompt_libraries(data)
        data["updated_at"] = now_ms()
        os.makedirs(DATA_DIR, exist_ok=True)
        temp_path = f"{PROMPT_LIBRARY_PATH}.tmp_{uuid.uuid4().hex[:8]}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, PROMPT_LIBRARY_PATH)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise
        return data


def public_prompt_libraries(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = normalize_prompt_libraries(data or load_prompt_libraries())
    return {
        "active_library_id": data.get("active_library_id") or (data.get("libraries") or [{}])[0].get("id") or "system",
        "libraries": data.get("libraries") or [],
        "updated_at": data.get("updated_at") or now_ms(),
    }


def find_prompt_library(data: Any, library_id: str = "") -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    libraries = data.get("libraries") if isinstance(data.get("libraries"), list) else []
    library_id = str(library_id or data.get("active_library_id") or "").strip()
    return next((item for item in libraries if item.get("id") == library_id), None) or (libraries[0] if libraries else None)


# ===== 路由端点 =====

@router.get("/api/smart-canvas/prompt-templates")
async def smart_canvas_prompt_templates():
    try:
        template_path = prompt_template_markdown_path()
        source = os.path.relpath(template_path, BASE_DIR).replace("\\", "/") if template_path else ""
        return {"templates": builtin_prompt_templates(), "source": source}
    except Exception as e:
        logger.warning(f"读取提示词模板失败: {e}")
        return {"templates": []}


@router.get("/api/prompt-libraries")
async def get_prompt_libraries():
    return {"library": public_prompt_libraries()}


@router.post("/api/prompt-libraries")
async def create_prompt_library(payload: PromptLibraryRequest):
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        library = {
            "id": f"lib_{uuid.uuid4().hex[:12]}",
            "name": sanitize_asset_name(payload.name, "提示词库"),
            "type": "prompt",
            "categories": [],
            "items": [],
        }
        data.setdefault("libraries", []).append(library)
        data["active_library_id"] = library["id"]
        data = save_prompt_libraries(data)
        new_lib = next((lib for lib in data.get("libraries", []) if lib.get("id") == library["id"]), library)
        return {"library": public_prompt_libraries(data), "prompt_library": new_lib}


@router.patch("/api/prompt-libraries/{library_id}")
async def rename_prompt_library(library_id: str, payload: PromptLibraryRequest):
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        library = find_prompt_library(data, library_id)
        if not library or library.get("id") != library_id:
            raise HTTPException(status_code=404, detail="提示词库不存在")
        library["name"] = sanitize_asset_name(payload.name, library.get("name") or "提示词库")
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data), "prompt_library": library}


@router.delete("/api/prompt-libraries/{library_id}")
async def delete_prompt_library(library_id: str):
    if library_id == "system":
        raise HTTPException(status_code=400, detail="系统提示词库不能删除，可以删除其中的提示词")
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        libraries = data.get("libraries", []) or []
        kept = [lib for lib in libraries if lib.get("id") != library_id]
        if len(kept) == len(libraries):
            raise HTTPException(status_code=404, detail="提示词库不存在")
        data["libraries"] = kept
        if data.get("active_library_id") == library_id:
            data["active_library_id"] = "system"
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data)}


@router.post("/api/prompt-libraries/items")
async def add_prompt_library_item(payload: PromptLibraryItemRequest):
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        library = find_prompt_library(data, payload.library_id)
        if not library:
            raise HTTPException(status_code=404, detail="提示词库不存在")
        if not str(payload.positive or "").strip():
            raise HTTPException(status_code=400, detail="提示词内容不能为空")
        category_val = (payload.category or "custom").strip()
        cat_id = normalize_prompt_category_id(category_val)
        cats = library.setdefault("categories", [])
        if not any((c.get("id") == cat_id or c.get("name") == category_val) for c in cats if isinstance(c, dict)):
            cats.append({"id": cat_id, "name": category_val})
        item = normalize_prompt_library_item({
            "id": f"tpl_{uuid.uuid4().hex[:12]}",
            "name": payload.name,
            "category": cat_id,
            "positive": payload.positive,
            "negative": payload.negative,
            "scene": payload.scene,
            "created_at": now_ms(),
            "updated_at": now_ms(),
        })
        library.setdefault("items", []).insert(0, item)
        data["active_library_id"] = library.get("id") or data.get("active_library_id")
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data), "item": item}


@router.patch("/api/prompt-libraries/items/{item_id}")
async def update_prompt_library_item(item_id: str, payload: PromptLibraryItemRequest):
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        for library in data.get("libraries", []) or []:
            if payload.library_id and library.get("id") != payload.library_id:
                continue
            for index, item in enumerate(library.get("items", []) or []):
                if item.get("id") == item_id:
                    category_val = (payload.category or item.get("category") or "custom").strip()
                    cat_id = normalize_prompt_category_id(category_val)
                    cats = library.setdefault("categories", [])
                    if not any((c.get("id") == cat_id or c.get("name") == category_val) for c in cats if isinstance(c, dict)):
                        cats.append({"id": cat_id, "name": category_val})
                    next_item = normalize_prompt_library_item({
                        **item,
                        "name": payload.name or item.get("name"),
                        "category": cat_id,
                        "positive": payload.positive or item.get("positive"),
                        "negative": payload.negative,
                        "scene": payload.scene,
                        "updated_at": now_ms(),
                    })
                    library["items"][index] = next_item
                    data = save_prompt_libraries(data)
                    return {"library": public_prompt_libraries(data), "item": next_item}
        raise HTTPException(status_code=404, detail="提示词不存在")


@router.delete("/api/prompt-libraries/items/{item_id}")
async def delete_prompt_library_item(item_id: str):
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        removed = None
        for library in data.get("libraries", []) or []:
            keep = []
            for item in library.get("items", []) or []:
                if item.get("id") == item_id:
                    removed = item
                else:
                    keep.append(item)
            library["items"] = keep
        if not removed:
            raise HTTPException(status_code=404, detail="提示词不存在")
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data), "removed": 1}


@router.post("/api/prompt-libraries/items/delete")
async def batch_delete_prompt_library_items(payload: PromptLibraryBatchDeleteRequest):
    ids = {str(item) for item in (payload.ids or []) if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择提示词")
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        removed = 0
        for library in data.get("libraries", []) or []:
            keep = []
            for item in library.get("items", []) or []:
                if item.get("id") in ids:
                    removed += 1
                else:
                    keep.append(item)
            library["items"] = keep
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data), "removed": removed}


@router.post("/api/prompt-libraries/categories")
async def add_prompt_library_category(payload: PromptLibraryCategoryRequest):
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        library = find_prompt_library(data, payload.library_id) or find_prompt_library(data, "system")
        if not library:
            raise HTTPException(status_code=404, detail="提示词库不存在")
        name = sanitize_asset_name(payload.name, "新分组")
        existing = {str(c.get("id")) for c in (library.get("categories") or []) if isinstance(c, dict)} | PROMPT_BUILTIN_CATEGORY_IDS
        cat_id = f"pcat_{uuid.uuid4().hex[:10]}"
        while cat_id in existing:
            cat_id = f"pcat_{uuid.uuid4().hex[:10]}"
        category = {"id": cat_id, "name": name}
        library.setdefault("categories", []).append(category)
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data), "category": category}


@router.patch("/api/prompt-libraries/categories/{category_id}")
async def rename_prompt_library_category(category_id: str, payload: PromptLibraryCategoryRequest):
    name = sanitize_asset_name(payload.name, "")
    if not name:
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        updated = False
        for library in data.get("libraries", []) or []:
            for cat in library.get("categories") or []:
                if isinstance(cat, dict) and cat.get("id") == category_id:
                    cat["name"] = name
                    updated = True
        if not updated:
            raise HTTPException(status_code=404, detail="分组不存在")
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data)}


@router.delete("/api/prompt-libraries/categories/{category_id}")
async def delete_prompt_library_category(category_id: str):
    with PROMPT_LOCK:
        data = load_prompt_libraries()
        found = False
        for library in data.get("libraries", []) or []:
            cats = library.get("categories") or []
            kept = [c for c in cats if not (isinstance(c, dict) and c.get("id") == category_id)]
            if len(kept) != len(cats):
                found = True
                library["categories"] = kept
                fallback = next((str(c.get("id")) for c in kept if isinstance(c, dict) and c.get("id")), "")
                for item in library.get("items", []) or []:
                    if isinstance(item, dict) and item.get("category") == category_id:
                        item["category"] = fallback
        if not found:
            raise HTTPException(status_code=404, detail="分组不存在")
        data = save_prompt_libraries(data)
        return {"library": public_prompt_libraries(data)}
