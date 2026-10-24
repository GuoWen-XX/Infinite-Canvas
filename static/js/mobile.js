/* mobile.js — 移动端微工作台（mobile.html 配套）
 * 包含：PWA 注册、物理触觉、手势下拉关闭、草稿防灾恢复、动态阶段感知、
 * 跨屏推送至桌面画布、参数一键回溯、历史骨架屏与多画布素材选择。
 */
'use strict';

/* ============ 常量 ============ */
const POLL_INTERVAL_MS = 1800;
const REF_MAX = 8;
const SIZE_MAPS = {
    '1K': {
        square: '1024x1024',
        portrait: '1024x1536',
        landscape: '1536x1024',
        story: '720x1280',
        wide: '1280x720',
    },
    '2K': {
        square: '2048x2048',
        portrait: '1536x2304',
        landscape: '2304x1536',
        story: '1080x1920',
        wide: '1920x1080',
    },
    '4K': {
        square: '4096x4096',
        portrait: '2560x3840',
        landscape: '3840x2560',
        story: '2160x3840',
        wide: '3840x2160',
    },
};

/* ============ 状态 ============ */
let providers = [];          // [{id,name,image_models,chat_models,...}]
let currentProviderId = '';
let currentModel = '';
let refs = [];               // [{url,name}] 参考图
let running = false;
let canvasAssetList = [];    // [{url,name,kind,canvas_id,canvas_title,...}] 来自 /api/canvas-assets
let canvasList = [];         // [{id,title,asset_count,...}]
let onlineHistoryList = [];  // [{timestamp,images,prompt,...}]
let selectedHistoryCanvasId = 'all';
let currentActiveItem = null;// 当前在 Lightbox 中展示的条目元数据

/* ============ 工具 ============ */
const $ = id => document.getElementById(id);
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
async function responseErrorMessage(res, fallback) {
    try {
        const data = await res.json();
        return data.detail || data.error || data.message || fallback;
    } catch (_) { return fallback; }
}

/* ============ 物理触觉反馈 (Haptic Feedback) ============ */
function haptic(type = 'light') {
    if (!navigator.vibrate) return;
    try {
        if (type === 'light') navigator.vibrate(12);
        else if (type === 'medium') navigator.vibrate(28);
        else if (type === 'success') navigator.vibrate([16, 50, 24]);
        else if (type === 'error') navigator.vibrate([35, 45, 35, 45, 35]);
    } catch (_) {}
}

/* ============ Toast ============ */
let toastTimer = null;
function showToast(message, retryFn = null) {
    const el = $('toast');
    if (!el) return;
    el.innerHTML = '';
    const span = document.createElement('span');
    span.textContent = message;
    el.appendChild(span);
    if (retryFn) {
        const btn = document.createElement('button');
        btn.className = 'toast-retry';
        btn.textContent = '重试';
        btn.onclick = () => { hideToast(); retryFn(); };
        el.appendChild(btn);
    }
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, retryFn ? 12000 : 3500);
}
function hideToast() { const el = $('toast'); if (el) el.classList.remove('show'); }

/* ============ 草稿防灾自动保存与恢复 ============ */
let draftTimer = null;
function scheduleSaveDraft() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraft, 350);
}
function saveDraft() {
    try {
        const data = {
            prompt: $('prompt')?.value || '',
            negativePrompt: $('negativePrompt')?.value || '',
            ratio: $('ratio')?.value || 'auto',
            resolution: $('resolution')?.value || '2K',
            count: $('count')?.value || '1',
            quality: $('quality')?.value || 'standard',
            providerId: currentProviderId,
            model: currentModel,
            refs: refs.map(r => ({ url: r.url, name: r.name })),
            time: Date.now()
        };
        localStorage.setItem('meanscanvas_mobile_draft', JSON.stringify(data));
    } catch (_) {}
}
function restoreDraft() {
    try {
        const raw = localStorage.getItem('meanscanvas_mobile_draft');
        if (!raw) return false;
        const data = JSON.parse(raw);
        if (data.prompt && $('prompt')) $('prompt').value = data.prompt;
        if (data.negativePrompt && $('negativePrompt')) {
            $('negativePrompt').value = data.negativePrompt;
            if ($('advDetails')) $('advDetails').open = true;
        }
        if (data.ratio && $('ratio')) $('ratio').value = data.ratio;
        if (data.resolution && $('resolution')) $('resolution').value = data.resolution;
        if (data.count && $('count')) $('count').value = data.count;
        if (data.quality && $('quality')) $('quality').value = data.quality;
        if (Array.isArray(data.refs) && data.refs.length) {
            refs = data.refs.slice(0, REF_MAX);
            renderRefs();
        }
        if (data.providerId) currentProviderId = data.providerId;
        if (data.model) currentModel = data.model;
        return true;
    } catch (_) { return false; }
}

