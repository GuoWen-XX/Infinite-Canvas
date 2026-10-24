import os
import math
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "images", "ext-previews")
os.makedirs(OUT_DIR, exist_ok=True)

FONT_MONO = os.path.join(ROOT, "static", "vendor", "fonts", "jetbrains-mono-6.ttf")
FONT_TITLE = os.path.join(ROOT, "static", "vendor", "fonts", "montserrat-600.ttf")
FONT_ZH = "C:/Windows/Fonts/msyh.ttc"

tools_data = [
    {
        "id": "mai",
        "name": "MAI Playground",
        "nameZh": "MAI 体验站",
        "domain": "playground.microsoft.ai",
        "category": "AI 体验",
        "desc": "微软新一代多模态 AI 交互体验平台，提供前沿生成式能力与灵感探索。",
        "accent": (56, 189, 248),
        "pattern": "nodes"
    },
    {
        "id": "copilot",
        "name": "Copilot Imagine",
        "nameZh": "Copilot 生图",
        "domain": "copilot.microsoft.com",
        "category": "AI 生图",
        "desc": "微软智能生图工具，基于多模态大模型实现高拟真与创意风格视觉生成。",
        "accent": (129, 140, 248),
        "pattern": "boxes"
    },
    {
        "id": "arena",
        "name": "Arena AI",
        "nameZh": "Arena AI",
        "domain": "arena.ai",
        "category": "模型评测",
        "desc": "LMSYS 社区权威的大模型对决评测平台，实时盲测体验对比前沿模型表现。",
        "accent": (251, 146, 60),
        "pattern": "versus"
    },
    {
        "id": "reve",
        "name": "Reve Image",
        "nameZh": "Reve 生图",
        "domain": "reve.com",
        "category": "AI 生图",
        "desc": "专注于高概念艺术与创意摄影的生成式生图平台，提供细腻光影与质感。",
        "accent": (244, 114, 182),
        "pattern": "focus"
    },
    {
        "id": "gflow",
        "name": "Google Flow",
        "nameZh": "Google Flow",
        "domain": "labs.google",
        "category": "创意实验",
        "desc": "Google Labs 实验性生成工具，串联提示词与多模态创意流水线。",
        "accent": (74, 222, 128),
        "pattern": "flow"
    },
    {
        "id": "grok",
        "name": "Grok Imagine",
        "nameZh": "Grok Imagine",
        "domain": "grok.com",
        "category": "AI 生图",
        "desc": "xAI 实时生图与理解工具，具备强大真实感呈现与敏锐的上下文解析力。",
        "accent": (251, 113, 133),
        "pattern": "slash"
    },
    {
        "id": "qianwen",
        "name": "Qianwen Create",
        "nameZh": "千问创作",
        "domain": "create.qianwen.com",
        "category": "多模态创作",
        "desc": "阿里云通义千问官方内容创作中心，涵盖生图、文案与长文本生成。",
        "accent": (192, 132, 252),
        "pattern": "star"
    },
    {
        "id": "chatgpt",
        "name": "ChatGPT",
        "nameZh": "ChatGPT 对话",
        "domain": "chatgpt.com",
        "category": "AI 顾问",
        "desc": "OpenAI 旗舰对话助手，提供灵感推演、Prompt 精修与多轮创作顾问。",
        "accent": (52, 211, 153),
        "pattern": "spiral"
    },
    {
        "id": "rh-canvas",
        "name": "RunningHub Canvas",
        "nameZh": "RunningHub 画布",
        "domain": "rhtv.runninghub.cn",
        "category": "工作流画布",
        "desc": "云端开箱即用的 ComfyUI 流程画布，随时调用算力运行工业级生图工作流。",
        "accent": (56, 189, 248),
        "pattern": "circuit"
    },
    {
        "id": "rh-user",
        "name": "RunningHub User Center",
        "nameZh": "RunningHub 个人中心",
        "domain": "runninghub.cn",
        "category": "算力管理",
        "desc": "RunningHub 算力与个人中心控制台，查看任务进度、API 授权与资产存储。",
        "accent": (96, 165, 250),
        "pattern": "dashboard"
    },
    {
        "id": "cloudcb",
        "name": "CloudCB",
        "nameZh": "CloudCB 图像编辑",
        "domain": "cloudcb.me",
        "category": "图像编辑",
        "desc": "轻量高效的在线图像后期与微调工具，支持快捷抠图、无损裁切与微调。",
        "accent": (45, 212, 191),
        "pattern": "edit"
    },
    {
        "id": "ascii",
        "name": "ASCII Lab",
        "nameZh": "ASCII Lab",
        "domain": "ascii-lab.sg.agentos-app.run",
        "category": "字符艺术",
        "desc": "将现代图像转码为 ASCII 字符画与终端风格纹理，探索纯粹文本的视觉张力。",
        "accent": (163, 230, 53),
        "pattern": "terminal"
    },
    {
        "id": "ladybug",
        "name": "Ladybug FX",
        "nameZh": "Ladybug FX",
        "domain": "app.theladybug.app",
        "category": "视觉滤镜",
        "desc": "专为设计师打造的复古胶片、辉光与色差特效渲染器，赋予素材独特情绪。",
        "accent": (251, 191, 36),
        "pattern": "lens"
    },
    {
        "id": "boardmix",
        "name": "Boardmix",
        "nameZh": "Boardmix 白板",
        "domain": "boardmix.cn",
        "category": "协作白板",
        "desc": "综合型在线多人协作白板，集思维导图、流程图与团队研讨于一体。",
        "accent": (129, 140, 248),
        "pattern": "canvas"
    },
    {
        "id": "canva",
        "name": "Canva",
        "nameZh": "Canva",
        "domain": "canva.com",
        "category": "平面设计",
        "desc": "全功能云端视觉排版工具，拥有丰富的商用模板库与智能版式排版组件。",
        "accent": (34, 211, 238),
        "pattern": "layout"
    },
    {
        "id": "longcat",
        "name": "LongCat",
        "nameZh": "LongCat",
        "domain": "longcat.chat",
        "category": "AI 顾问",
        "desc": "极简轻盈的生成式对话工具，专注文案改写、灵感头脑风暴与指令构思。",
        "accent": (245, 158, 11),
        "pattern": "chat"
    },
    {
        "id": "dola",
        "name": "Dola",
        "nameZh": "Dola",
        "domain": "dola.com",
        "category": "AI 助手",
        "desc": "基于自然语言的智能日程、计划与灵感捕获助手，随时整理记录创作灵感。",
        "accent": (167, 139, 250),
        "pattern": "radar"
    },
    {
        "id": "agnes-wb",
        "name": "Agnes Workbench",
        "nameZh": "Agnes 工作台",
        "domain": "agnes-image-gen.netlify.app",
        "category": "AI 生图",
        "desc": "敏捷的生成式图像调试工作台，便于快速探索不同 Prompt 变体与种子参数。",
        "accent": (52, 211, 153),
        "pattern": "sliders"
    },
    {
        "id": "lovart",
        "name": "Lovart",
        "nameZh": "Lovart",
        "domain": "lovart.ai",
        "category": "设计顾问",
        "desc": "专为空间与视觉创作者设计的审美指导平台，输出精准的情绪板与风格建议。",
        "accent": (244, 114, 182),
        "pattern": "palette"
    },
    {
        "id": "topaz",
        "name": "Topaz Studio",
        "nameZh": "Topaz Studio",
        "domain": "topazlabs.com",
        "category": "画质增强",
        "desc": "业界领先的 AI 超分辨率与锐化处理平台，消除伪影并深度还原图像细节。",
        "accent": (96, 165, 250),
        "pattern": "resolution"
    },
    {
        "id": "tooootem",
        "name": "Tooootem",
        "nameZh": "Tooootem",
        "domain": "tooootem.vercel.app",
        "category": "生成实验",
        "desc": "前沿参数化艺术与分形图形生成器，探索算法几何与未来主义图案美学。",
        "accent": (192, 132, 252),
        "pattern": "totem"
    },
    {
        "id": "feralui",
        "name": "FeralUI Gradients",
        "nameZh": "FeralUI 渐变生成器",
        "domain": "feralui.dev",
        "category": "设计工具",
        "desc": "免登录在线调配细腻的网格噪点、流动动效与和风传统色渐变，支持导出 SVG、PNG 与 MP4 视频。",
        "accent": (244, 114, 182),
        "pattern": "flow"
    },
    {
        "id": "valessa",
        "name": "Valessa",
        "nameZh": "Valessa 3D 渲染",
        "domain": "valessa.riotters.com",
        "category": "3D 渲染",
        "desc": "Riotters 出品的 3D 产品视觉渲染平台，支持上传模型、自定义材质与光影运镜，秒级导出视频或图片。",
        "accent": (168, 85, 247),
        "pattern": "boxes"
    },
    {
        "id": "google-pics",
        "name": "Google Pics",
        "nameZh": "Google Pics",
        "domain": "docs.google.com",
        "category": "素材管理",
        "desc": "Google Docs 图片与画板素材协作库，便于团队沉淀与协同整理项目图片资产。",
        "accent": (66, 133, 244),
        "pattern": "palette"
    },
    {
        "id": "mindvideo",
        "name": "MindVideo",
        "nameZh": "MindVideo 创意工作室",
        "domain": "mindvideo.ai",
        "category": "视频生成",
        "desc": "新一代 AI 创意视频工作室，支持文本与图像驱动的高拟真运镜、影视级动态与视觉叙事。",
        "accent": (168, 85, 247),
        "pattern": "focus"
    },
    {
        "id": "gen-design",
        "name": "Generative Design",
        "nameZh": "Generative Design",
        "domain": "generative-gestaltung.de",
        "category": "创意编程",
        "desc": "经典生成式设计与计算美学代码实验场，提供丰富的 P5.js 交互图形、算法分形与参数化视觉。",
        "accent": (52, 211, 153),
        "pattern": "totem"
    },
    {
        "id": "shadergpt",
        "name": "ShaderGPT",
        "nameZh": "ShaderGPT",
        "domain": "shadergpt.14islands.com",
        "category": "着色器",
        "desc": "14islands 出品的 WebGL 着色器 AI 生成器，支持自然语言实时调配 GLSL 动效与三维材质光影。",
        "accent": (251, 146, 60),
        "pattern": "slash"
    },
    {
        "id": "sensenova",
        "name": "SenseNova Workbench",
        "nameZh": "商汤日日新",
        "domain": "unify.light-ai.top",
        "category": "AI 体验",
        "desc": "商汤日日新 SenseNova 统一交互体验平台，提供多元化生成式大模型与轻量化能力测试。",
        "accent": (56, 189, 248),
        "pattern": "star"
    },
    {
        "id": "fal-ai",
        "name": "fal.ai",
        "nameZh": "fal.ai 开发者看板",
        "domain": "fal.ai",
        "category": "生成式 API",
        "desc": "面向下一代生成式媒体的极速推理云平台，提供 FLUX、SD3.5、Luma 等模型的高并发 API。",
        "accent": (234, 179, 8),
        "pattern": "slash"
    },
    {
        "id": "aihubmix",
        "name": "AIHubMix",
        "nameZh": "AIHubMix 聚合平台",
        "domain": "aihubmix.com",
        "category": "API 聚合",
        "desc": "一站式主流大模型 API 聚合与分发网关，支持全球百余款顶尖 LLM 与多模态模型高速直连。",
        "accent": (99, 102, 241),
        "pattern": "nodes"
    },
    {
        "id": "omniakey",
        "name": "OmniaKey",
        "nameZh": "OmniaKey 接口网关",
        "domain": "omniakey.com",
        "category": "API 聚合",
        "desc": "面向开发者与创作者的通用 AI 密钥与路由聚合服务，提供高可用 OpenAI 标准接口中转。",
        "accent": (14, 165, 233),
        "pattern": "terminal"
    },
    {
        "id": "eachlabs",
        "name": "EachLabs",
        "nameZh": "EachLabs 生成式 API",
        "domain": "eachlabs.ai",
        "category": "AI 生成 API",
        "desc": "专注于图像、视频生成与视觉编辑的多模态 AI 开发者平台，支持灵活的工作流与微调接口。",
        "accent": (236, 72, 153),
        "pattern": "focus"
    },
    {
        "id": "apikey-fun",
        "name": "ApiKey.fun",
        "nameZh": "ApiKey.fun 分发站",
        "domain": "apikey.fun",
        "category": "API 分发",
        "desc": "高性价比的 AI 接口聚合与中转服务平台，多节点负载均衡，轻松调用主流商用大模型。",
        "accent": (34, 197, 94),
        "pattern": "circuit"
    },
    {
        "id": "merge-gateway",
        "name": "Merge Gateway",
        "nameZh": "Merge API 网关",
        "domain": "gateway.merge.dev",
        "category": "统一网关",
        "desc": "面向团队与企业的统一 AI API 接入与路由网关，集中管控调用配额、审计与接口安全。",
        "accent": (168, 85, 247),
        "pattern": "flow"
    },
    {
        "id": "animos",
        "name": "Animos",
        "nameZh": "Animos 动效设计",
        "domain": "animos.app",
        "category": "动效设计",
        "desc": "面向设计展示的在线动态模板与动效编辑器，快速制作高质感产品演示与镜头转场。",
        "accent": (244, 114, 182),
        "pattern": "flow"
    },
    {
        "id": "brand-gen",
        "name": "Brand Generator",
        "nameZh": "Brand Generator",
        "domain": "brand-generator.stoyanov.works",
        "category": "品牌设计",
        "desc": "Stoyanov Works 出品的品牌资产生成器，基于参数与色彩系统自动生成整套品牌视觉体系。",
        "accent": (99, 102, 241),
        "pattern": "palette"
    },
    {
        "id": "adam",
        "name": "Adam",
        "nameZh": "Adam 工业设计 Copilot",
        "domain": "adam.new",
        "category": "CAD 辅助",
        "desc": "面向硬件团队与工业工程师的 AI CAD 智能副驾驶，自然语言辅助三维构件推演与机械设计。",
        "accent": (14, 165, 233),
        "pattern": "boxes"
    },
    {
        "id": "cutia",
        "name": "Cutia",
        "nameZh": "Cutia 在线剪辑",
        "domain": "cutia.msgbyte.com",
        "category": "视频剪辑",
        "desc": "轻量高效的开源网页端在线音视频剪辑器，具备多轨道时间轴、特效字幕与实时回放。",
        "accent": (236, 72, 153),
        "pattern": "edit"
    },
    {
        "id": "opencut",
        "name": "OpenCut",
        "nameZh": "OpenCut 视频编辑",
        "domain": "opencut.app",
        "category": "视频剪辑",
        "desc": "现代开源 Web 视频编辑平台，完全在浏览器本地处理，隐私安全，无水印极速导出。",
        "accent": (34, 197, 94),
        "pattern": "circuit"
    },
    {
        "id": "motion-dev",
        "name": "Motion",
        "nameZh": "Motion 动效库",
        "domain": "motion.dev",
        "category": "动效设计",
        "desc": "现代 Web 旗舰级声明式动画与动效引擎，提供高流畅度弹簧物理动效、滚动视差与手势交互。",
        "accent": (236, 72, 153),
        "pattern": "flow"
    },
    {
        "id": "minimax-h3",
        "name": "MiniMax H3-Max",
        "nameZh": "MiniMax H3-Max",
        "domain": "fal.ai",
        "category": "视频生成",
        "desc": "MiniMax 顶尖图生视频模型 H3-Max（fal.ai 部署版），具备强大物理规律仿真与电影级运镜。",
        "accent": (234, 179, 8),
        "pattern": "focus"
    },
    {
        "id": "openprocessing",
        "name": "OpenProcessing",
        "nameZh": "OpenProcessing 创意编程",
        "domain": "openprocessing.org",
        "category": "创意编程",
        "desc": "全球领先的 p5.js 与 Processing 计算艺术社区，在线编写、探索与分享参数化算法视觉。",
        "accent": (59, 130, 246),
        "pattern": "totem"
    },
    {
        "id": "gen-gestaltung",
        "name": "Generative Gestaltung",
        "nameZh": "Generative Gestaltung",
        "domain": "generative-gestaltung.de",
        "category": "设计理论",
        "desc": "生成式设计经典著作《Generative Gestaltung》官方主页，探索算法图形、复杂排版与计算美学。",
        "accent": (16, 185, 129),
        "pattern": "circuit"
    },
    {
        "id": "recent-design",
        "name": "Recent Design",
        "nameZh": "Recent Design 灵感库",
        "domain": "recent.design",
        "category": "设计灵感",
        "desc": "精选全球前沿工作室与独立设计师的数字产品、品牌与交互作品，捕捉即时设计灵感与视觉趋势。",
        "accent": (168, 85, 247),
        "pattern": "palette"
    }
]


