(function() {
    'use strict';

    /**
     * 开卷画布 · MeansCanvas 外部工具 6 大核心大类规范 (EXT_DEFAULT_GROUPS)
     */
    window.EXT_DEFAULT_GROUPS = [
    {
        "category": "AI 生图与设计",
        "tools": [
            "copilot",
            "reve",
            "grok",
            "agnes-wb",
            "qianwen",
            "topaz",
            "cloudcb",
            "canva",
            "brand-gen",
            "feralui",
            "gradient-lab",
            "flux-tools",
            "flux-precise",
            "artcraft"
        ]
    },
    {
        "category": "视频与动效",
        "tools": [
            "mindvideo",
            "minimax-h3",
            "cutia",
            "opencut",
            "codrops-gsap",
            "effect-app",
            "animos",
            "motion-dev"
        ]
    },
    {
        "category": "建筑与空间灵感",
        "tools": [
            "divisare",
            "kontextur",
            "recent-design",
            "brik-space",
            "brik-editor",
            "aholo3d",
            "intr-pattern",
            "tooooools",
            "digitiles",
            "pixel-perfect",
            "adam",
            "google-pics",
            "lovart",
            "bg-freebies"
        ]
    },
    {
        "category": "创意编程与实验",
        "tools": [
            "gflow",
            "asc11",
            "ascii",
            "tooootem",
            "ladybug",
            "shadergpt",
            "valessa",
            "gen-design",
            "openprocessing",
            "gen-gestaltung",
            "snitscanner",
            "spinespine",
            "gianluca-sketches",
            "pixelsynth",
            "ascii-magic",
            "dotforge",
            "brik-mousegrid"
        ]
    },
    {
        "category": "大模型与评测",
        "tools": [
            "chatgpt",
            "longcat",
            "dola",
            "mai",
            "sensenova",
            "arena",
            "artificial-lab",
            "design-arena",
            "boardmix",
            "fontbox",
            "duck-ai"
        ]
    },
    {
        "category": "工作流与 API",
        "tools": [
            "rh-canvas",
            "rh-user",
            "fal-ai",
            "aihubmix",
            "omniakey",
            "apikey-fun",
            "eachlabs",
            "merge-gateway"
        ]
    }
];

    /**
     * 开卷画布 · MeansCanvas 外部工具元数据字典 (EXT_TOOL_META)
     * 规范：遵循 AGENTS.md 极简性冷淡灰阶美学与零彩色 Emoji 准则。
     */
    window.EXT_TOOL_META = {
    "mai": {
        "id": "mai",
        "name": "MAI Playground",
        "nameZh": "MAI 体验站",
        "url": "https://playground.microsoft.ai/",
        "domain": "playground.microsoft.ai",
        "category": "大模型与评测",
        "desc": "微软新一代多模态 AI 交互体验平台，提供前沿生成式能力与灵感探索。",
        "preview": "/static/images/ext-previews/mai.png"
    },
    "copilot": {
        "id": "copilot",
        "name": "Copilot Imagine",
        "nameZh": "Copilot 生图",
        "url": "https://copilot.microsoft.com/imagine",
        "domain": "copilot.microsoft.com",
        "category": "AI 生图与设计",
        "desc": "微软智能生图工具，基于多模态大模型实现高拟真与创意风格视觉生成。",
        "preview": "/static/images/ext-previews/copilot.png"
    },
    "arena": {
        "id": "arena",
        "name": "Arena AI",
        "nameZh": "Arena AI",
        "url": "https://arena.ai/",
        "domain": "arena.ai",
        "category": "大模型与评测",
        "desc": "LMSYS 社区权威的大模型对决评测平台，实时盲测体验对比前沿模型表现。",
        "preview": "/static/images/ext-previews/arena.png"
    },
    "reve": {
        "id": "reve",
        "name": "Reve Image",
        "nameZh": "Reve 生图",
        "url": "https://reve.com/",
        "domain": "reve.com",
        "category": "AI 生图与设计",
        "desc": "专注于高概念艺术与创意摄影的生成式生图平台，提供细腻光影与质感。",
        "preview": "/static/images/ext-previews/reve.png"
    },
    "gflow": {
        "id": "gflow",
        "name": "Google Flow",
        "nameZh": "Google Flow",
        "url": "https://labs.google/fx/zh/tools/flow",
        "domain": "labs.google",
        "category": "创意编程与实验",
        "desc": "Google Labs 实验性生成工具，串联提示词与多模态创意流水线。",
        "preview": "/static/images/ext-previews/gflow.png"
    },
    "grok": {
        "id": "grok",
        "name": "Grok Imagine",
        "nameZh": "Grok Imagine",
        "url": "https://grok.com/imagine",
        "domain": "grok.com",
        "category": "AI 生图与设计",
        "desc": "xAI 实时生图与理解工具，具备强大真实感呈现与敏锐的上下文解析力。",
        "preview": "/static/images/ext-previews/grok.png"
    },
    "qianwen": {
        "id": "qianwen",
        "name": "Qianwen Create",
        "nameZh": "千问创作",
        "url": "https://create.qianwen.com/",
        "domain": "create.qianwen.com",
        "category": "AI 生图与设计",
        "desc": "阿里云通义千问官方内容创作中心，涵盖生图、文案与长文本生成。",
        "preview": "/static/images/ext-previews/qianwen.png"
    },
    "chatgpt": {
        "id": "chatgpt",
        "name": "ChatGPT",
        "nameZh": "ChatGPT 对话",
        "url": "https://chatgpt.com/",
        "domain": "chatgpt.com",
        "category": "大模型与评测",
        "desc": "OpenAI 旗舰对话助手，提供灵感推演、Prompt 精修与多轮创作顾问。",
        "preview": "/static/images/ext-previews/chatgpt.png"
    },
    "rh-canvas": {
        "id": "rh-canvas",
        "name": "RunningHub Canvas",
        "nameZh": "RunningHub 画布",
        "url": "https://rhtv.runninghub.cn/",
        "domain": "rhtv.runninghub.cn",
        "category": "工作流与 API",
        "desc": "云端开箱即用的 ComfyUI 流程画布，随时调用算力运行工业级生图工作流。",
        "preview": "/static/images/ext-previews/rh-canvas.png"
    },
    "rh-user": {
        "id": "rh-user",
        "name": "RunningHub User Center",
        "nameZh": "RunningHub 个人中心",
        "url": "https://runninghub.cn/",
        "domain": "runninghub.cn",
        "category": "工作流与 API",
        "desc": "RunningHub 算力与个人中心控制台，查看任务进度、API 授权与资产存储。",
        "preview": "/static/images/ext-previews/rh-user.png"
    },
    "cloudcb": {
        "id": "cloudcb",
        "name": "CloudCB",
        "nameZh": "CloudCB 图像编辑",
        "url": "https://cloudcb.me/",
        "domain": "cloudcb.me",
        "category": "AI 生图与设计",
        "desc": "轻量高效的在线图像后期与微调工具，支持快捷抠图、无损裁切与微调。",
        "preview": "/static/images/ext-previews/cloudcb.png"
    },
    "ascii": {
        "id": "ascii",
        "name": "ASCII Lab",
        "nameZh": "ASCII Lab",
        "url": "https://ascii-lab.sg.agentos-app.run/",
        "domain": "ascii-lab.sg.agentos-app.run",
        "category": "创意编程与实验",
        "desc": "将现代图像转码为 ASCII 字符画与终端风格纹理，探索纯粹文本的视觉张力。",
        "preview": "/static/images/ext-previews/ascii.png"
    },
    "ladybug": {
        "id": "ladybug",
        "name": "Ladybug FX",
        "nameZh": "Ladybug FX",
        "url": "https://app.theladybug.app/",
        "domain": "app.theladybug.app",
        "category": "创意编程与实验",
        "desc": "专为设计师打造的复古胶片、辉光与色差特效渲染器，赋予素材独特情绪。",
        "preview": "/static/images/ext-previews/ladybug.png"
    },
    "boardmix": {
        "id": "boardmix",
        "name": "Boardmix",
        "nameZh": "Boardmix 白板",
        "url": "https://boardmix.cn/",
        "domain": "boardmix.cn",
        "category": "大模型与评测",
        "desc": "综合型在线多人协作白板，集思维导图、流程图与团队研讨于一体。",
        "preview": "/static/images/ext-previews/boardmix.png"
    },
    "canva": {
        "id": "canva",
        "name": "Canva",
        "nameZh": "Canva",
        "url": "https://canva.com/",
        "domain": "canva.com",
        "category": "AI 生图与设计",
        "desc": "全功能云端视觉排版工具，拥有丰富的商用模板库与智能版式排版组件。",
        "preview": "/static/images/ext-previews/canva.png"
    },
    "longcat": {
        "id": "longcat",
        "name": "LongCat",
        "nameZh": "LongCat",
        "url": "https://longcat.chat/",
        "domain": "longcat.chat",
        "category": "大模型与评测",
        "desc": "极简轻盈的生成式对话工具，专注文案改写、灵感头脑风暴与指令构思。",
        "preview": "/static/images/ext-previews/longcat.png"
    },
    "dola": {
        "id": "dola",
        "name": "Dola",
        "nameZh": "Dola",
        "url": "https://dola.com/",
        "domain": "dola.com",
        "category": "大模型与评测",
        "desc": "基于自然语言的智能日程、计划与灵感捕获助手，随时整理记录创作灵感。",
        "preview": "/static/images/ext-previews/dola.png"
    },
    "agnes-wb": {
        "id": "agnes-wb",
        "name": "Agnes Workbench",
        "nameZh": "Agnes 工作台",
        "url": "https://agnes-image-gen.netlify.app/",
        "domain": "agnes-image-gen.netlify.app",
        "category": "AI 生图与设计",
        "desc": "敏捷的生成式图像调试工作台，便于快速探索不同 Prompt 变体与种子参数。",
        "preview": "/static/images/ext-previews/agnes-wb.png"
    },
    "lovart": {
        "id": "lovart",
        "name": "Lovart",
        "nameZh": "Lovart",
        "url": "https://lovart.ai/",
        "domain": "lovart.ai",
        "category": "建筑与空间灵感",
        "desc": "专为空间与视觉创作者设计的审美指导平台，输出精准的情绪板与风格建议。",
        "preview": "/static/images/ext-previews/lovart.png"
    },
    "topaz": {
        "id": "topaz",
        "name": "Topaz Studio",
        "nameZh": "Topaz Studio",
        "url": "https://topazlabs.com/",
        "domain": "topazlabs.com",
        "category": "AI 生图与设计",
        "desc": "业界领先的 AI 超分辨率与锐化处理平台，消除伪影并深度还原图像细节。",
        "preview": "/static/images/ext-previews/topaz.png"
    },
    "tooootem": {
        "id": "tooootem",
        "name": "Tooootem",
        "nameZh": "Tooootem",
        "url": "https://tooootem.vercel.app/",
        "domain": "tooootem.vercel.app",
        "category": "创意编程与实验",
        "desc": "前沿参数化艺术与分形图形生成器，探索算法几何与未来主义图案美学。",
        "preview": "/static/images/ext-previews/tooootem.png"
    },
    "feralui": {
        "id": "feralui",
        "name": "FeralUI Gradients",
        "nameZh": "FeralUI 渐变生成器",
        "url": "https://feralui.dev/gradients",
        "domain": "feralui.dev",
        "category": "AI 生图与设计",
        "desc": "免登录在线调配细腻的网格噪点、流动动效与和风传统色渐变，支持导出 SVG、PNG 与 MP4 视频。",
        "preview": "/static/images/ext-previews/feralui.png"
    },
    "valessa": {
        "id": "valessa",
        "name": "Valessa",
        "nameZh": "Valessa 3D 渲染",
        "url": "https://valessa.riotters.com/",
        "domain": "valessa.riotters.com",
        "category": "创意编程与实验",
        "desc": "Riotters 出品的 3D 产品视觉渲染平台，支持上传模型、自定义材质与光影运镜，秒级导出视频或图片。",
        "preview": "/static/images/ext-previews/valessa.png"
    },
    "google-pics": {
        "id": "google-pics",
        "name": "Google Pics",
        "nameZh": "Google Pics",
        "url": "https://docs.google.com/images/d/1cm3eiOdmL1Z-0ZDrzgWu4MjvxeWEAT05NRWT_dy7keI/edit?pli=1",
        "domain": "docs.google.com",
        "category": "建筑与空间灵感",
        "desc": "Google Docs 图片与画板素材协作库，便于团队沉淀与协同整理项目图片资产。",
        "preview": "/static/images/ext-previews/google-pics.png"
    },
    "mindvideo": {
        "id": "mindvideo",
        "name": "MindVideo",
        "nameZh": "MindVideo 创意工作室",
        "url": "https://www.mindvideo.ai/zh/creative-studio/",
        "domain": "mindvideo.ai",
        "category": "视频与动效",
        "desc": "新一代 AI 创意视频工作室，支持文本与图像驱动的高拟真运镜、影视级动态与视觉叙事。",
        "preview": "/static/images/ext-previews/mindvideo.png"
    },
    "gen-design": {
        "id": "gen-design",
        "name": "Generative Design",
        "nameZh": "Generative Design",
        "url": "http://www.generative-gestaltung.de/2/",
        "domain": "generative-gestaltung.de",
        "category": "创意编程与实验",
        "desc": "经典生成式设计与计算美学代码实验场，提供丰富的 P5.js 交互图形、算法分形与参数化视觉。",
        "preview": "/static/images/ext-previews/gen-design.png"
    },
    "shadergpt": {
        "id": "shadergpt",
        "name": "ShaderGPT",
        "nameZh": "ShaderGPT",
        "url": "https://shadergpt.14islands.com/1a1d14d3-9453-449e-be9d-d8477b22d825",
        "domain": "shadergpt.14islands.com",
        "category": "创意编程与实验",
        "desc": "14islands 出品的 WebGL 着色器 AI 生成器，支持自然语言实时调配 GLSL 动效与三维材质光影。",
        "preview": "/static/images/ext-previews/shadergpt.png"
    },
    "sensenova": {
        "id": "sensenova",
        "name": "SenseNova Workbench",
        "nameZh": "商汤日日新",
        "url": "https://unify.light-ai.top/home?model=u15-lite",
        "domain": "unify.light-ai.top",
        "category": "大模型与评测",
        "desc": "商汤日日新 SenseNova 统一交互体验平台，提供多元化生成式大模型与轻量化能力测试。",
        "preview": "/static/images/ext-previews/sensenova.png"
    },
    "fal-ai": {
        "id": "fal-ai",
        "name": "fal.ai",
        "nameZh": "fal.ai 开发者看板",
        "url": "https://fal.ai/dashboard",
        "domain": "fal.ai",
        "category": "工作流与 API",
        "desc": "面向下一代生成式媒体的极速推理云平台，提供 FLUX、SD3.5、Luma 等模型的高并发 API。",
        "preview": "/static/images/ext-previews/fal-ai.png"
    },
    "aihubmix": {
        "id": "aihubmix",
        "name": "AIHubMix",
        "nameZh": "AIHubMix 聚合平台",
        "url": "https://aihubmix.com/",
        "domain": "aihubmix.com",
        "category": "工作流与 API",
        "desc": "一站式主流大模型 API 聚合与分发网关，支持全球百余款顶尖 LLM 与多模态模型高速直连。",
        "preview": "/static/images/ext-previews/aihubmix.png"
    },
    "omniakey": {
        "id": "omniakey",
        "name": "OmniaKey",
        "nameZh": "OmniaKey 接口网关",
        "url": "https://omniakey.com/",
        "domain": "omniakey.com",
        "category": "工作流与 API",
        "desc": "面向开发者与创作者的通用 AI 密钥与路由聚合服务，提供高可用 OpenAI 标准接口中转。",
        "preview": "/static/images/ext-previews/omniakey.png"
    },
    "eachlabs": {
        "id": "eachlabs",
        "name": "EachLabs",
        "nameZh": "EachLabs 生成式 API",
        "url": "https://www.eachlabs.ai/",
        "domain": "eachlabs.ai",
        "category": "工作流与 API",
        "desc": "专注于图像、视频生成与视觉编辑的多模态 AI 开发者平台，支持灵活的工作流与微调接口。",
        "preview": "/static/images/ext-previews/eachlabs.png"
    },
    "apikey-fun": {
        "id": "apikey-fun",
        "name": "ApiKey.fun",
        "nameZh": "ApiKey.fun 分发站",
        "url": "https://apikey.fun/",
        "domain": "apikey.fun",
        "category": "工作流与 API",
        "desc": "高性价比的 AI 接口聚合与中转服务平台，多节点负载均衡，轻松调用主流商用大模型。",
        "preview": "/static/images/ext-previews/apikey-fun.png"
    },
    "merge-gateway": {
        "id": "merge-gateway",
        "name": "Merge Gateway",
        "nameZh": "Merge API 网关",
        "url": "https://gateway.merge.dev/",
        "domain": "gateway.merge.dev",
        "category": "工作流与 API",
        "desc": "面向团队与企业的统一 AI API 接入与路由网关，集中管控调用配额、审计与接口安全。",
        "preview": "/static/images/ext-previews/merge-gateway.png"
    },
    "animos": {
        "id": "animos",
        "name": "Animos",
        "nameZh": "Animos 动效设计",
        "url": "https://animos.app/editor",
        "domain": "animos.app",
        "category": "视频与动效",
        "desc": "面向设计展示的在线动态模板与动效编辑器，快速制作高质感产品演示与镜头转场。",
        "preview": "/static/images/ext-previews/animos.png"
    },
    "brand-gen": {
        "id": "brand-gen",
        "name": "Brand Generator",
        "nameZh": "Brand Generator 品牌资产",
        "url": "https://brand-generator.stoyanov.works/",
        "domain": "brand-generator.stoyanov.works",
        "category": "AI 生图与设计",
        "desc": "Stoyanov Works 出品的品牌资产生成器，基于参数与色彩系统自动生成整套品牌视觉体系。",
        "preview": "/static/images/ext-previews/brand-gen.png"
    },
    "adam": {
        "id": "adam",
        "name": "Adam",
        "nameZh": "Adam 硬件设计 Copilot",
        "url": "https://adam.new/",
        "domain": "adam.new",
        "category": "建筑与空间灵感",
        "desc": "面向硬件团队与工业工程师的 AI CAD 智能副驾驶，自然语言辅助三维构件推演与机械设计。",
        "preview": "/static/images/ext-previews/adam.png"
    },
    "cutia": {
        "id": "cutia",
        "name": "Cutia",
        "nameZh": "Cutia 在线剪辑",
        "url": "https://cutia.msgbyte.com/zh",
        "domain": "cutia.msgbyte.com",
        "category": "视频与动效",
        "desc": "轻量高效的开源网页端在线音视频剪辑器，具备多轨道时间轴、特效字幕与实时回放。",
        "preview": "/static/images/ext-previews/cutia.png"
    },
    "opencut": {
        "id": "opencut",
        "name": "OpenCut",
        "nameZh": "OpenCut 视频编辑",
        "url": "https://opencut.app/",
        "domain": "opencut.app",
        "category": "视频与动效",
        "desc": "现代开源 Web 视频编辑平台，完全在浏览器本地处理，隐私安全，无水印极速导出。",
        "preview": "/static/images/ext-previews/opencut.png"
    },
    "motion-dev": {
        "id": "motion-dev",
        "name": "Motion",
        "nameZh": "Motion 动效库",
        "url": "https://motion.dev/",
        "domain": "motion.dev",
        "category": "视频与动效",
        "desc": "现代 Web 旗舰级声明式动画与动效引擎，提供高流畅度弹簧物理动效、滚动视差与手势交互。",
        "preview": "/static/images/ext-previews/motion-dev.png"
    },
    "minimax-h3": {
        "id": "minimax-h3",
        "name": "MiniMax H3-Max",
        "nameZh": "MiniMax H3-Max",
        "url": "https://fal.ai/models/minimax/h3-max/image-to-video",
        "domain": "fal.ai",
        "category": "视频与动效",
        "desc": "MiniMax 顶尖图生视频模型 H3-Max（fal.ai 部署版），具备强大物理规律仿真与电影级运镜。",
        "preview": "/static/images/ext-previews/minimax-h3.png"
    },
    "openprocessing": {
        "id": "openprocessing",
        "name": "OpenProcessing",
        "nameZh": "OpenProcessing 创意编程",
        "url": "https://openprocessing.org/",
        "domain": "openprocessing.org",
        "category": "创意编程与实验",
        "desc": "全球领先的 p5.js 与 Processing 计算艺术社区，在线编写、探索与分享参数化算法视觉。",
        "preview": "/static/images/ext-previews/openprocessing.png"
    },
    "gen-gestaltung": {
        "id": "gen-gestaltung",
        "name": "Generative Gestaltung",
        "nameZh": "Generative Gestaltung",
        "url": "http://www.generative-gestaltung.de/",
        "domain": "generative-gestaltung.de",
        "category": "创意编程与实验",
        "desc": "生成式设计经典著作《Generative Gestaltung》官方主页，探索算法图形、复杂排版与计算美学。",
        "preview": "/static/images/ext-previews/gen-gestaltung.png"
    },
    "recent-design": {
        "id": "recent-design",
        "name": "Recent Design",
        "nameZh": "Recent Design 灵感库",
        "url": "https://recent.design",
        "domain": "recent.design",
        "category": "建筑与空间灵感",
        "desc": "精选全球前沿工作室与独立设计师的数字产品、品牌与交互作品，捕捉即时设计灵感与视觉趋势。",
        "preview": "/static/images/ext-previews/recent-design.png"
    },
    "codrops-gsap": {
        "id": "codrops-gsap",
        "name": "Codrops GSAP",
        "nameZh": "Codrops GSAP 动效库",
        "url": "https://tympanus.net/codrops/hub/tag/gsap/",
        "domain": "tympanus.net",
        "category": "视频与动效",
        "desc": "Codrops 出品的 GSAP Web 动效精选案例与前沿实验库，汇聚全球创意交互与动效源码。",
        "preview": "/static/images/ext-previews/codrops-gsap.png"
    },
    "artificial-lab": {
        "id": "artificial-lab",
        "name": "Artificial Analysis",
        "nameZh": "Image Lab 画质评测",
        "url": "https://artificialanalysis.ai/image/image-lab",
        "domain": "artificialanalysis.ai",
        "category": "大模型与评测",
        "desc": "权威独立的 AI 生图模型竞技场与综合画质评测室，支持实时盲测与前沿排位榜单。",
        "preview": "/static/images/ext-previews/artificial-lab.png"
    },
    "brik-space": {
        "id": "brik-space",
        "name": "Brik Space",
        "nameZh": "Brik Space 画廊",
        "url": "https://brik.space/gallery",
        "domain": "brik.space",
        "category": "建筑与空间灵感",
        "desc": "前沿数字艺术与 3D 空间创意画廊，呈现高概念视觉叙事与实验性作品。",
        "preview": "/static/images/ext-previews/brik-space.png"
    },
    "asc11": {
        "id": "asc11",
        "name": "ASC11",
        "nameZh": "ASC11 字符艺术",
        "url": "https://asc11.com/",
        "domain": "asc11.com",
        "category": "创意编程与实验",
        "desc": "极简前卫的 ASCII 字符艺术与复古计算机图形实验生成平台。",
        "preview": "/static/images/ext-previews/asc11.png"
    },
    "design-arena": {
        "id": "design-arena",
        "name": "Design Arena",
        "nameZh": "Design Arena 竞技场",
        "url": "https://www.designarena.ai/",
        "domain": "designarena.ai",
        "category": "大模型与评测",
        "desc": "专注于 UI/UX 与生成式设计的 AI 模型对决与盲测排位平台。",
        "preview": "/static/images/ext-previews/design-arena.png"
    },
    "snitscanner": {
        "id": "snitscanner",
        "name": "Snit Scanner",
        "nameZh": "Snit Scanner 扫描仪",
        "url": "https://snitscanner.xyz/",
        "domain": "snitscanner.xyz",
        "category": "创意编程与实验",
        "desc": "趣味互动式数字扫描与故障艺术发生器，模拟机械扫描推拉质感。",
        "preview": "/static/images/ext-previews/snitscanner.png"
    },
    "spinespine": {
        "id": "spinespine",
        "name": "Spine Tools",
        "nameZh": "Spine 曲线工具",
        "url": "https://www.spinespinespine.tools/",
        "domain": "spinespinespine.tools",
        "category": "创意编程与实验",
        "desc": "专注于动态脊线、骨骼拓扑与有机流体曲线的生成式设计工具。",
        "preview": "/static/images/ext-previews/spinespine.png"
    },
    "intr-pattern": {
        "id": "intr-pattern",
        "name": "INTR Pattern",
        "nameZh": "INTR 纹理生成器",
        "url": "https://wangxian.work/tools/intr-tools/INTR-PATTERN.html",
        "domain": "wangxian.work",
        "category": "建筑与空间灵感",
        "desc": "王宪工作室出品的参数化交互图案与几何网格纹样生成工具。",
        "preview": "/static/images/ext-previews/intr-pattern.png"
    },
    "tooooools": {
        "id": "tooooools",
        "name": "Tooooools",
        "nameZh": "Tooooools 工具库",
        "url": "https://www.tooooools.app/",
        "domain": "tooooools.app",
        "category": "建筑与空间灵感",
        "desc": "精选创意设计工具、排版辅助与视觉生成器的高质量导航站。",
        "preview": "/static/images/ext-previews/tooooools.png"
    },
    "effect-app": {
        "id": "effect-app",
        "name": "Effect App",
        "nameZh": "Effect 动效探索",
        "url": "https://effect.app/explore",
        "domain": "effect.app",
        "category": "视频与动效",
        "desc": "前沿 WebGL / 节点式实时动效滤镜与视觉合成创意社区。",
        "preview": "/static/images/ext-previews/effect-app.png"
    },
    "gianluca-sketches": {
        "id": "gianluca-sketches",
        "name": "Gianluca Sketches",
        "nameZh": "Gianluca 创意编程草图",
        "url": "https://www.gianluca.club/sketches",
        "domain": "gianluca.club",
        "category": "创意编程与实验",
        "desc": "独立设计师 Gianluca 的创意编程草图与动态几何交互实验集。",
        "preview": "/static/images/ext-previews/gianluca-sketches.png"
    },
    "digitiles": {
        "id": "digitiles",
        "name": "Digitiles",
        "nameZh": "Digitiles 瓷砖排布",
        "url": "https://eduardadu.github.io/Digitiles/create.html",
        "domain": "eduardadu.github.io",
        "category": "建筑与空间灵感",
        "desc": "模块化数字瓷砖与图案自相似拼贴生成器，探索几何铺装律动。",
        "preview": "/static/images/ext-previews/digitiles.png"
    },
    "pixelsynth": {
        "id": "pixelsynth",
        "name": "PixelSynth",
        "nameZh": "PixelSynth 图像发声器",
        "url": "https://pixelsynth.com/",
        "domain": "pixelsynth.com",
        "category": "创意编程与实验",
        "desc": "基于图像灰度与线条的光谱音频合成器，将像素转化为声音振动。",
        "preview": "/static/images/ext-previews/pixelsynth.png"
    },
    "fontbox": {
        "id": "fontbox",
        "name": "FontBox",
        "nameZh": "FontBox 字体推敲",
        "url": "https://fontbox.barcoloudly.com/",
        "domain": "barcoloudly.com",
        "category": "大模型与评测",
        "desc": "优雅直观的字体排印推敲与字形对比工具，快速预览字重与韵律。",
        "preview": "/static/images/ext-previews/fontbox.png"
    },
    "pixel-perfect": {
        "id": "pixel-perfect",
        "name": "Pixel Perfect",
        "nameZh": "Pixel Perfect 空间",
        "url": "https://www.pixel-perfect.space/",
        "domain": "pixel-perfect.space",
        "category": "建筑与空间灵感",
        "desc": "极致性冷淡网格与像素级精度的当代视觉作品归档空间。",
        "preview": "/static/images/ext-previews/pixel-perfect.png"
    },
    "divisare": {
        "id": "divisare",
        "name": "Divisare",
        "nameZh": "Divisare 建筑宝典",
        "url": "https://www.divisare.com",
        "domain": "divisare.com",
        "category": "建筑与空间灵感",
        "desc": "全球顶级当代建筑、室内空间与空间摄影文献集与视觉图库。",
        "preview": "/static/images/ext-previews/divisare.png"
    },
    "kontextur": {
        "id": "kontextur",
        "name": "Kontextur",
        "nameZh": "Kontextur 建筑名录",
        "url": "https://kontextur.info/studiolists",
        "domain": "kontextur.info",
        "category": "建筑与空间灵感",
        "desc": "汇聚全球前沿建筑事务所、批判性对话与先锋设计实践的索引名录。",
        "preview": "/static/images/ext-previews/kontextur.png"
    },
    "gradient-lab": {
        "id": "gradient-lab",
        "name": "Gradient Lab",
        "nameZh": "Gradient Lab 渐变工坊",
        "url": "https://backgrounds.supply/gradient-lab",
        "domain": "backgrounds.supply",
        "category": "AI 生图与设计",
        "desc": "强大的多重渐变生成与色彩微调工坊，支持平滑混合与高品质背景导出。",
        "preview": "/static/images/ext-previews/gradient-lab.png"
    },
    "bg-freebies": {
        "id": "bg-freebies",
        "name": "Backgrounds Freebies",
        "nameZh": "Backgrounds 免费背景素材",
        "url": "https://backgrounds.supply/freebies",
        "domain": "backgrounds.supply",
        "category": "建筑与空间灵感",
        "desc": "高品质免费背景素材与肌理库，提供细腻的几何、渐变与抽象底纹下载。",
        "preview": "/static/images/ext-previews/bg-freebies.png"
    },
    "ascii-magic": {
        "id": "ascii-magic",
        "name": "ASCII Magic",
        "nameZh": "ASCII Magic 字符画转换",
        "url": "https://www.ascii-magic.com/",
        "domain": "ascii-magic.com",
        "category": "创意编程与实验",
        "desc": "纯粹优雅的 ASCII 字符画与文本艺术转换工具，支持图像快速转译为复古字符。",
        "preview": "/static/images/ext-previews/ascii-magic.png"
    },
    "dotforge": {
        "id": "dotforge",
        "name": "DotForge",
        "nameZh": "DotForge 点阵工坊",
        "url": "https://dotforge.vercel.app/",
        "domain": "dotforge.vercel.app",
        "category": "创意编程与实验",
        "desc": "基于点阵粒子与像素网格的创意生成器，定制可调点距与动态点阵视觉。",
        "preview": "/static/images/ext-previews/dotforge.png"
    },
    "duck-ai": {
        "id": "duck-ai",
        "name": "Duck.ai",
        "nameZh": "Duck.ai 隐私 AI 对话",
        "url": "https://duck.ai/",
        "domain": "duck.ai",
        "category": "大模型与评测",
        "desc": "DuckDuckGo 打造的匿名无痕多模型 AI 对话平台，安全保护对话隐私与创意想法。",
        "preview": "/static/images/ext-previews/duck-ai.png"
    },
    "flux-tools": {
        "id": "flux-tools",
        "name": "FLUX Tools",
        "nameZh": "FLUX 官方工具箱",
        "url": "https://flux-tools.bfl.ai/",
        "domain": "flux-tools.bfl.ai",
        "category": "AI 生图与设计",
        "desc": "Black Forest Labs 官方 FLUX 视觉工具套件，支持智能扩图、局部擦除重绘与结构控制。",
        "preview": "/static/images/ext-previews/flux-tools.png"
    },
    "flux-precise": {
        "id": "flux-precise",
        "name": "FLUX Precise Editing",
        "nameZh": "FLUX 精准编辑",
        "url": "https://flux-tools.bfl.ai/precise-editing",
        "domain": "flux-tools.bfl.ai",
        "category": "AI 生图与设计",
        "desc": "Black Forest Labs 出品的 FLUX 精准图像编辑工作台，支持精细局部重绘、元素替换与光影微调。",
        "preview": "/static/images/ext-previews/flux-precise.png"
    },
    "brik-editor": {
        "id": "brik-editor",
        "name": "Brik Tool Editor",
        "nameZh": "Brik 工具编辑器",
        "url": "https://brik.space/tooleditor/6ac799b728cbfe67305e50bf",
        "domain": "brik.space",
        "category": "建筑与空间灵感",
        "desc": "Brik 创意设计工具构建与实时参数调优编辑器，定制专属交互式生成工具。",
        "preview": "/static/images/ext-previews/brik-editor.png"
    },
    "brik-mousegrid": {
        "id": "brik-mousegrid",
        "name": "Brik MouseGrid",
        "nameZh": "Brik 鼠标网格交互",
        "url": "https://brik.space/toolviewer?slug=mousegrid-mo0453fe",
        "domain": "brik.space",
        "category": "创意编程与实验",
        "desc": "Brik 社区出品的 MouseGrid 交互式动态网格工具，随鼠标轨迹实时触发几何与色彩形态演化。",
        "preview": "/static/images/ext-previews/brik-mousegrid.png"
    },
    "aholo3d": {
        "id": "aholo3d",
        "name": "Aholo 3D",
        "nameZh": "Aholo 空间智能平台",
        "url": "https://www.aholo3d.cn/",
        "domain": "aholo3d.cn",
        "category": "建筑与空间灵感",
        "desc": "Aholo 空间智能开放平台，支持高保真 3DGS 实景重建、AI 空间生成、实时云端编辑与三维世界构建。",
        "preview": "/static/images/ext-previews/aholo3d.png"
    },
    "artcraft": {
        "id": "artcraft",
        "name": "ArtCraft",
        "nameZh": "ArtCraft 视觉工作台",
        "url": "https://app.getartcraft.com/",
        "domain": "app.getartcraft.com",
        "category": "AI 生图与设计",
        "desc": "ArtCraft 一体化 AI 视觉与三维创作工作台，涵盖文生图、视频生成、3D 世界构建与情绪板合成。",
        "preview": "/static/images/ext-previews/artcraft.png"
    }
};
})();