/* ============ Provider / Model ============ */
function mobileProviderList() {
    const priority = ['modelscope', 'gemini-cli', 'codex', 'fhl', 'runninghub', 'pollinations', 'apimart', 'openai'];
    const active = providers.filter(p => p && p.enabled !== false && Array.isArray(p.image_models) && p.image_models.length > 0);
    return active.sort((a, b) => {
        const ia = priority.indexOf(a.id);
        const ib = priority.indexOf(b.id);
        if (ia !== -1 && ib !== -1) return ia - ib;
        if (ia !== -1) return -1;
        if (ib !== -1) return 1;
        return (a.name || a.id).localeCompare(b.name || b.id);
    });
}
function providerModels(providerId) {
    const p = providers.find(x => x.id === providerId);
    let models = (p && Array.isArray(p.image_models)) ? p.image_models.slice() : [];
    if (providerId === 'modelscope' && models.length && !models.some(m => /flux/i.test(String(m)))) {
        models = ['black-forest-labs/FLUX.2-klein-9B', ...models.filter(m => !/flux/i.test(String(m)))];
    }
    return models;
}
function renderProviderSelect() {
    const sel = $('provider');
    if (!sel) return;
    const list = mobileProviderList();
    if (!list.length) {
        sel.innerHTML = `<option value="" disabled selected>暂无可用平台，请到桌面端配置</option>`;
        return;
    }
    sel.innerHTML = list.map(p => {
        const hasModels = providerModels(p.id).length > 0;
        return `<option value="${escapeHtml(p.id)}" ${p.id === currentProviderId ? 'selected' : ''} ${hasModels ? '' : 'disabled'}>${escapeHtml(p.name || p.id)}${hasModels ? '' : '（未配置模型）'}</option>`;
    }).join('');
    if (!currentProviderId || !list.some(p => p.id === currentProviderId && providerModels(p.id).length)) {
        const first = list.find(p => providerModels(p.id).length > 0);
        currentProviderId = first ? first.id : '';
    }
    renderModelSelect();
}
function renderModelSelect() {
    const sel = $('model');
    if (!sel) return;
    const models = providerModels(currentProviderId);
    if (!models.length) {
        sel.innerHTML = `<option value="" disabled selected>该平台暂无生图模型</option>`;
        currentModel = '';
        return;
    }
    sel.innerHTML = models.map(m => `<option value="${escapeHtml(m)}" ${m === currentModel ? 'selected' : ''}>${escapeHtml(m)}</option>`).join('');
    if (!currentModel || !models.includes(currentModel)) currentModel = models[0];
    syncGenBtn();
}
function resolveSize() {
    const ratio = $('ratio')?.value || 'auto';
    if (ratio === 'auto') return 'auto';
    const res = $('resolution')?.value || '2K';
    const map = SIZE_MAPS[res] || SIZE_MAPS['2K'];
    return map[ratio] || map.square;
}