def wrap_text(text, max_chars=24):
    lines = []
    curr = ""
    for char in text:
        curr += char
        if len(curr) >= max_chars:
            lines.append(curr)
            curr = ""
    if curr:
        lines.append(curr)
    return lines

def draw_pattern(draw, ptype, cx, cy, accent):
    ar, ag, ab = accent
    faint_col = (ar, ag, ab, 60)
    line_col = (ar, ag, ab, 120)
    bright_col = (ar, ag, ab, 220)

    if ptype == "nodes":
        pts = [
            (cx, cy - 100), (cx + 100, cy - 40), (cx + 80, cy + 80),
            (cx - 80, cy + 80), (cx - 100, cy - 40), (cx, cy)
        ]
        for i in range(5):
            draw.line([pts[i], pts[(i+1)%5]], fill=line_col, width=2)
            draw.line([pts[i], pts[5]], fill=faint_col, width=1)
        for pt in pts:
            draw.ellipse([pt[0]-10, pt[1]-10, pt[0]+10, pt[1]+10], outline=bright_col, width=2)
            draw.ellipse([pt[0]-4, pt[1]-4, pt[0]+4, pt[1]+4], fill=bright_col)

    elif ptype == "boxes":
        for off, alpha in [(0, 180), (35, 120), (70, 60)]:
            col = (ar, ag, ab, alpha)
            draw.rectangle([cx - 110 + off, cy - 90 + off, cx + 50 + off, cy + 70 + off], outline=col, width=2)
        draw.line([cx - 110, cy - 90, cx - 40, cy - 20], fill=line_col, width=1)
        draw.line([cx + 50, cy - 90, cx + 120, cy - 20], fill=line_col, width=1)
        draw.line([cx + 50, cy + 70, cx + 120, cy + 140], fill=line_col, width=1)
        draw.line([cx - 110, cy + 70, cx - 40, cy + 140], fill=line_col, width=1)

    elif ptype == "versus":
        draw.polygon([(cx - 120, cy - 110), (cx - 20, cy - 110), (cx - 50, cy + 110), (cx - 120, cy + 50)], outline=bright_col, width=2)
        draw.polygon([(cx + 120, cy + 110), (cx + 20, cy + 110), (cx + 50, cy - 110), (cx + 120, cy - 50)], outline=faint_col, width=2)
        draw.line([(cx - 8, cy - 130), (cx + 8, cy + 130)], fill=(255, 255, 255, 200), width=2)

    elif ptype == "focus":
        draw.ellipse([cx - 120, cy - 120, cx + 120, cy + 120], outline=faint_col, width=1)
        draw.ellipse([cx - 80, cy - 80, cx + 80, cy + 80], outline=line_col, width=2)
        draw.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], outline=bright_col, width=2)
        draw.line([cx - 140, cy, cx - 90, cy], fill=bright_col, width=2)
        draw.line([cx + 90, cy, cx + 140, cy], fill=bright_col, width=2)
        draw.line([cx, cy - 140, cx, cy - 90], fill=bright_col, width=2)
        draw.line([cx, cy + 90, cx, cy + 140], fill=bright_col, width=2)

    elif ptype == "flow":
        for r in range(30, 140, 30):
            draw.arc([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=(ar, ag, ab, int(200 - r * 1.2)), width=2)
            draw.arc([cx - r + 30, cy - r + 30, cx + r + 30, cy + r + 30], start=0, end=180, fill=(ar, ag, ab, int(180 - r * 1.1)), width=2)
        draw.line([cx - 130, cy, cx + 160, cy], fill=line_col, width=2)
        draw.ellipse([cx - 60, cy - 6, cx - 48, cy + 6], fill=bright_col)
        draw.ellipse([cx + 40, cy - 6, cx + 52, cy + 6], fill=bright_col)

    elif ptype == "slash":
        for i in range(-3, 4):
            x = cx + i * 35
            draw.line([(x - 60, cy + 120), (x + 60, cy - 120)], fill=(ar, ag, ab, 220 - abs(i) * 45), width=3 if i==0 else 2)

    elif ptype == "star":
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = cx + math.cos(rad) * 30
            y1 = cy + math.sin(rad) * 30
            x2 = cx + math.cos(rad) * 120
            y2 = cy + math.sin(rad) * 120
            draw.line([(x1, y1), (x2, y2)], fill=line_col, width=2)
        draw.ellipse([cx - 45, cy - 45, cx + 45, cy + 45], outline=bright_col, width=2)
        draw.ellipse([cx - 110, cy - 110, cx + 110, cy + 110], outline=faint_col, width=1)

    elif ptype == "spiral":
        pts = []
        for t in range(0, 720, 10):
            r = t * 0.16
            rad = math.radians(t)
            pts.append((cx + math.cos(rad) * r, cy + math.sin(rad) * r))
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i+1]], fill=(ar, ag, ab, int(40 + i * 2.5)), width=2)

    elif ptype == "circuit":
        lines = [
            [(cx - 120, cy - 80), (cx - 40, cy - 80), (cx, cy - 40), (cx + 90, cy - 40), (cx + 120, cy - 10)],
            [(cx - 120, cy), (cx - 60, cy), (cx - 20, cy + 40), (cx + 60, cy + 40), (cx + 120, cy + 100)],
            [(cx - 100, cy + 80), (cx - 30, cy + 80), (cx + 10, cy + 40), (cx + 120, cy + 40)],
        ]
        for l in lines:
            for i in range(len(l) - 1):
                draw.line([l[i], l[i+1]], fill=line_col, width=2)
            for pt in l:
                draw.ellipse([pt[0]-4, pt[1]-4, pt[0]+4, pt[1]+4], fill=bright_col)

    elif ptype == "dashboard":
        draw.arc([cx - 100, cy - 100, cx + 100, cy + 100], start=140, end=400, fill=line_col, width=3)
        draw.arc([cx - 70, cy - 70, cx + 70, cy + 70], start=140, end=320, fill=bright_col, width=6)
        draw.line([cx, cy, cx + 60, cy - 45], fill=(255, 255, 255, 220), width=3)
        draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=bright_col)

    elif ptype == "edit":
        draw.rectangle([cx - 110, cy - 90, cx + 70, cy + 70], outline=line_col, width=2)
        draw.rectangle([cx - 70, cy - 50, cx + 110, cy + 110], outline=bright_col, width=2)
        draw.line([cx - 70, cy - 50, cx + 70, cy + 70], fill=faint_col, width=1)

    elif ptype == "terminal":
        draw.rectangle([cx - 120, cy - 80, cx + 120, cy + 80], outline=line_col, width=2)
        draw.line([cx - 120, cy - 55, cx + 120, cy - 55], fill=faint_col, width=1)
        for i in range(3):
            draw.ellipse([cx - 105 + i * 18, cy - 68, cx - 95 + i * 18, cy - 58], fill=faint_col)
        for row in range(4):
            y = cy - 35 + row * 24
            w = 80 + (row * 37) % 110
            draw.line([(cx - 95, y), (cx - 95 + w, y)], fill=bright_col if row==0 else faint_col, width=3)

    elif ptype == "lens":
        for r in [120, 95, 70, 45]:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(ar, ag, ab, int(r * 1.6)), width=2)
        draw.line([cx - 130, cy, cx + 130, cy], fill=faint_col, width=1)
        draw.line([cx, cy - 130, cx, cy + 130], fill=faint_col, width=1)

    elif ptype == "canvas":
        draw.rectangle([cx - 110, cy - 80, cx - 10, cy + 10], outline=bright_col, width=2)
        draw.rectangle([cx + 10, cy - 50, cx + 110, cy + 40], outline=line_col, width=2)
        draw.rectangle([cx - 60, cy + 30, cx + 40, cy + 110], outline=faint_col, width=2)
        draw.line([(cx - 10, cy - 35), (cx + 10, cy - 20)], fill=bright_col, width=2)
        draw.line([(cx + 10, cy + 20), (cx, cy + 30)], fill=line_col, width=2)

    elif ptype == "layout":
        draw.rectangle([cx - 110, cy - 100, cx + 110, cy + 100], outline=faint_col, width=1)
        draw.rectangle([cx - 95, cy - 85, cx - 15, cy + 85], outline=line_col, width=2)
        draw.rectangle([cx + 5, cy - 85, cx + 95, cy - 10], outline=bright_col, width=2)
        draw.rectangle([cx + 5, cy + 5, cx + 95, cy + 85], outline=faint_col, width=1)

    elif ptype == "chat":
        draw.polygon([(cx - 100, cy - 80), (cx + 40, cy - 80), (cx + 40, cy + 10), (cx - 60, cy + 10), (cx - 90, cy + 35), (cx - 85, cy + 10), (cx - 100, cy + 10)], outline=bright_col, width=2)
        draw.polygon([(cx - 30, cy - 10), (cx + 100, cy - 10), (cx + 100, cy + 70), (cx + 85, cy + 70), (cx + 90, cy + 95), (cx + 60, cy + 70), (cx - 30, cy + 70)], outline=line_col, width=2)

    elif ptype == "radar":
        for r in [40, 80, 120]:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=faint_col, width=1)
        draw.line([cx - 125, cy, cx + 125, cy], fill=faint_col, width=1)
        draw.line([cx, cy - 125, cx, cy + 125], fill=faint_col, width=1)
        draw.line([cx, cy, cx + 90, cy - 90], fill=bright_col, width=2)
        draw.ellipse([cx + 45, cy - 40, cx + 55, cy - 30], fill=bright_col)

    elif ptype == "sliders":
        for i, val in enumerate([0.3, 0.7, 0.5, 0.9, 0.4]):
            x = cx - 100 + i * 50
            draw.line([(x, cy - 80), (x, cy + 80)], fill=faint_col, width=2)
            sy = int(cy + 80 - val * 160)
            draw.rectangle([x - 12, sy - 8, x + 12, sy + 8], outline=bright_col, width=2)
            draw.line([(x - 8, sy), (x + 8, sy)], fill=bright_col, width=2)

    elif ptype == "palette":
        draw.ellipse([cx - 90, cy - 90, cx + 30, cy + 30], outline=bright_col, width=2)
        draw.polygon([(cx - 20, cy + 90), (cx + 100, cy + 90), (cx + 40, cy - 30)], outline=line_col, width=2)
        draw.rectangle([cx - 90, cy + 10, cx - 10, cy + 90], outline=faint_col, width=2)

    elif ptype == "resolution":
        step = 25
        for x in range(cx - 100, cx + 101, step):
            draw.line([(x, cy - 100), (x, cy + 100)], fill=faint_col, width=1)
        for y in range(cy - 100, cy + 101, step):
            draw.line([(cx - 100, y), (cx + 100, y)], fill=faint_col, width=1)
        draw.rectangle([cx - 25, cy - 25, cx + 25, cy + 25], outline=bright_col, width=3)
        draw.line([cx - 50, cy - 50, cx - 25, cy - 25], fill=bright_col, width=2)
        draw.line([cx + 50, cy - 50, cx + 25, cy - 25], fill=bright_col, width=2)
        draw.line([cx + 50, cy + 50, cx + 25, cy + 25], fill=bright_col, width=2)
        draw.line([cx - 50, cy + 50, cx - 25, cy + 25], fill=bright_col, width=2)

    elif ptype == "totem":
        for i in range(12):
            rad = math.radians(i * 30)
            rx = cx + math.cos(rad) * 45
            ry = cy + math.sin(rad) * 45
            draw.ellipse([rx - 45, ry - 45, rx + 45, ry + 45], outline=faint_col, width=1)
        draw.ellipse([cx - 65, cy - 65, cx + 65, cy + 65], outline=bright_col, width=2)
        draw.ellipse([cx - 110, cy - 110, cx + 110, cy + 110], outline=line_col, width=1)

