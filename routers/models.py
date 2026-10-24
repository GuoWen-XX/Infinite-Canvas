"""Pydantic data models for Infinite-Canvas Cloud AI APIs.

Decoupled data transfer objects (DTOs) for:
- Online Image generation & Midjourney
- Video generation & MiniMax timeline export
- Cloud Integrations (RunningHub, Jimeng, Codex, Gemini CLI)
- Chat, Multi-modal Agent & Canvas LLM
"""
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field

from core.providers import (
    ONLINE_IMAGE_PROMPT_MAX_LENGTH,
    VIDEO_PROMPT_MAX_LENGTH,
    LLM_MESSAGE_MAX_LENGTH,
    SYSTEM_PROMPT,
)

class TokenRequest(BaseModel):
    token: str

class CloudGenRequest(BaseModel):
    prompt: str
    api_key: str = ""
    model: str = ""
    resolution: str = "1024x1024"
    type: str = "zimage"
    image_urls: List[str] = []
    loras: Optional[Any] = None
    client_id: Optional[str] = None

class CloudPollRequest(BaseModel):
    task_id: str
    api_key: str = ""
    client_id: Optional[str] = None

class AIReference(BaseModel):
    url: str = ""
    name: str = ""
    role: str = ""
    kind: str = ""
    mime: str = ""
    original_url: str = ""
    source_url: str = ""
    originalLocalUrl: str = ""

class OnlineImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    provider_id: str = "comfly"
    model: str = ""
    size: str = "1024x1024"
    aspect_ratio: str = ""
    resolution: str = ""
    quality: str = "auto"
    n: int = 1
    reference_images: List[AIReference] = []
    operation: str = ""
    resolution_type: str = ""

class MidjourneySubmitRequest(BaseModel):
    provider_id: str = ""
    prompt: str = Field(default="", max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    size: str = "1:1"
    version: str = "6.1"
    speed: str = "relax"
    reference_images: List[AIReference] = []
    mode: str = "imagine"

class MidjourneyActionRequest(BaseModel):
    provider_id: str = ""
    task_id: str = Field(min_length=1, max_length=240)
    action: str = "variation"
    index: int = 1
    speed: str = "relax"
    direction: str = ""
    zoom_ratio: Optional[float] = None
    custom_id: str = Field(default="", max_length=600)
    prompt: str = Field(default="", max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)

class MidjourneyModalRequest(BaseModel):
    provider_id: str = ""
    task_id: str = Field(min_length=1, max_length=240)
    prompt: str = Field(default="", max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    speed: str = "relax"
    mask_image: Optional[AIReference] = None

class ImageTaskQueryRequest(BaseModel):
    provider_id: str = "comfly"
    task_id: str = Field(min_length=1, max_length=240)


class CanvasVideoRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=VIDEO_PROMPT_MAX_LENGTH)
    provider_id: str = "comfly"
    model: str = "veo3-fast"
    duration: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = ""
    size: str = ""
    images: List[AIReference] = []
    videos: List[str] = []
    audios: List[str] = []
    enhance_prompt: bool = False
    enable_upsample: bool = False
    watermark: bool = False
    seed: Optional[int] = None
    camerafixed: bool = False
    return_last_frame: bool = False
    generate_audio: bool = False
    multimodal: bool = False
    trusted_asset: bool = False

class TempShUploadRequest(BaseModel):
    url: str = ""

class CloudVideoUploadRequest(BaseModel):
    url: str = ""
    service: str = "auto"

class RunningHubSubmitRequest(BaseModel):
    webappId: str = ""
    nodeInfoList: List[Dict[str, Any]] = []
    instanceType: str = ""
    useWallet: bool = False

class RunningHubWorkflowSubmitRequest(BaseModel):
    workflowId: str = ""
    nodeInfoList: List[Dict[str, Any]] = []
    workflow: Any = None
    useWallet: bool = False

class RunningHubUploadAssetRequest(BaseModel):
    url: str = ""
    useWallet: bool = False

class JimengHelpRequest(BaseModel):
    command: str = ""

class CodexHelpRequest(BaseModel):
    command: str = ""

class GeminiCliHelpRequest(BaseModel):
    command: str = ""

class JimengQueryMediaRequest(BaseModel):
    submit_id: str = ""
    kind: str = "image"

class RunningHubWorkflowConfigField(BaseModel):
    id: str = ""
    nodeId: str = ""
    fieldName: str = ""
    fieldValue: str = ""
    fieldType: str = "TEXT"
    label: str = ""
    enabled: bool = True
    sourceFromUpstream: bool = True
    group: str = ""
    note: str = ""
    options: List[str] = Field(default_factory=list)
    random_enabled: bool = False
    min: Any = ""
    max: Any = ""
    step: Any = ""
    imageOrder: int = 0
    required: bool = False

class RunningHubWorkflowConfig(BaseModel):
    workflowId: str = ""
    title: str = ""
    description: str = ""
    fields: List[RunningHubWorkflowConfigField] = Field(default_factory=list)
    workflowJson: Dict[str, Any] = Field(default_factory=dict)
    optionalImageMode: str = "prune-workflow"
    raw: Dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    conversation_id: str = ""
    message: str = Field(min_length=1, max_length=LLM_MESSAGE_MAX_LENGTH)
    system_prompt: str = ""
    model: str = ""
    image_model: str = ""
    image_provider: str = ""
    mode: str = "chat"
    size: str = "1024x1024"
    aspect_ratio: str = ""
    resolution: str = ""
    quality: str = "auto"
    reference_images: List[AIReference] = []
    provider: str = "comfly"
    ms_model: str = ""

def chat_system_prompt(payload):
    prompt = str(getattr(payload, "system_prompt", "") or "").strip()
    return prompt or SYSTEM_PROMPT

class MsGenerateRequest(BaseModel):
    prompt: str
    api_key: str = ""
    model: str = "black-forest-labs/FLUX.2-klein-9B"
    image_urls: List[str] = []
    width: int = 0
    height: int = 0
    size: str = ""
    loras: Optional[Any] = None
    client_id: Optional[str] = None

class CanvasLLMRequest(BaseModel):
    message: str = Field(min_length=1, max_length=LLM_MESSAGE_MAX_LENGTH)
    system_prompt: str = ""
    model: str = ""
    messages: List[Dict[str, Any]] = []
    provider: str = "comfly"
    ms_model: str = ""
    images: List[str] = []   # 可以是 /output/*.png、/assets/*.png 本地路径 或 http(s) URL 或 data URL
    videos: List[str] = []   # 可以是 /output/*.mp4、/assets/*.mp4 本地路径 或 http(s) URL 或 data URL

class ConversationCreateRequest(BaseModel):
    title: str = "新对话"

class MiniMaxTimelineClip(BaseModel):
    url: str = ""
    name: str = ""
    start: float = 0
    end: float = 0
    duration: float = 0

class MiniMaxTimelineExportRequest(BaseModel):
    clips: List[MiniMaxTimelineClip] = []
    filename: str = "minimax-timeline.mp4"

class LocalImageImportRequest(BaseModel):
    path: str = ""
    paths: List[str] = Field(default_factory=list)



class Base64UploadRequest(BaseModel):
    image: str = ""
    ext: str = "png"
    target_dir: str = "output"