/* ============ 参考图 ============ */
function renderRefs() {
    const zone = $('refZone');
    if (!zone) return;
    const thumbs = zone.querySelectorAll('.ref-thumb');
    thumbs.forEach(t => t.remove());
    const btn = $('pickAlbum');
    refs.slice(0, REF_MAX).forEach((ref, idx) => {
        const div = document.createElement('div');
        div.className = 'ref-thumb';
        div.innerHTML = `
            <img src="${escapeHtml(ref.url)}" alt="${escapeHtml(ref.name || '')}">
            <button class="ref-remove" type="button" aria-label="移除"><i data-lucide="x" class="w-3.5 h-3.5"></i></button>`;
        div.querySelector('.ref-remove').onclick = () => {
            haptic('light');
            refs.splice(idx, 1);
            renderRefs();
            scheduleSaveDraft();
        };
        zone.insertBefore(div, btn);
    });
    if(window.lucide) lucide.createIcons();
    $('pickAlbum').style.display = refs.length >= REF_MAX ? 'none' : '';
    scheduleSaveDraft();
}
async function addFiles(fileList) {
    const files = [...fileList].filter(f => f && (f.type || '').startsWith('image/')).slice(0, REF_MAX - refs.length);
    if (!files.length) return;
    haptic('light');
    for (const f of files) {
        const form = new FormData();
        form.append('files', f);
        try {
            const res = await fetch('/api/ai/upload', { method: 'POST', body: form });
            if (!res.ok) throw new Error(await responseErrorMessage(res, '上传失败'));
            const data = await res.json();
            const file = (data.files || [])[0];
            if (file && file.url) refs.push({ url: file.url, name: file.name });
        } catch (err) {
            haptic('error');
            showToast(`「${f.name || '图片'}」上传失败：${err.message || '网络错误'}`);
        }
    }
    renderRefs();
}

/* ============ 历史抽屉与多画布素材选择 ============ */
function renderSkeletonGrid() {
    const grid = $('historyGrid');
    if (!grid) return;
    grid.innerHTML = Array(8).fill(0).map(() => '<div class="skeleton-cell skeleton"></div>').join('');
}
async function openHistoryDrawer() {
    haptic('light');
    $('historyDrawer').classList.add('open');
    renderSkeletonGrid();
    try {
        const [assetRes, historyRes] = await Promise.all([
            fetch('/api/canvas-assets').catch(() => null),
            fetch('/api/history?type=online').catch(() => null),
        ]);

        if (assetRes && assetRes.ok) {
            const data = await assetRes.json();
            canvasList = Array.isArray(data.canvases) ? data.canvases : [];
            canvasAssetList = (Array.isArray(data.items) ? data.items : []).filter(it => it && it.kind === 'image' && it.url);
        } else {
            canvasList = [];
            canvasAssetList = [];
        }

        if (historyRes && historyRes.ok) {
            const hItems = await historyRes.json();
            onlineHistoryList = (Array.isArray(hItems) ? hItems : [])
                .filter(it => it && Array.isArray(it.images) && it.images.length);
        } else {
            onlineHistoryList = [];
        }

        renderHistoryCanvasTabs();
        renderHistoryGrid();
    } catch (err) {
        $('historyGrid').innerHTML = `<div class="drawer-loading">${escapeHtml(err.message || '加载失败')}</div>`;
    }
}
function closeHistoryDrawer() {
    const drawer = $('historyDrawer');
    if (drawer) drawer.classList.remove('open');
    const body = $('drawerBody');
    if (body) body.style.transform = '';
}

function renderHistoryCanvasTabs() {
    const tabsContainer = $('historyCanvasTabs');
    if (!tabsContainer) return;

    const canvasCounts = {};
    canvasAssetList.forEach(it => {
        const cid = it.canvas_id || 'unknown';
        canvasCounts[cid] = (canvasCounts[cid] || 0) + 1;
    });

    const activeCanvases = canvasList.filter(c => (canvasCounts[c.id] || 0) > 0);
    const totalAssets = canvasAssetList.length + onlineHistoryList.reduce((sum, h) => sum + (h.images?.length || 0), 0);

    let html = `<button type="button" class="history-canvas-pill ${selectedHistoryCanvasId === 'all' ? 'active' : ''}" data-canvas-id="all">全部历史 (${totalAssets})</button>`;

    if (onlineHistoryList.length > 0) {
        const count = onlineHistoryList.reduce((sum, h) => sum + (h.images?.length || 0), 0);
        html += `<button type="button" class="history-canvas-pill ${selectedHistoryCanvasId === 'recent-online' ? 'active' : ''}" data-canvas-id="recent-online">最近生图 (${count})</button>`;
    }

    activeCanvases.forEach(c => {
        const count = canvasCounts[c.id] || 0;
        const active = selectedHistoryCanvasId === c.id ? 'active' : '';
        html += `<button type="button" class="history-canvas-pill ${active}" data-canvas-id="${escapeHtml(c.id)}">${escapeHtml(c.title || '画布')} (${count})</button>`;
    });

    tabsContainer.innerHTML = html;
    tabsContainer.querySelectorAll('.history-canvas-pill').forEach(btn => {
        btn.onclick = () => {
            haptic('light');
            selectedHistoryCanvasId = btn.dataset.canvasId;
            tabsContainer.querySelectorAll('.history-canvas-pill').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderHistoryGrid();
        };
    });
}