def generate_tool_preview(tool):
    W, H = 1200, 630
    im = Image.new("RGBA", (W, H), (14, 18, 25, 255))
    draw = ImageDraw.Draw(im)

    # 1. Subtle radial gradient glow centered at (cx=920, cy=315)
    gx, gy = 920, 315
    ar, ag, ab = tool["accent"]
    for r in range(400, 0, -8):
        factor = (1.0 - r / 400.0) ** 2
        alpha = int(40 * factor)
        draw.ellipse([gx - r, gy - r, gx + r, gy + r], fill=(ar, ag, ab, alpha))

    # 2. Dot grid
    for x in range(36, W - 36, 36):
        for y in range(36, H - 36, 36):
            draw.point((x, y), fill=(255, 255, 255, 14))

    # 3. Outer boundary & corner reticles
    draw.rectangle([24, 24, W - 25, H - 25], outline=(38, 48, 64), width=1)
    draw.rectangle([28, 28, W - 29, H - 29], outline=(28, 36, 48), width=1)
    for cx, cy in [(24, 24), (W - 25, 24), (24, H - 25), (W - 25, H - 25)]:
        draw.line([(cx - 8, cy), (cx + 8, cy)], fill=(148, 163, 184), width=1)
        draw.line([(cx, cy - 8), (cx, cy + 8)], fill=(148, 163, 184), width=1)

    # 4. Fonts
    font_mono_14 = ImageFont.truetype(FONT_MONO, 14)
    font_mono_12 = ImageFont.truetype(FONT_MONO, 12)
    font_title_en = ImageFont.truetype(FONT_TITLE, 46)
    font_title_zh = ImageFont.truetype(FONT_ZH, 28)
    font_cat = ImageFont.truetype(FONT_ZH, 16)
    font_desc = ImageFont.truetype(FONT_ZH, 22)

    # 5. Top header bar
    draw.text((64, 56), "INFINITE CANVAS // EXTERNAL SUITE", font=font_mono_14, fill=(100, 116, 139))
    domain_text = tool["domain"]
    dom_bbox = font_mono_14.getbbox(domain_text)
    dom_w = dom_bbox[2] - dom_bbox[0]
    pill_x2 = W - 64
    pill_x1 = pill_x2 - dom_w - 24
    draw.rectangle([pill_x1, 50, pill_x2, 78], outline=(51, 65, 85), fill=(20, 27, 38, 220), width=1)
    draw.text((pill_x1 + 12, 55), domain_text, font=font_mono_14, fill=(148, 163, 184))
    draw.line([(64, 96), (W - 64, 96)], fill=(38, 48, 64), width=1)

    # 6. Left content
    cat_text = tool["category"]
    cat_bbox = font_cat.getbbox(cat_text)
    cat_w = cat_bbox[2] - cat_bbox[0]
    draw.rectangle([64, 130, 64 + cat_w + 24, 160], outline=(ar, ag, ab, 160), fill=(ar, ag, ab, 30), width=1)
    draw.text((76, 134), cat_text, font=font_cat, fill=(ar, ag, ab))

    draw.text((64, 184), tool["name"], font=font_title_en, fill=(248, 250, 252))
    draw.text((64, 252), tool["nameZh"], font=font_title_zh, fill=(203, 213, 225))

    draw.line([(64, 305), (600, 305)], fill=(ar, ag, ab, 120), width=2)
    draw.line([(600, 305), (700, 305)], fill=(38, 48, 64), width=1)

    desc_lines = wrap_text(tool["desc"], max_chars=24)
    curr_y = 330
    for line in desc_lines:
        draw.text((64, curr_y), line, font=font_desc, fill=(148, 163, 184))
        curr_y += 36

    draw.line([(64, 530), (W - 64, 530)], fill=(38, 48, 64), width=1)
    draw.text((64, 552), f"ID: {tool['id']}  ·  PROTOCOL: EXT-TAB  ·  SECURITY: SANDBOXED", font=font_mono_12, fill=(100, 116, 139))
    draw.text((W - 320, 552), "CLICK TO OPEN IN NEW WINDOW", font=font_mono_12, fill=(100, 116, 139))

    # 7. Right graphic area
    draw_pattern(draw, tool["pattern"], 940, 315, tool["accent"])

    out_path = os.path.join(OUT_DIR, f"{tool['id']}.png")
    final_img = im.convert("RGB")
    final_img.save(out_path, "PNG", optimize=True)
    print(f"Generated: {out_path} ({os.path.getsize(out_path)} bytes)")

def main():
    print(f"Generating {len(tools_data)} external tool preview images...")
    for t in tools_data:
        generate_tool_preview(t)
    print("All preview images generated successfully!")

if __name__ == "__main__":
    main()
