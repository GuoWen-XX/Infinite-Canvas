/**
 * Infinite-Canvas - Space Creation Agent (Canvas Creation Agent)
 *
 * Left-docked collapsible Agent drawer providing:
 * - Conversational ideas and prompt refinement
 * - Tool-dispatched image generation via /api/chat/agent
 * - Contextual awareness of selected canvas nodes & multi-node references
 * - Floating @ mention menu to reference canvas image and prompt nodes
 * - One-click & auto write-back into canvas nodes with workflow lineage auto-linking
 * - Multi-modal Vision interrogation ("反推提示词") and structured prompt extraction
 */

(function () {
    'use strict';

    let agentPanel = null;
    let agentToggleBtn = null;
    let agentDockTrigger = null;
    let agentDockSideBtn = null;
    let agentCloseBtn = null;
    let agentNewBtn = null;
    let agentMessagesEl = null;
    let agentInputEl = null;
    let agentSendBtn = null;
    let agentProviderSelect = null;
    let agentModelSelect = null;
    let agentContextBar = null;
    let agentContextChips = null;
    let agentInterrogateBtn = null;
    let agentExtractAtmosphereBtn = null;
    let agentContextClearAllBtn = null;
    let agentMentionMenu = null;
    let agentMentionList = null;
    let agentMentionCount = null;
    let agentMentionBtn = null;
    let agentAutoPlaceCheckbox = null;
    let agentFileInput = null;

    let conversationId = '';
    let isGenerating = false;
    const referencedNodes = new Map(); // id -> { id, type, name, url, text, x, y, w, h }
    let uploadedReference = null;
    let lastSelectedId = null;

    // Mention floating menu state
    let isMentionMenuOpen = false;
    let mentionCandidates = [];
    let mentionActiveIndex = 0;
    let mentionQuery = '';
    let mentionMatchStartIndex = -1;

    function tr(key, fallback = '') {
        return (window.StudioI18n ? window.StudioI18n.t(key) : key) || fallback || key;
    }

    function escapeHtml(text) {
        return String(text || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function showAgentToast(message) {
        let toast = document.getElementById('agentToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'agentToast';
            toast.className = 'agent-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('visible');
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => {
            toast.classList.remove('visible');
        }, 2200);
    }

    let activeAbortController = null;

    function abortPendingRequest() {
        if (activeAbortController) {
            try {
                activeAbortController.abort();
            } catch (_) {}
            activeAbortController = null;
        }
        if (isGenerating) {
            isGenerating = false;
            removeThinkingMessage();
            agentSendBtn?.classList.remove('loading');
            if (agentSendBtn) {
                agentSendBtn.disabled = false;
                agentSendBtn.title = '';
            }
        }
    }

    let cachedProviders = null;

    async function fetchProvidersAsync() {
        try {
            const res = await fetch('/api/providers');
            if (res.ok) {
                const data = await res.json();
                const all = data.providers || [];
                const chatList = all.filter(p => p.enabled !== false && (p.chat_models || []).length);
                if (chatList.length) {
                    cachedProviders = chatList;
                    return chatList;
                }
            }
        } catch (_) {}
        return null;
    }

    function getProviders() {
        if (cachedProviders && cachedProviders.length) return cachedProviders;
        if (typeof window.chatApiProviders === 'function') {
            const list = window.chatApiProviders();
            if (list && list.length && list[0].id !== 'comfly') return list;
        }
        if (typeof window.apiProviders !== 'undefined' && Array.isArray(window.apiProviders) && window.apiProviders.length) {
            const list = window.apiProviders.filter(p => p.enabled !== false && (p.chat_models || []).length);
            if (list.length) return list;
        }
        return [
            { id: 'gemini-cli', name: 'Antigravity CLI', chat_models: ['gemini-2.5-flash', 'gemini-2.5-pro', 'auto'] },
            { id: 'modelscope', name: 'ModelScope', chat_models: ['Qwen/Qwen3-235B-A22B', 'Qwen/Qwen3-VL-235B-A22B-Instruct'] }
        ];
    }

    async function populateProviders() {
        if (!agentProviderSelect) return;
        let providers = getProviders();
        if (!cachedProviders) {
            const remote = await fetchProvidersAsync();
            if (remote && remote.length) {
                providers = remote;
            }
        }
        // Ensure Antigravity CLI is prioritized
        providers.sort((a, b) => (a.id === 'gemini-cli' ? -1 : b.id === 'gemini-cli' ? 1 : 0));

        const savedProvider = localStorage.getItem('canvas_agent_provider') || '';
        const isPinnedV3 = localStorage.getItem('canvas_agent_provider_pinned_v3') === '1';
        const hasGeminiCli = providers.some(p => p.id === 'gemini-cli');

        let activeId = '';
        if (isPinnedV3 && savedProvider && providers.some(p => p.id === savedProvider)) {
            activeId = savedProvider;
        } else if (hasGeminiCli) {
            activeId = 'gemini-cli';
            localStorage.setItem('canvas_agent_provider_pinned_v3', '1');
            localStorage.setItem('canvas_agent_provider', 'gemini-cli');
        } else {
            activeId = providers[0]?.id || '';
            localStorage.setItem('canvas_agent_provider_pinned_v3', '1');
            localStorage.setItem('canvas_agent_provider', activeId);
        }

        agentProviderSelect.innerHTML = providers.map(p => `
            <option value="${escapeHtml(p.id)}" ${p.id === activeId ? 'selected' : ''}>
                ${escapeHtml(p.name || p.id)}
            </option>
        `).join('');

        populateModels();
    }

    function populateModels() {
        if (!agentProviderSelect || !agentModelSelect) return;
        const providerId = agentProviderSelect.value;
        const providers = getProviders();
        const current = providers.find(p => p.id === providerId);
        const models = (current && current.chat_models && current.chat_models.length)
            ? current.chat_models
            : ['default'];

        const savedModel = localStorage.getItem(`canvas_agent_model_${providerId}`) || models[0];
        const activeModel = models.includes(savedModel) ? savedModel : models[0];
        agentModelSelect.innerHTML = models.map(m => `
            <option value="${escapeHtml(m)}" ${m === activeModel ? 'selected' : ''}>
                ${escapeHtml(m)}
            </option>
        `).join('');
    }

    function toggleAgentDrawer(forceOpen) {
        if (!agentPanel) return;
        const isOpen = typeof forceOpen === 'boolean' ? forceOpen : !agentPanel.classList.contains('open');
        if (isOpen) {
            agentPanel.classList.add('open');
            agentToggleBtn?.classList.add('active');
            agentDockTrigger?.classList.add('hidden');
            localStorage.setItem('canvas_agent_open', '1');
            pollCanvasSelection();
            setTimeout(() => {
                agentInputEl?.focus();
                scrollMessagesToBottom();
            }, 100);
        } else {
            agentPanel.classList.remove('open');
            agentToggleBtn?.classList.remove('active');
            agentDockTrigger?.classList.remove('hidden');
            localStorage.setItem('canvas_agent_open', '0');
            closeMentionMenu();
        }
    }

    function scrollMessagesToBottom() {
        if (agentMessagesEl) {
            agentMessagesEl.scrollTop = agentMessagesEl.scrollHeight;
        }
    }

    function applyDockSide(side) {
        const isRight = side === 'right';
        if (agentPanel) {
            agentPanel.classList.toggle('dock-right', isRight);
            agentPanel.classList.toggle('dock-left', !isRight);
        }
        if (agentDockTrigger) {
            agentDockTrigger.classList.toggle('dock-right', isRight);
            agentDockTrigger.classList.toggle('dock-left', !isRight);
        }
        if (agentDockSideBtn) {
            agentDockSideBtn.title = isRight ? '切换至左侧停靠 (Alt+S)' : '切换至右侧停靠 (Alt+S)';
            agentDockSideBtn.setAttribute('aria-label', agentDockSideBtn.title);
            agentDockSideBtn.innerHTML = '<i data-lucide="arrow-left-right" class="w-4 h-4"></i>';
            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons();
            }
        }
        localStorage.setItem('canvas_agent_dock', isRight ? 'right' : 'left');
        localStorage.setItem('canvas_agent_dock_v2', '1');
    }

    // =========================================================================
    // Multi-Node Context & Chips
    // =========================================================================

    function renderContextChips() {
        if (!agentContextBar || !agentContextChips) return;
        agentContextChips.innerHTML = '';

        const items = [];
        if (uploadedReference) {
            items.push({
                id: '__uploaded__',
                type: 'image',
                url: uploadedReference.url,
                name: uploadedReference.name || '上传参考图',
                isUpload: true
            });
        }
        for (const node of referencedNodes.values()) {
            items.push(node);
        }

        if (items.length === 0) {
            agentContextBar.style.display = 'none';
            return;
        }

        agentContextBar.style.display = 'block';

        items.forEach(item => {
            const chip = document.createElement('div');
            chip.className = 'agent-context-chip';
            if (!chip.dataset) chip.dataset = {};
            chip.dataset.id = item.id;

            const isImg = item.type === 'image' && Boolean(item.url);
            const tagText = item.isUpload ? '上传参考' : (item.type === 'image' ? '图片节点' : '提示词节点');
            const displayName = isImg ? (item.name || '图片') : (item.text || item.name || '提示词');

            let visualHtml = '';
            if (isImg) {
                visualHtml = `<img class="agent-context-thumb" src="${escapeHtml(item.url)}" alt="thumb">`;
            } else {
                visualHtml = `<div class="agent-context-icon"><i data-lucide="type" class="w-3.5 h-3.5"></i></div>`;
            }

            chip.innerHTML = `
                ${visualHtml}
                <div class="agent-context-meta">
                    <span class="agent-context-tag">${escapeHtml(tagText)}</span>
                    <span class="agent-context-name" title="${escapeHtml(displayName)}">${escapeHtml(displayName)}</span>
                </div>
                <button class="agent-context-close" type="button" title="移除参考" data-remove-id="${escapeHtml(item.id)}">
                    <i data-lucide="x" class="w-3 h-3"></i>
                </button>
            `;

            chip.querySelector('.agent-context-close')?.addEventListener('click', (e) => {
                e.stopPropagation();
                if (item.id === '__uploaded__') {
                    uploadedReference = null;
                } else {
                    referencedNodes.delete(item.id);
                }
                renderContextChips();
            });

            agentContextChips.appendChild(chip);
        });

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    function addReferencedNode(node) {
        if (!node || !node.id) return;
        referencedNodes.set(node.id, {
            id: node.id,
            type: node.type || 'image',
            name: node.name || (node.type === 'image' ? '图片节点' : '提示词节点'),
            url: node.url || '',
            text: node.text || '',
            x: node.x,
            y: node.y,
            w: node.w,
            h: node.h
        });
        renderContextChips();
    }

    function clearLinkedContext() {
        referencedNodes.clear();
        uploadedReference = null;
        lastSelectedId = null;
        renderContextChips();
    }

    function pollCanvasSelection() {
        if (!agentPanel || !agentPanel.classList.contains('open')) return;
        try {
            if (typeof window.selected !== 'undefined' && typeof window.nodes !== 'undefined') {
                const sel = window.selected;
                const allNodes = window.nodes || [];
                if (sel && sel.size === 1) {
                    const id = [...sel][0];
                    if (id !== lastSelectedId) {
                        lastSelectedId = id;
                        // If user has not manually configured context, sync single-selection
                        if (referencedNodes.size === 0 && !uploadedReference) {
                            const target = allNodes.find(n => n.id === id);
                            if (target && ((target.type === 'image' && target.url) || (target.type === 'prompt' && target.text))) {
                                addReferencedNode(target);
                            }
                        }
                    }
                } else if (sel && sel.size === 0) {
                    if (lastSelectedId !== null) {
                        lastSelectedId = null;
                    }
                }
            }
        } catch (e) {}
    }

    // =========================================================================
    // Floating @ Mention Menu
    // =========================================================================

    function getMentionCandidates(query) {
        const allNodes = (typeof window.nodes !== 'undefined' && Array.isArray(window.nodes)) ? window.nodes : [];
        const q = (query || '').toLowerCase().trim();
        return allNodes.filter(n => {
            if (n.type === 'image' && n.url) {
                if (!q) return true;
                return (n.name || '').toLowerCase().includes(q) || (n.prompt || '').toLowerCase().includes(q);
            }
            if (n.type === 'prompt' && (n.text || n.name)) {
                if (!q) return true;
                return (n.text || '').toLowerCase().includes(q) || (n.name || '').toLowerCase().includes(q);
            }
            return false;
        });
    }

    function openMentionMenu(query, matchIndex) {
        if (!agentMentionMenu || !agentMentionList) return;
        mentionQuery = query;
        mentionMatchStartIndex = matchIndex;
        mentionCandidates = getMentionCandidates(query);
        mentionActiveIndex = 0;

        renderMentionList();
        agentMentionMenu.style.display = 'flex';
        isMentionMenuOpen = true;
    }

    function closeMentionMenu() {
        if (!agentMentionMenu) return;
        agentMentionMenu.style.display = 'none';
        isMentionMenuOpen = false;
        mentionCandidates = [];
        mentionMatchStartIndex = -1;
    }

    function renderMentionList() {
        if (!agentMentionList) return;
        agentMentionList.innerHTML = '';

        if (agentMentionCount) {
            agentMentionCount.textContent = `${mentionCandidates.length} 个候选`;
        }

        if (mentionCandidates.length === 0) {
            agentMentionList.innerHTML = `<div class="agent-mention-empty">无匹配的画布图片或提示词节点</div>`;
            return;
        }

        mentionCandidates.forEach((n, idx) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = `agent-mention-item ${idx === mentionActiveIndex ? 'active' : ''}`;
            if (!item.dataset) item.dataset = {};
            item.dataset.index = idx;

            const isImg = n.type === 'image';
            const title = isImg ? (n.name || '图片节点') : (n.text ? n.text.slice(0, 36) : (n.name || '提示词节点'));
            const badge = isImg ? '图片节点' : '提示词节点';
            const isReferenced = referencedNodes.has(n.id);

            let iconHtml = '';
            if (isImg) {
                iconHtml = `<img class="agent-mention-thumb" src="${escapeHtml(n.url)}" alt="node">`;
            } else {
                iconHtml = `<div class="agent-mention-icon"><i data-lucide="type" class="w-4 h-4"></i></div>`;
            }

            item.innerHTML = `
                ${iconHtml}
                <div class="agent-mention-info">
                    <span class="agent-mention-title">${escapeHtml(title)}</span>
                    <span class="agent-mention-badge">${badge}${isReferenced ? ' · 已引用' : ''}</span>
                </div>
            `;

            item.addEventListener('click', (e) => {
                e.stopPropagation();
                selectMentionCandidate(n);
            });

            agentMentionList.appendChild(item);
        });

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    function updateMentionHighlight() {
        if (!agentMentionList) return;
        const items = agentMentionList.querySelectorAll('.agent-mention-item');
        items.forEach((item, idx) => {
            if (idx === mentionActiveIndex) {
                item.classList.add('active');
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove('active');
            }
        });
    }

    function selectMentionCandidate(node) {
        if (!node) return;
        addReferencedNode(node);

        if (agentInputEl && mentionMatchStartIndex >= 0) {
            const full = agentInputEl.value;
            const before = full.slice(0, mentionMatchStartIndex);
            const afterCursor = full.slice(agentInputEl.selectionStart);
            const nodeName = node.name || (node.type === 'image' ? '图片' : '提示词');
            const inserted = `@${nodeName} `;
            agentInputEl.value = before + inserted + afterCursor;
            const newCursorPos = before.length + inserted.length;
            agentInputEl.setSelectionRange(newCursorPos, newCursorPos);
            agentInputEl.focus();
        }

        closeMentionMenu();
    }

    // =========================================================================
    // "反推提示词" (Multi-modal Vision Interrogation)
    // =========================================================================

    function handleInterrogate() {
        let targetImage = null;
        for (const node of referencedNodes.values()) {
            if (node.type === 'image' && node.url) {
                targetImage = node;
                break;
            }
        }
        if (!targetImage && uploadedReference && uploadedReference.url) {
            targetImage = uploadedReference;
        }

        if (!targetImage) {
            showAgentToast('请先在画布中选中或通过 @ 引用一张图片');
            return;
        }

        const interrogatePrompt = `You are a top-tier architectural visual director and AI prompt reverse-engineering master. Please perform an in-depth visual analysis on the reference image and output reverse-engineered prompt data strictly following the JSON format below. Ensure the prompt captures all materials, lighting, perspective, and composition.

Output Format: JSON Code Block only.
{
  "visual_analysis": {
    "subject": "Core spatial/architectural subject and geometry",
    "composition": "Camera angle, perspective, framing, shot type",
    "lighting_and_atmosphere": "Light direction, natural/artificial balance, color temperature, atmospheric haze",
    "materials_and_textures": "Exposed concrete, warm timber, glass, steel, stone, etc.",
    "color_palette": {
      "dominant": ["Dominant color 1", "Dominant color 2"],
      "accent": ["Accent color 1"],
      "overall_tone": "Warm neutral, high contrast, cinematic, etc."
    }
  },
  "prompt_zh": "提炼一段高精度、结构化的中文生图提示词，详细包含主体特征、空间尺度、材质肌理、光影层次与渲染品质",
  "prompt_en": "A master-grade, photorealistic English prompt for Midjourney / SD / Flux / Recraft, complete with camera optics (e.g. 35mm, f/8, natural daylight) and spatial materiality",
  "negative_prompt": "blurry, distorted geometry, oversaturated, amateur photography, low quality",
  "derivative_suggestions": [
    "Derivative direction 1: Night/dusk lighting variation with warm interior glow",
    "Derivative direction 2: Close-up material vignette emphasizing textures",
    "Derivative direction 3: Aerial bird's eye masterplan perspective"
  ]
}`;

        showAgentToast('正在以 JSON 结构反推视觉特征与提示词...');
        sendAgentMessage(interrogatePrompt);
    }

    function handleExtractAtmosphere() {
        let targetImage = null;
        for (const node of referencedNodes.values()) {
            if (node.type === 'image' && node.url) {
                targetImage = node;
                break;
            }
        }
        if (!targetImage && uploadedReference && uploadedReference.url) {
            targetImage = uploadedReference;
        }
        if (!targetImage && window.selected && window.selected.size === 1 && window.nodes) {
            const selId = [...window.selected][0];
            const selNode = window.nodes.find(n => n.id === selId && n.type === 'image' && n.url);
            if (selNode) {
                addReferencedNode(selNode);
                targetImage = selNode;
            }
        }

        if (!targetImage) {
            showAgentToast('请先在画布中选中一张图片，或在 Agent 中引用图片');
            return;
        }

        const atmospherePrompt = `You are a top-tier interior designer and architectural photographer with 20 years of experience. You excel at deconstructing spaces through materials, lighting, and cinematic language. Please analyze the reference image I provide and strictly follow the JSON format below to output the analysis results. Do not miss any details; ensure that the scene can be reproduced 1:1 in AI drawing through your description.

Output Format: JSON Code Block only.
{
  "style_and_atmosphere": {
    "design_style": "e.g., Japandi, Industrial Loft, Mid-century Modern",
    "era_vibe": "e.g., 2020s Contemporary, 1960s Retro, Futuristic",
    "emotional_mood": "e.g., Serene, Moody, Clinical, Inviting"
  },
  "composition_and_perspective": {
    "visual_center": "Where is the visual focal point? e.g., The central red sofa, the distant window view",
    "perspective_type": "e.g., 1-Point Perspective, 2-Point Perspective, Isometric",
    "framing_composition": "e.g., Rule of Thirds, Symmetrical, Frame-within-a-frame",
    "depth_layering": "Describe the relationship between foreground, midground, and background. e.g., Blurred plants in foreground, dining table in midground, kitchen in background"
  },
  "camera_parameters": {
    "shot_type": "e.g., Wide Angle, Medium Shot, Close-up",
    "camera_angle": "e.g., Eye-level, Low Angle, High Angle",
    "lens_characteristics": "e.g., 35mm (Standard Wide), 85mm (Compression), Fisheye",
    "depth_of_field": "e.g., f/16 (Deep focus, all sharp), f/1.8 (Shallow depth of field/Bokeh)"
  },
  "lighting_physics": {
    "primary_source": "e.g., Natural sunlight from large window (left)",
    "light_quality": "e.g., Soft diffused, Hard directional, Dappled shadows",
    "color_temperature": "e.g., 6000K (Daylight Cool), 2700K (Warm Tungsten)",
    "volumetric_effects": "Are light beams/dust particles visible? (God rays, Haziness)"
  },
  "spatial_content_breakdown": {
    "architectural_shell": {
      "ceiling": "e.g., Exposed concrete beams, Drop ceiling with cove lights",
      "walls": "e.g., White plaster, Wood slats, Brick texture",
      "flooring": "e.g., Polished concrete, Chevron wood floor"
    },
    "key_objects": [
      {
        "object": "Describe the main furniture",
        "material": "Detailed material, e.g., Distressed brown leather",
        "color": "Hex code or specific name",
        "position": "Location in frame"
      },
      {
        "object": "Describe secondary decor",
        "material": "e.g., Brushed brass",
        "position": "Location"
      }
    ]
  },
  "color_palette_extraction": {
    "dominant_hues": ["Dominant Color 1", "Dominant Color 2"],
    "accent_hues": ["Accent Color 1"],
    "global_tone": "e.g., Desaturated, High Contrast, Pastel"
  }
}`;

        showAgentToast('正在解构空间材质、光影与氛围 JSON...');
        sendAgentMessage(atmospherePrompt);
    }

    function extractAtmosphereJson(text) {
        if (!text || typeof text !== 'string') return null;
        let clean = text.trim();
        const codeBlockMatch = clean.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
        if (codeBlockMatch && codeBlockMatch[1]) {
            clean = codeBlockMatch[1].trim();
        } else {
            const firstBrace = clean.indexOf('{');
            const lastBrace = clean.lastIndexOf('}');
            if (firstBrace !== -1 && lastBrace > firstBrace) {
                clean = clean.slice(firstBrace, lastBrace + 1);
            }
        }
        try {
            const parsed = JSON.parse(clean);
            if (parsed && typeof parsed === 'object') {
                const isAtmosphere = Boolean(parsed.style_and_atmosphere || parsed.spatial_content_breakdown || parsed.composition_and_perspective);
                const isInterrogate = Boolean(parsed.prompt_en || parsed.prompt_zh || parsed.visual_analysis);
                if (isAtmosphere || isInterrogate || Object.keys(parsed).length >= 2) {
                    return {
                        json: parsed,
                        rawString: JSON.stringify(parsed, null, 2),
                        isInterrogate,
                        isAtmosphere
                    };
                }
            }
        } catch (_) {}
        return null;
    }

    function formatAtmospherePrompt(jsonData) {
        if (!jsonData || typeof jsonData !== 'object') return '';
        const parts = [];

        // If reverse prompt JSON format
        if (jsonData.prompt_en || jsonData.prompt_zh) {
            if (jsonData.prompt_en) parts.push(jsonData.prompt_en);
            if (jsonData.prompt_zh) parts.push(`【中文解析】: ${jsonData.prompt_zh}`);
            if (jsonData.negative_prompt) parts.push(`【负向提示词】: ${jsonData.negative_prompt}`);
            return parts.join('\n\n');
        }
        if (jsonData.style_and_atmosphere) {
            const { design_style, era_vibe, emotional_mood } = jsonData.style_and_atmosphere;
            const p = [design_style, era_vibe, emotional_mood].filter(Boolean).join(', ');
            if (p) parts.push(`【空间风格与情绪】: ${p}`);
        }
        if (jsonData.composition_and_perspective) {
            const { visual_center, perspective_type, framing_composition, depth_layering } = jsonData.composition_and_perspective;
            const cp = [perspective_type, framing_composition, visual_center ? `视觉中心: ${visual_center}` : '', depth_layering ? `空间层次: ${depth_layering}` : ''].filter(Boolean).join('; ');
            if (cp) parts.push(`【构图与透视】: ${cp}`);
        }
        if (jsonData.camera_parameters) {
            const { shot_type, camera_angle, lens_characteristics, depth_of_field } = jsonData.camera_parameters;
            const cam = [shot_type, camera_angle, lens_characteristics, depth_of_field].filter(Boolean).join(', ');
            if (cam) parts.push(`【摄影机机位】: ${cam}`);
        }
        if (jsonData.lighting_physics) {
            const { primary_source, light_quality, color_temperature, volumetric_effects } = jsonData.lighting_physics;
            const lp = [primary_source, light_quality, color_temperature, volumetric_effects].filter(Boolean).join(', ');
            if (lp) parts.push(`【光影物理】: ${lp}`);
        }
        if (jsonData.spatial_content_breakdown) {
            const { architectural_shell, key_objects } = jsonData.spatial_content_breakdown;
            if (architectural_shell) {
                const shellParts = [];
                if (architectural_shell.ceiling) shellParts.push(`天花: ${architectural_shell.ceiling}`);
                if (architectural_shell.walls) shellParts.push(`墙面: ${architectural_shell.walls}`);
                if (architectural_shell.flooring) shellParts.push(`地面: ${architectural_shell.flooring}`);
                if (shellParts.length) parts.push(`【建筑界面材质】: ${shellParts.join('; ')}`);
            }
            if (Array.isArray(key_objects) && key_objects.length) {
                const objParts = key_objects.map(o => {
                    const desc = [o.object, o.material, o.color, o.position].filter(Boolean).join(' - ');
                    return desc;
                }).filter(Boolean);
                if (objParts.length) parts.push(`【核心陈设】: ${objParts.join('; ')}`);
            }
        }
        if (jsonData.color_palette_extraction) {
            const { dominant_hues, accent_hues, global_tone } = jsonData.color_palette_extraction;
            const hues = [...(dominant_hues || []), ...(accent_hues || [])].filter(Boolean).join(', ');
            const cpStr = [hues ? `主要色彩: ${hues}` : '', global_tone ? `全局影调: ${global_tone}` : ''].filter(Boolean).join('; ');
            if (cpStr) parts.push(`【调色板】: ${cpStr}`);
        }
        return parts.join('\n\n');
    }

    // =========================================================================
    // Canvas Placement & Workflow Lineage Auto-Linking
    // =========================================================================

    function addAgentImageToCanvas(imageUrl, prompt, title, sourceNodesList = null, batchIndex = 0) {
        if (!imageUrl) return null;
        if (typeof window.addNode !== 'function' && (!window.nodes || typeof window.render !== 'function')) {
            showAgentToast('画布未初始化');
            return null;
        }

        const sources = sourceNodesList || [...referencedNodes.values()];

        let x = 0;
        let y = 0;

        if (sources && sources.length > 0) {
            const maxX = Math.max(...sources.map(s => (Number(s.x) || 0) + (Number(s.w) || 260)));
            const avgY = sources.reduce((sum, s) => sum + (Number(s.y) || 0), 0) / sources.length;
            x = maxX + 80;
            y = avgY + batchIndex * 360;
        } else if (typeof window.defaultPoint === 'function') {
            const p = window.defaultPoint(40, 0);
            x = p.x;
            y = p.y + batchIndex * 360;
        } else {
            x = 100;
            y = 100 + batchIndex * 360;
        }

        const newNode = {
            id: (typeof window.uid === 'function') ? window.uid('img') : `img_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
            type: 'image',
            x: x,
            y: y,
            url: imageUrl,
            name: title || 'Agent 创作',
            prompt: prompt || ''
        };

        if (typeof window.addNode === 'function') {
            window.addNode(newNode);
        } else if (window.nodes) {
            window.nodes.push(newNode);
        }

        // Auto-create workflow graph lineage connections
        if (sources && sources.length > 0 && typeof window.connections !== 'undefined') {
            sources.forEach(src => {
                if (src.id && src.id !== '__uploaded__') {
                    if (typeof window.canConnect === 'function' && !window.canConnect(src.id, newNode.id)) {
                        return;
                    }
                    if (typeof window.wouldCreateCycle === 'function' && window.wouldCreateCycle(src.id, newNode.id)) {
                        return;
                    }
                    const linkId = (typeof window.uid === 'function') ? window.uid('c') : `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
                    if (!window.connections.some(c => c.from === src.id && c.to === newNode.id)) {
                        window.connections.push({
                            id: linkId,
                            from: src.id,
                            to: newNode.id
                        });
                    }
                }
            });
        }

        if (typeof window.selected !== 'undefined') {
            window.selected.clear();
            window.selected.add(newNode.id);
        }

        if (typeof window.render === 'function') window.render();
        if (typeof window.scheduleSave === 'function') window.scheduleSave();

        showAgentToast(sources && sources.length > 0 ? tr('canvas.agentAddedLinked', '已入画布并建立连线') : tr('canvas.agentAdded', '已放入画布'));
        return newNode;
    }

    function addPromptNodeToCanvas(promptText, sourceNodesList = null, nodeTitle = '') {
        if (!promptText) return null;
        const sources = sourceNodesList || [...referencedNodes.values()];

        let x = 0;
        let y = 0;

        if (sources && sources.length > 0) {
            const maxX = Math.max(...sources.map(s => (Number(s.x) || 0) + (Number(s.w) || 260)));
            const avgY = sources.reduce((sum, s) => sum + (Number(s.y) || 0), 0) / sources.length;
            x = maxX + 80;
            y = avgY;
        } else if (typeof window.defaultPoint === 'function') {
            const p = window.defaultPoint(40, 0);
            x = p.x;
            y = p.y;
        } else {
            x = 100;
            y = 100;
        }

        const newNode = {
            id: (typeof window.uid === 'function') ? window.uid('prompt') : `prompt_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
            type: 'prompt',
            x: x,
            y: y,
            text: promptText,
            name: nodeTitle || '反推提示词'
        };

        if (typeof window.addNode === 'function') {
            window.addNode(newNode);
        } else if (window.nodes) {
            window.nodes.push(newNode);
        }

        if (sources && sources.length > 0 && typeof window.connections !== 'undefined') {
            sources.forEach(src => {
                if (src.id && src.id !== '__uploaded__') {
                    if (typeof window.canConnect === 'function' && !window.canConnect(src.id, newNode.id)) {
                        return;
                    }
                    if (typeof window.wouldCreateCycle === 'function' && window.wouldCreateCycle(src.id, newNode.id)) {
                        return;
                    }
                    const linkId = (typeof window.uid === 'function') ? window.uid('c') : `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
                    if (!window.connections.some(c => c.from === src.id && c.to === newNode.id)) {
                        window.connections.push({ id: linkId, from: src.id, to: newNode.id });
                    }
                }
            });
        }

        if (typeof window.selected !== 'undefined') {
            window.selected.clear();
            window.selected.add(newNode.id);
        }

        if (typeof window.render === 'function') window.render();
        if (typeof window.scheduleSave === 'function') window.scheduleSave();

        showAgentToast('已在画布创建提示词节点并建立连线');
        return newNode;
    }

    // =========================================================================
    // Message Rendering & Communication
    // =========================================================================

    function appendUserMessage(text, refUrl, sourcesSnapshot = []) {
        const welcome = agentMessagesEl.querySelector('.agent-welcome');
        if (welcome) welcome.style.display = 'none';

        const wrap = document.createElement('div');
        wrap.className = 'agent-msg agent-msg-user';

        let refsHtml = '';
        if (sourcesSnapshot && sourcesSnapshot.length > 0) {
            refsHtml = '<div class="agent-msg-refs-bar">';
            sourcesSnapshot.forEach(s => {
                if (s.type === 'image' && s.url) {
                    refsHtml += `<img src="${escapeHtml(s.url)}" alt="ref" class="agent-msg-ref-img" title="${escapeHtml(s.name || '图片')}">`;
                } else if (s.type === 'prompt' && s.text) {
                    refsHtml += `<span class="agent-msg-ref-pill" title="${escapeHtml(s.text)}">@${escapeHtml(s.name || '提示词')}</span>`;
                }
            });
            refsHtml += '</div>';
        } else if (refUrl) {
            refsHtml = `<div class="agent-msg-ref"><img src="${escapeHtml(refUrl)}" alt="reference" class="agent-msg-ref-img"></div>`;
        }

        wrap.innerHTML = `
            <div class="agent-msg-bubble">
                ${refsHtml}
                <div class="agent-msg-text">${escapeHtml(text)}</div>
            </div>
        `;
        agentMessagesEl.appendChild(wrap);
        scrollMessagesToBottom();
    }

    function appendThinkingMessage() {
        const wrap = document.createElement('div');
        wrap.className = 'agent-msg agent-msg-assistant agent-msg-thinking';
        wrap.id = 'agentThinkingIndicator';
        wrap.innerHTML = `
            <div class="agent-msg-bubble">
                <div class="agent-thinking-dots">
                    <span class="dot"></span><span class="dot"></span><span class="dot"></span>
                </div>
                <span class="agent-thinking-label">${tr('canvas.agentThinking', 'Agent 思考并创作中...')}</span>
            </div>
        `;
        agentMessagesEl.appendChild(wrap);
        scrollMessagesToBottom();
    }

    function removeThinkingMessage() {
        const el = document.getElementById('agentThinkingIndicator');
        if (el) el.remove();
    }

    function appendAssistantReply(msg, action, sourcesSnapshot = []) {
        removeThinkingMessage();

        const wrap = document.createElement('div');
        wrap.className = 'agent-msg agent-msg-assistant';

        let innerHtml = '<div class="agent-msg-bubble">';

        if (msg.agent_reply) {
            innerHtml += `<div class="agent-msg-text">${escapeHtml(msg.agent_reply)}</div>`;
        }

        const isImage = msg.type === 'image' || (msg.image_urls && msg.image_urls.length) || Boolean(msg.image_url);
        const imageUrls = msg.image_urls || (msg.image_url ? [msg.image_url] : []);

        if (isImage && imageUrls.length) {
            innerHtml += `<div class="agent-image-grid">`;
            imageUrls.forEach((url, idx) => {
                const promptUsed = (msg.prompts && msg.prompts[idx]) || msg.content || '';
                innerHtml += `
                    <div class="agent-image-card" data-url="${escapeHtml(url)}" data-prompt="${escapeHtml(promptUsed)}" data-idx="${idx}">
                        <div class="agent-image-thumb-wrap">
                            <img src="${escapeHtml(url)}" alt="AI Generated" class="agent-image-thumb" loading="lazy">
                        </div>
                        <div class="agent-card-actions">
                            <button class="agent-card-btn primary agent-place-btn" type="button" title="直接放入画布并建立连线">
                                <i data-lucide="plus-circle" class="w-3.5 h-3.5"></i>
                                <span>${tr('canvas.agentAddToCanvas', '放入画布')}</span>
                            </button>
                            <button class="agent-card-btn secondary agent-copy-prompt-btn" type="button" title="复制提示词">
                                <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                                <span>${tr('canvas.copyPrompt', '复制提示词')}</span>
                            </button>
                        </div>
                    </div>
                `;
            });
            innerHtml += `</div>`;
        } else if (msg.content && !msg.agent_reply) {
            const atmosphereData = extractAtmosphereJson(msg.content);
            if (atmosphereData) {
                const headerTitle = atmosphereData.isInterrogate ? '反推提示词与视觉特征 JSON' : '空间氛围与材质解构 JSON';
                const headerIcon = atmosphereData.isInterrogate ? 'scan-search' : 'palette';
                const nodeTitle = atmosphereData.isInterrogate ? '反推生图提示词' : '空间氛围提示词';
                innerHtml += `
                    <div class="agent-msg-text agent-json-bubble">
                        <div class="agent-json-header">
                            <i data-lucide="${headerIcon}" class="w-3.5 h-3.5"></i>
                            <span>${headerTitle}</span>
                        </div>
                        <pre class="agent-json-pre"><code>${escapeHtml(atmosphereData.rawString)}</code></pre>
                    </div>
                    <div class="agent-card-actions" style="margin-top: 8px;">
                        <button class="agent-card-btn primary agent-atmosphere-prompt-node-btn" data-node-title="${nodeTitle}" type="button" title="从 JSON 提炼并在画布创建提示词节点并建立连线">
                            <i data-lucide="file-plus" class="w-3.5 h-3.5"></i>
                            <span>${tr('canvas.createPromptFromAtmosphere', '生成提示词节点')}</span>
                        </button>
                        <button class="agent-card-btn secondary agent-copy-json-btn" type="button" title="复制纯净 JSON">
                            <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                            <span>${tr('canvas.copyJson', '复制 JSON')}</span>
                        </button>
                        <button class="agent-card-btn secondary agent-copy-text-btn" type="button" title="复制完整回复">
                            <i data-lucide="file-text" class="w-3.5 h-3.5"></i>
                            <span>复制完整文本</span>
                        </button>
                    </div>
                `;
            } else {
                innerHtml += `<div class="agent-msg-text">${escapeHtml(msg.content)}</div>`;
                innerHtml += `
                    <div class="agent-card-actions" style="margin-top: 8px;">
                        <button class="agent-card-btn secondary agent-add-prompt-node-btn" type="button" title="在画布中创建提示词节点并建立连线">
                            <i data-lucide="file-text" class="w-3.5 h-3.5"></i>
                            <span>创建提示词节点</span>
                        </button>
                        <button class="agent-card-btn secondary agent-copy-text-btn" type="button" title="复制回复内容">
                            <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                            <span>复制</span>
                        </button>
                    </div>
                `;
            }
        }

        innerHtml += '</div>';
        wrap.innerHTML = innerHtml;
        agentMessagesEl.appendChild(wrap);

        wrap.querySelectorAll('.agent-image-thumb-wrap').forEach(thumb => {
            thumb.addEventListener('click', (e) => {
                e.stopPropagation();
                const card = thumb.closest('.agent-image-card');
                const url = card?.dataset?.url;
                if (url && typeof window.openLightboxImage === 'function') {
                    window.openLightboxImage(url);
                }
            });
        });

        wrap.querySelectorAll('.agent-place-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const card = btn.closest('.agent-image-card');
                const url = card?.dataset?.url;
                const p = card?.dataset?.prompt;
                const idx = Number(card?.dataset?.idx || 0);
                addAgentImageToCanvas(url, p, 'Agent 创作', sourcesSnapshot, idx);
            });
        });

        wrap.querySelectorAll('.agent-copy-prompt-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const card = btn.closest('.agent-image-card');
                const p = card?.dataset?.prompt;
                if (p) {
                    try {
                        await navigator.clipboard.writeText(p);
                        showAgentToast(tr('canvas.copied', '已复制提示词'));
                    } catch (err) {
                        showAgentToast(tr('canvas.copyFailed', '复制失败'));
                    }
                }
            });
        });

        wrap.querySelector('.agent-atmosphere-prompt-node-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            const btn = e.currentTarget;
            const atmosphereData = extractAtmosphereJson(msg.content);
            if (atmosphereData) {
                const nodeTitle = btn?.dataset?.nodeTitle || (atmosphereData.isInterrogate ? '反推生图提示词' : '空间氛围提示词');
                const promptText = formatAtmospherePrompt(atmosphereData.json);
                addPromptNodeToCanvas(promptText, sourcesSnapshot, nodeTitle);
            }
        });

        wrap.querySelector('.agent-copy-json-btn')?.addEventListener('click', async (e) => {
            e.stopPropagation();
            const atmosphereData = extractAtmosphereJson(msg.content);
            if (atmosphereData) {
                try {
                    await navigator.clipboard.writeText(atmosphereData.rawString);
                    showAgentToast(tr('canvas.copied', '已复制 JSON'));
                } catch (err) {
                    showAgentToast('复制失败');
                }
            }
        });

        wrap.querySelector('.agent-add-prompt-node-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            addPromptNodeToCanvas(msg.content, sourcesSnapshot);
        });

        wrap.querySelector('.agent-copy-text-btn')?.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                await navigator.clipboard.writeText(msg.content || '');
                showAgentToast('已复制内容');
            } catch (err) {
                showAgentToast('复制失败');
            }
        });

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }

        scrollMessagesToBottom();

        if (isImage && agentAutoPlaceCheckbox?.checked) {
            imageUrls.forEach((url, idx) => {
                const promptUsed = (msg.prompts && msg.prompts[idx]) || msg.content || '';
                addAgentImageToCanvas(url, promptUsed, 'Agent 创作', sourcesSnapshot, idx);
            });
        }
    }

    async function sendAgentMessage(overrideText) {
        if (isGenerating) {
            abortPendingRequest();
            return;
        }
        const text = (typeof overrideText === 'string' ? overrideText : (agentInputEl?.value || '')).trim();
        if (!text) return;

        abortPendingRequest();
        const controller = new AbortController();
        activeAbortController = controller;
        const currentSignal = controller.signal;

        isGenerating = true;
        agentSendBtn?.classList.add('loading');
        if (agentSendBtn) {
            agentSendBtn.disabled = false;
            agentSendBtn.title = tr('canvas.agentCancel', '点击取消');
        }

        // Snapshot references for this turn
        const sourcesSnapshot = [...referencedNodes.values()];
        if (uploadedReference) {
            sourcesSnapshot.unshift({
                id: '__uploaded__',
                type: 'image',
                name: uploadedReference.name || '上传参考图',
                url: uploadedReference.url
            });
        }

        const firstImg = sourcesSnapshot.find(s => s.type === 'image' && s.url);
        const refUrl = firstImg ? firstImg.url : '';

        appendUserMessage(text, refUrl, sourcesSnapshot);
        if (!overrideText && agentInputEl) {
            agentInputEl.value = '';
            agentInputEl.style.height = 'auto';
        }

        appendThinkingMessage();

        const provider = agentProviderSelect?.value || 'comfly';
        const model = agentModelSelect?.value || '';

        // Collect image references for multi-modal inference
        const refs = [];
        sourcesSnapshot.forEach(item => {
            if (item.type === 'image' && item.url) {
                refs.push({
                    url: item.url,
                    name: item.name || 'reference',
                    role: 'reference',
                    kind: 'image'
                });
            }
        });

        // Enrich text prompt with prompt node contents if present
        let enrichedMessage = text;
        const promptNodes = sourcesSnapshot.filter(s => s.type === 'prompt' && s.text);
        if (promptNodes.length > 0) {
            const promptContext = promptNodes.map(p => `【参考提示词: ${p.name || ''}】：${p.text}`).join('\n');
            enrichedMessage = `${enrichedMessage}\n\n[画布上下文参考提示词]：\n${promptContext}`;
        }

        try {
            const resp = await fetch('/api/chat/agent', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                signal: currentSignal,
                body: JSON.stringify({
                    conversation_id: conversationId,
                    message: enrichedMessage,
                    provider: provider,
                    model: model,
                    image_provider: provider,
                    reference_images: refs
                })
            });

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || `请求失败 (${resp.status})`);
            }

            const data = await resp.json();
            if (data.conversation?.id) {
                conversationId = data.conversation.id;
            }

            const assistantMsg = data.message || {};
            const action = data.agent?.action || 'chat';
            appendAssistantReply(assistantMsg, action, sourcesSnapshot);
        } catch (err) {
            removeThinkingMessage();
            if (err.name === 'AbortError' || currentSignal?.aborted) {
                return;
            }
            const errWrap = document.createElement('div');
            errWrap.className = 'agent-msg agent-msg-assistant agent-msg-error';
            errWrap.innerHTML = `
                <div class="agent-msg-bubble">
                    <div class="agent-error-badge">
                        <i data-lucide="alert-circle" class="w-3.5 h-3.5"></i>
                        <span>${escapeHtml(err.message || '生成或对话遇到异常')}</span>
                    </div>
                </div>
            `;
            agentMessagesEl.appendChild(errWrap);
            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons();
            }
            scrollMessagesToBottom();
        } finally {
            if (activeAbortController === controller) {
                activeAbortController = null;
            }
            isGenerating = false;
            agentSendBtn?.classList.remove('loading');
            if (agentSendBtn) {
                agentSendBtn.disabled = false;
                agentSendBtn.title = '';
            }
            agentInputEl?.focus();
        }
    }

    function handleFileUpload(e) {
        const file = e.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = async () => {
            const dataUrl = reader.result;
            try {
                showAgentToast('正在上传参考图...');
                const resp = await fetch('/api/ai/upload-base64', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        data: dataUrl,
                        filename: file.name || 'agent_ref.png'
                    })
                });
                if (resp.ok) {
                    const data = await resp.json();
                    uploadedReference = {
                        url: data.url,
                        name: file.name || '参考图'
                    };
                    renderContextChips();
                    showAgentToast('参考图已关联');
                } else {
                    showAgentToast('上传失败');
                }
            } catch (err) {
                showAgentToast('上传网络异常');
            }
        };
        reader.readAsDataURL(file);
        e.target.value = '';
    }

    window.agentApplySuggestion = function (text) {
        if (!agentInputEl) return;
        agentInputEl.value = text;
        agentInputEl.focus();
        sendAgentMessage();
    };

    function bindEvents() {
        window.addEventListener('beforeunload', () => abortPendingRequest());

        agentToggleBtn?.addEventListener('click', () => toggleAgentDrawer());
        agentDockTrigger?.addEventListener('click', () => toggleAgentDrawer(true));
        agentDockSideBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            const isRight = agentPanel?.classList.contains('dock-right');
            applyDockSide(isRight ? 'left' : 'right');
            showAgentToast(isRight ? '已切换停靠到左侧' : '已切换停靠到右侧');
        });
        agentCloseBtn?.addEventListener('click', () => toggleAgentDrawer(false));
        agentMessagesEl?.addEventListener('click', (e) => {
            const btn = e.target.closest('.agent-suggestion-btn');
            if (btn && btn.dataset.suggestion) {
                agentApplySuggestion(btn.dataset.suggestion);
            }
        });

        agentNewBtn?.addEventListener('click', () => {
            abortPendingRequest();
            conversationId = '';
            clearLinkedContext();
            if (agentMessagesEl) {
                agentMessagesEl.innerHTML = `
                    <div class="agent-welcome">
                        <div class="agent-welcome-icon"><i data-lucide="sparkles" class="w-6 h-6"></i></div>
                        <div class="agent-welcome-title">输入灵感，协同创作</div>
                        <div class="agent-welcome-desc">描述你想要生成的画面，或选中画布节点进行调整修图、扩图与风格演进。</div>
                        <div class="agent-suggestions">
                            <button class="agent-suggestion-btn" type="button" data-suggestion="生成一组现代极简主义住宅，暖光木饰面与水面倒影">现代极简建筑效果图</button>
                            <button class="agent-suggestion-btn" type="button" data-suggestion="根据当前选中的图片，帮我构思 3 个不同视角和天气的衍生方案">分析选中节点并衍生视角</button>
                            <button class="agent-suggestion-btn" type="button" data-suggestion="优化我的提示词：大师级杰作，写实摄影，电影感光影">润色优化提示词</button>
                        </div>
                    </div>
                `;
                if (window.lucide && typeof window.lucide.createIcons === 'function') {
                    window.lucide.createIcons();
                }
            }
            showAgentToast(tr('canvas.agentNewSession', '已开启新对话'));
        });

        agentProviderSelect?.addEventListener('change', () => {
            localStorage.setItem('canvas_agent_provider', agentProviderSelect.value);
            populateModels();
        });

        agentModelSelect?.addEventListener('change', () => {
            const providerId = agentProviderSelect?.value || 'comfly';
            localStorage.setItem(`canvas_agent_model_${providerId}`, agentModelSelect.value);
        });

        agentInterrogateBtn?.addEventListener('click', handleInterrogate);
        agentExtractAtmosphereBtn?.addEventListener('click', handleExtractAtmosphere);

        agentContextClearAllBtn?.addEventListener('click', () => {
            clearLinkedContext();
            showAgentToast('已清空参考上下文');
        });

        agentFileInput?.addEventListener('change', handleFileUpload);

        agentAutoPlaceCheckbox?.addEventListener('change', () => {
            localStorage.setItem('canvas_agent_autoplace', agentAutoPlaceCheckbox.checked ? '1' : '0');
        });

        agentSendBtn?.addEventListener('click', () => {
            if (isGenerating) {
                abortPendingRequest();
                showAgentToast(tr('canvas.agentCancelled', '已取消生成'));
                return;
            }
            sendAgentMessage();
        });

        agentMentionBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            if (!agentInputEl) return;
            agentInputEl.focus();
            const cur = agentInputEl.value;
            const pos = agentInputEl.selectionStart || cur.length;
            const before = cur.slice(0, pos);
            const needsSpace = before.length > 0 && !before.endsWith(' ');
            const prefix = needsSpace ? ' @' : '@';
            agentInputEl.value = before + prefix + cur.slice(pos);
            const newPos = pos + prefix.length;
            agentInputEl.setSelectionRange(newPos, newPos);
            openMentionMenu('', newPos - 1);
        });

        agentInputEl?.addEventListener('keydown', (e) => {
            if (isMentionMenuOpen) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    if (mentionCandidates.length > 0) {
                        mentionActiveIndex = (mentionActiveIndex + 1) % mentionCandidates.length;
                        updateMentionHighlight();
                    }
                    return;
                }
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (mentionCandidates.length > 0) {
                        mentionActiveIndex = (mentionActiveIndex - 1 + mentionCandidates.length) % mentionCandidates.length;
                        updateMentionHighlight();
                    }
                    return;
                }
                if (e.key === 'Enter' || e.key === 'Tab') {
                    if (mentionCandidates.length > 0 && mentionCandidates[mentionActiveIndex]) {
                        e.preventDefault();
                        selectMentionCandidate(mentionCandidates[mentionActiveIndex]);
                        return;
                    }
                }
                if (e.key === 'Escape') {
                    e.preventDefault();
                    closeMentionMenu();
                    return;
                }
            }

            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendAgentMessage();
            }
        });

        agentInputEl?.addEventListener('input', () => {
            agentInputEl.style.height = 'auto';
            agentInputEl.style.height = Math.min(agentInputEl.scrollHeight, 140) + 'px';

            const cursorPos = agentInputEl.selectionStart || 0;
            const textBeforeCursor = agentInputEl.value.slice(0, cursorPos);
            const match = textBeforeCursor.match(/(?:^|\s)@([^\s@]*)$/);
            if (match) {
                const query = match[1] || '';
                const matchIndex = textBeforeCursor.lastIndexOf('@');
                openMentionMenu(query, matchIndex);
            } else {
                closeMentionMenu();
            }
        });

        document.addEventListener('click', (e) => {
            if (isMentionMenuOpen && !agentMentionMenu?.contains(e.target) && e.target !== agentMentionBtn && !agentMentionBtn?.contains(e.target)) {
                closeMentionMenu();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.altKey && (e.key === 'a' || e.key === 'A')) {
                e.preventDefault();
                toggleAgentDrawer();
            }
            if (e.altKey && (e.key === 's' || e.key === 'S')) {
                e.preventDefault();
                const isRight = agentPanel?.classList.contains('dock-right');
                applyDockSide(isRight ? 'left' : 'right');
                showAgentToast(isRight ? '已切换停靠到左侧' : '已切换停靠到右侧');
            }
        });

        agentProviderSelect?.addEventListener('change', () => {
            if (agentProviderSelect.value) {
                localStorage.setItem('canvas_agent_provider', agentProviderSelect.value);
                localStorage.setItem('canvas_agent_provider_pinned_v3', '1');
                populateModels();
            }
        });

        window.addEventListener('canvas-providers-loaded', () => {
            cachedProviders = null;
            populateProviders();
        });
        try {
            const agentBc = new BroadcastChannel('studio-api');
            agentBc.onmessage = (e) => {
                if (e.data?.type === 'providers-changed') {
                    cachedProviders = null;
                    populateProviders();
                }
            };
        } catch (_) {}

        setInterval(pollCanvasSelection, 400);
    }

    function init() {
        agentPanel = document.getElementById('canvasAgentPanel');
        agentToggleBtn = document.getElementById('canvasAgentToggle');
        agentDockTrigger = document.getElementById('agentDockTrigger');
        agentCloseBtn = document.getElementById('agentCloseBtn');
        agentDockSideBtn = document.getElementById('agentDockSideBtn');
        agentNewBtn = document.getElementById('agentNewSessionBtn');
        agentMessagesEl = document.getElementById('agentMessages');
        agentInputEl = document.getElementById('agentInput');
        agentSendBtn = document.getElementById('agentSendBtn');
        agentProviderSelect = document.getElementById('agentProviderSelect');
        agentModelSelect = document.getElementById('agentModelSelect');
        agentContextBar = document.getElementById('agentContextBar');
        agentContextChips = document.getElementById('agentContextChips');
        agentInterrogateBtn = document.getElementById('agentInterrogateBtn');
        agentExtractAtmosphereBtn = document.getElementById('agentExtractAtmosphereBtn');
        agentContextClearAllBtn = document.getElementById('agentContextClearAllBtn');
        agentMentionMenu = document.getElementById('agentMentionMenu');
        agentMentionList = document.getElementById('agentMentionList');
        agentMentionCount = document.getElementById('agentMentionCount');
        agentMentionBtn = document.getElementById('agentMentionBtn');
        agentAutoPlaceCheckbox = document.getElementById('agentAutoPlaceCheckbox');
        agentFileInput = document.getElementById('agentFileInput');

        if (!agentPanel) return;

        const isDockPinnedV2 = localStorage.getItem('canvas_agent_dock_v2') === '1';
        const savedDock = isDockPinnedV2 ? (localStorage.getItem('canvas_agent_dock') || 'right') : 'right';
        applyDockSide(savedDock);

        if (agentAutoPlaceCheckbox) {
            const savedAuto = localStorage.getItem('canvas_agent_autoplace');
            if (savedAuto !== null) {
                agentAutoPlaceCheckbox.checked = savedAuto === '1';
            }
        }

        populateProviders();
        bindEvents();

        const wasOpen = localStorage.getItem('canvas_agent_open') === '1';
        if (wasOpen) {
            toggleAgentDrawer(true);
        }

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.CanvasAgent = {
        abort: abortPendingRequest,
        toggle: toggleAgentDrawer,
        addReferencedNode: addReferencedNode,
        clearLinkedContext: clearLinkedContext,
        addAgentImageToCanvas: addAgentImageToCanvas,
        addPromptNodeToCanvas: addPromptNodeToCanvas,
        handleInterrogate: handleInterrogate,
        handleExtractAtmosphere: handleExtractAtmosphere,
        formatAtmospherePrompt: formatAtmospherePrompt,
        extractAtmosphereJson: extractAtmosphereJson,
        getReferencedNodes: () => [...referencedNodes.values()]
    };
})();