function renderHistoryGrid() {
    const grid = $('historyGrid');
    if (!grid) return;

    let displayItems = [];
    const seenUrls = new Set();

    if (selectedHistoryCanvasId === 'all') {
        canvasAssetList.forEach(it => {
            if (!seenUrls.has(it.url)) {
                seenUrls.add(it.url);
                displayItems.push({
                    url: it.url,
                    name: it.name || it.prompt || '画布素材',
                    prompt: it.prompt || it.name || '',
                    canvasTitle: it.canvas_title || '画布素材',
                    canvasId: it.canvas_id || '',
                    model: it.model || '',
                    resolution: it.resolution || ''
                });
            }
        });
        onlineHistoryList.forEach(it => {
            (it.images || []).forEach(url => {
                if (url && !seenUrls.has(url)) {
                    seenUrls.add(url);
                    displayItems.push({
                        url: url,
                        name: it.prompt || '最近生图',
                        prompt: it.prompt || '',
                        canvasTitle: '最近生图',
                        canvasId: '',
                        model: it.model || '',
                        resolution: it.resolution || ''
                    });
                }
            });
        });
    } else if (selectedHistoryCanvasId === 'recent-online') {
        onlineHistoryList.forEach(it => {
            (it.images || []).forEach(url => {
                if (url && !seenUrls.has(url)) {
                    seenUrls.add(url);
                    displayItems.push({
                        url: url,
                        name: it.prompt || '最近生图',
                        prompt: it.prompt || '',
                        canvasTitle: '最近生图',
                        canvasId: '',
                        model: it.model || '',
                        resolution: it.resolution || ''
                    });
                }
            });
        });
    } else {
        canvasAssetList.filter(it => it.canvas_id === selectedHistoryCanvasId).forEach(it => {
            if (!seenUrls.has(it.url)) {
                seenUrls.add(it.url);
                displayItems.push({
                    url: it.url,
                    name: it.name || it.prompt || '画布素材',
                    prompt: it.prompt || it.name || '',
                    canvasTitle: it.canvas_title || '画布素材',
                    canvasId: it.canvas_id || '',
                    model: it.model || '',
                    resolution: it.resolution || ''
                });
            }
        });
    }

    if (!displayItems.length) {
        grid.innerHTML = '<div class="drawer-loading">该分类下暂无图片素材</div>';
        return;
    }

    grid.innerHTML = displayItems.slice(0, 100).map((it, idx) => `
        <div class="history-cell skeleton" data-idx="${idx}">
            <img src="${escapeHtml(it.url)}" loading="lazy" alt="素材图片" onload="this.classList.add('loaded'); this.parentElement.classList.remove('skeleton');">
            <div class="history-cell-badge" title="${escapeHtml(it.canvasTitle)}">${escapeHtml(it.canvasTitle)}</div>
        </div>
    `).join('');

    grid.querySelectorAll('.history-cell').forEach(cell => {
        cell.onclick = () => {
            haptic('light');
            const idx = parseInt(cell.dataset.idx, 10);
            const item = displayItems[idx];
            if (item) {
                openPreview(item.url, item.prompt || item.name, item);
            }
        };
    });
}

/* ============ 跨屏推送至桌面画布 (Mobile-to-Desktop Push) ============ */
async function pushToCanvas(url, name = '移动端图片', promptText = '', targetCid = '') {
    haptic('medium');
    try {
        let cid = targetCid || selectedHistoryCanvasId;
        if (!cid || cid === 'all' || cid === 'recent-online') {
            cid = canvasList[0]?.id || '';
        }
        const res = await fetch('/api/canvas/mobile-push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                name: name,
                canvas_id: cid,
                prompt: promptText
            })
        });
        if (!res.ok) throw new Error(await responseErrorMessage(res, '推送失败'));
        const data = await res.json();
        haptic('success');
        showToast(`已推送到桌面「${data.canvas_title || '画布'}」！`);
    } catch (err) {
        haptic('error');
        showToast(`推送失败：${err.message || '网络错误'}`);
    }
}

/* ============ 参数回填复用 (Parameter Recovery) ============ */
function reuseParameters(item) {
    if (!item) return;
    haptic('medium');
    let promptText = item.prompt || item.name || '';
    let negText = '';
    if (promptText.includes('\n--no ')) {
        const parts = promptText.split('\n--no ');
        promptText = parts[0].trim();
        negText = (parts[1] || '').trim();
    } else if (promptText.includes(' --no ')) {
        const parts = promptText.split(' --no ');
        promptText = parts[0].trim();
        negText = (parts[1] || '').trim();
    }
    if (promptText && $('prompt')) $('prompt').value = promptText;
    if (negText && $('negativePrompt')) {
        $('negativePrompt').value = negText;
        if ($('advDetails')) $('advDetails').open = true;
    }
    if (item.model && $('model')) {
        $('model').value = item.model;
        currentModel = item.model;
    }
    if (item.resolution && $('resolution')) {
        $('resolution').value = item.resolution;
    }
    scheduleSaveDraft();
    closeHistoryDrawer();
    closePreview();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    haptic('success');
    showToast('已回填提示词与生成参数');
}

/* ============ 生成主流程 (含动态阶段与进度感知) ============ */
function syncGenBtn() {
    const btn = $('genBtn');
    if (!btn) return;
    btn.disabled = running || !currentModel;
    btn.innerHTML = running
        ? '<i data-lucide="loader-2" class="spin"></i>生成中…'
        : '<i data-lucide="zap"></i>生成';
    try { lucide.createIcons(); } catch (_) {}
}

async function generate() {
    if (running) return;
    const prompt = ($('prompt').value || '').trim();
    if (!prompt && !refs.length) {
        haptic('error');
        showToast('请输入提示词或添加参考图');
        return;
    }
    if (!currentProviderId || !currentModel) {
        haptic('error');
        showToast('请选择平台与模型');
        return;
    }
    haptic('medium');
    running = true;
    syncGenBtn();

    const startTime = Date.now();
    $('resultZone').innerHTML = `
        <div class="result-pending">
            <div class="spin-lg"></div>
            <div class="pending-text">${escapeHtml(currentModel.split('/').pop())}</div>
            <div class="progress-bar-wrap">
                <div class="progress-bar-fill" id="progressFill" style="width: 15%;"></div>
            </div>
            <div class="phase-badge" id="phaseBadge">接收任务 · 已用时 0.0s</div>
        </div>`;

    let progressTimer = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        const fill = $('progressFill');
        const badge = $('phaseBadge');
        if (!fill || !badge) return;
        const e = parseFloat(elapsed);
        if (e < 2.5) {
            fill.style.width = `${Math.min(45, 15 + e * 12)}%`;
            badge.textContent = `准备请求 · 已用时 ${elapsed}s`;
        } else if (e < 7.0) {
            fill.style.width = `${Math.min(80, 45 + (e - 2.5) * 8)}%`;
            badge.textContent = `扩散推理中 · 已用时 ${elapsed}s`;
        } else {
            fill.style.width = `${Math.min(94, 80 + (e - 7.0) * 2)}%`;
            badge.textContent = `高清渲染解码 · 已用时 ${elapsed}s`;
        }
    }, 200);

    try {
        const resolution = $('resolution')?.value || '2K';
        const count = parseInt($('count')?.value || '1', 10);
        const quality = $('quality')?.value || 'standard';
        const negative = ($('negativePrompt')?.value || '').trim();
        let finalPrompt = prompt || 'Edit the reference images.';
        if (negative) {
            finalPrompt += `\n--no ${negative}`;
        }

        // 1) 创建任务
        const res = await fetch('/api/canvas-image-tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: finalPrompt,
                provider_id: currentProviderId,
                model: currentModel,
                size: resolveSize(),
                resolution: resolution,
                quality: quality,
                n: count,
                reference_images: refs.slice(0, REF_MAX).map(r => ({ url: r.url })),
            }),
        });
        if (!res.ok) throw new Error(await responseErrorMessage(res, '任务创建失败'));
        const task = await res.json();

        // 2) 轮询结果
        let result = null;
        while (true) {
            const st = await fetch(`/api/canvas-image-tasks/${encodeURIComponent(task.task_id)}`);
            if (!st.ok) throw new Error(await responseErrorMessage(st, '任务查询失败'));
            const data = await st.json();
            if (data.status === 'succeeded') { result = data.result || {}; break; }
            if (data.status === 'failed') throw new Error(data.error || '生成失败');
            await sleep(POLL_INTERVAL_MS);
        }

        const images = (result.images || []).filter(Boolean);
        if (!images.length) throw new Error('生成结果为空');

        clearInterval(progressTimer);
        haptic('success');
        renderResult(images, prompt, {
            model: currentModel,
            resolution: resolution,
            prompt: finalPrompt
        });
    } catch (err) {
        clearInterval(progressTimer);
        haptic('error');
        $('resultZone').innerHTML = '';
        showToast(`${err.message || '生成失败'}，点击重试`, generate);
    } finally {
        clearInterval(progressTimer);
        running = false;
        syncGenBtn();
    }
}

function renderResult(images, prompt, meta = {}) {
    const zone = $('resultZone');
    zone.innerHTML = '';
    images.forEach(url => {
        const wrap = document.createElement('div');
        wrap.className = 'result-card';
        wrap.innerHTML = `<img src="${escapeHtml(url)}" alt="生成结果">`;
        wrap.onclick = () => openPreview(url, prompt, Object.assign({ url, name: prompt || '生成结果' }, meta));
        zone.appendChild(wrap);
    });

    const primaryUrl = images[0];
    const actions = document.createElement('div');
    actions.className = 'result-actions';
    actions.innerHTML = `
        <button class="result-btn" id="btnUseAsRef"><i data-lucide="image-plus"></i>用作参考</button>
        <button class="result-btn" id="btnPushDesk"><i data-lucide="send"></i>推至电脑</button>
        <button class="result-btn" id="btnReuse"><i data-lucide="rotate-ccw"></i>复用参数</button>
        <a class="result-btn" href="${escapeHtml(primaryUrl)}" download><i data-lucide="download"></i>保存原图</a>`;

    actions.querySelector('#btnUseAsRef').onclick = () => {
        haptic('light');
        if (refs.length >= REF_MAX) { showToast(`参考图最多 ${REF_MAX} 张`); return; }
        refs.push({ url: primaryUrl, name: 'result' });
        renderRefs();
        showToast('已加入参考图');
    };
    actions.querySelector('#btnPushDesk').onclick = () => {
        pushToCanvas(primaryUrl, prompt || '生成结果', prompt);
    };
    actions.querySelector('#btnReuse').onclick = () => {
        reuseParameters(Object.assign({ prompt, name: prompt }, meta));
    };

    zone.appendChild(actions);
    try { lucide.createIcons(); } catch (_) {}
}

/* ============ 图片预览（交互增强 Lightbox） ============ */
function openPreview(url, prompt, itemMeta = null) {
    currentActiveItem = itemMeta || { url, name: prompt || '素材', prompt: prompt || '' };
    const lb = $('lightbox');
    const titleEl = $('lightboxTitle');
    const imgEl = $('lightboxImg');
    const actEl = $('lightboxActions');

    if (titleEl) titleEl.textContent = prompt || currentActiveItem.name || '预览图片';
    if (imgEl) {
        imgEl.src = url;
        imgEl.alt = prompt || '';
    }

    if (actEl) {
        actEl.innerHTML = `
            <button class="lightbox-btn" id="lbBtnRef"><i data-lucide="image-plus"></i>加为参考</button>
            <button class="lightbox-btn" id="lbBtnPush"><i data-lucide="send"></i>推至电脑</button>
            <button class="lightbox-btn" id="lbBtnReuse"><i data-lucide="rotate-ccw"></i>复用参数</button>
            <a class="lightbox-btn" href="${escapeHtml(url)}" download><i data-lucide="download"></i>保存原图</a>`;

        actEl.querySelector('#lbBtnRef').onclick = e => {
            e.stopPropagation();
            haptic('light');
            if (refs.length >= REF_MAX) { showToast(`参考图最多 ${REF_MAX} 张`); return; }
            refs.push({ url, name: currentActiveItem.name || 'history' });
            renderRefs();
            closePreview();
            closeHistoryDrawer();
            showToast('已添加参考图');
        };
        actEl.querySelector('#lbBtnPush').onclick = e => {
            e.stopPropagation();
            pushToCanvas(url, currentActiveItem.name || '推送图片', currentActiveItem.prompt || '', currentActiveItem.canvasId || '');
        };
        actEl.querySelector('#lbBtnReuse').onclick = e => {
            e.stopPropagation();
            reuseParameters(currentActiveItem);
        };
    }

    lb.classList.add('show');
    try { lucide.createIcons(); } catch (_) {}
}
function closePreview() {
    const lb = $('lightbox');
    if (lb) lb.classList.remove('show');
    const img = $('lightboxImg');
    if (img) img.style.transform = '';
    currentActiveItem = null;
}

/* ============ 手势下拉关闭 (Swipe-to-dismiss) ============ */
function setupGestureDismiss() {
    // 1. History Drawer 下拉关闭
    const drawerBody = $('drawerBody');
    const grid = $('historyGrid');
    let startY = 0;
    let currentY = 0;
    let isSwiping = false;

    if (drawerBody) {
        drawerBody.addEventListener('touchstart', e => {
            if (grid && grid.scrollTop > 0) return;
            startY = e.touches[0].clientY;
            currentY = startY;
            isSwiping = true;
            drawerBody.style.transition = 'none';
        }, { passive: true });

        drawerBody.addEventListener('touchmove', e => {
            if (!isSwiping) return;
            currentY = e.touches[0].clientY;
            const delta = currentY - startY;
            if (delta > 0) {
                drawerBody.style.transform = `translateY(${delta}px)`;
            }
        }, { passive: true });

        drawerBody.addEventListener('touchend', () => {
            if (!isSwiping) return;
            isSwiping = false;
            drawerBody.style.transition = 'transform .25s ease';
            const delta = currentY - startY;
            if (delta > 80) {
                haptic('light');
                closeHistoryDrawer();
            } else {
                drawerBody.style.transform = 'translateY(0)';
            }
        });
    }

    // 2. Lightbox 下拉关闭
    const lbBody = $('lightboxBody');
    let lbStartY = 0;
    let lbCurrentY = 0;
    let lbSwiping = false;
    if (lbBody) {
        lbBody.addEventListener('touchstart', e => {
            lbStartY = e.touches[0].clientY;
            lbCurrentY = lbStartY;
            lbSwiping = true;
        }, { passive: true });

        lbBody.addEventListener('touchmove', e => {
            if (!lbSwiping) return;
            lbCurrentY = e.touches[0].clientY;
            const delta = lbCurrentY - lbStartY;
            const img = $('lightboxImg');
            if (delta > 0 && img) {
                img.style.transform = `translateY(${delta * 0.7}px) scale(${Math.max(0.75, 1 - delta / 500)})`;
            }
        }, { passive: true });

        lbBody.addEventListener('touchend', () => {
            if (!lbSwiping) return;
            lbSwiping = false;
            const delta = lbCurrentY - lbStartY;
            const img = $('lightboxImg');
            if (delta > 70) {
                haptic('light');
                closePreview();
            } else if (img) {
                img.style.transform = '';
            }
        });
    }
}

/* ============ 主题 ============ */
function applySavedTheme() {
    try {
        const saved = localStorage.getItem('studio_theme');
        if (saved === 'light') {
            document.body.classList.add('light');
            $('metaThemeColor')?.setAttribute('content', '#f5f5f5');
        } else {
            $('metaThemeColor')?.setAttribute('content', '#111111');
        }
    } catch (_) {}
}
function toggleTheme() {
    haptic('light');
    document.body.classList.toggle('light');
    const isLight = document.body.classList.contains('light');
    $('metaThemeColor')?.setAttribute('content', isLight ? '#f5f5f5' : '#111111');
    try { localStorage.setItem('studio_theme', isLight ? 'light' : 'dark'); } catch (_) {}
    renderProviderSelect();
}

/* ============ Cookie 工具 ============ */
function getCookie(name) {
    const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : '';
}
function updateDesktopHint() {
    const hint = $('desktopHint');
    if (!hint) return;
    if (getCookie('prefer_desktop') === '1') {
        hint.textContent = '解除桌面版锁定';
        hint.style.color = 'var(--acc)';
    } else {
        hint.textContent = '不再跳转移动版';
        hint.style.color = '';
    }
}

/* ============ 初始化 ============ */
async function init() {
    // 1. PWA Service Worker 注册
    if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
        navigator.serviceWorker.register('/static/sw-mobile.js', { scope: '/' }).catch(() => {});
    }

    applySavedTheme();

    // 2. 交互手势与事件绑定
    setupGestureDismiss();
    $('themeBtn').onclick = toggleTheme;
    $('historyBtn').onclick = openHistoryDrawer;
    $('drawerClose').onclick = () => { haptic('light'); closeHistoryDrawer(); };
    $('historyMask').onclick = () => { haptic('light'); closeHistoryDrawer(); };
    $('pickAlbum').onclick = () => $('fileInput').click();
    $('fileInput').onchange = e => { addFiles(e.target.files); e.target.value = ''; };
    $('genBtn').onclick = generate;
    $('lightboxClose').onclick = () => { haptic('light'); closePreview(); };
    $('lightbox').onclick = e => {
        if (e.target === $('lightbox') || e.target === $('lightboxBody')) {
            haptic('light');
            closePreview();
        }
    };

    // 3. 表单防灾自动保存事件
    ['prompt', 'negativePrompt'].forEach(id => {
        $(id)?.addEventListener('input', scheduleSaveDraft);
    });
    ['ratio', 'resolution', 'count', 'quality'].forEach(id => {
        $(id)?.addEventListener('change', () => {
            haptic('light');
            scheduleSaveDraft();
        });
    });

    $('provider').onchange = e => {
        haptic('light');
        currentProviderId = e.target.value;
        currentModel = '';
        renderModelSelect();
        scheduleSaveDraft();
    };
    $('model').onchange = e => {
        haptic('light');
        currentModel = e.target.value;
        syncGenBtn();
        scheduleSaveDraft();
    };

    $('desktopLink').onclick = e => {
        e.preventDefault();
        document.cookie = 'prefer_desktop=1; path=/; max-age=2592000';
        location.href = '/';
    };
    $('desktopHint').onclick = e => {
        e.preventDefault();
        if (getCookie('prefer_desktop') === '1') {
            document.cookie = 'prefer_desktop=; path=/; max-age=0';
            showToast('已解除桌面版锁定，将按设备自动跳转');
            updateDesktopHint();
        } else {
            $('desktopLink').click();
        }
    };
    updateDesktopHint();

    // 4. 恢复本地草稿
    const hadDraft = restoreDraft();

    // 5. 拉取 Provider 配置并同步
    try {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error(await responseErrorMessage(res, '配置加载失败'));
        const cfg = await res.json();
        providers = Array.isArray(cfg.api_providers) ? cfg.api_providers : [];
        renderProviderSelect();
    } catch (err) {
        showToast(`${err.message || '配置加载失败'}，点击重试`, init);
    }

    syncGenBtn();
    try { lucide.createIcons(); } catch (_) {}
}

document.addEventListener('DOMContentLoaded', init);
