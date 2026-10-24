/**
 * CanvasShotBreakdown - Zero-Compute Video Shot Breakdown (逐帧拉片) Node & 2x3 Grid Cards
 * Part of MeansCanvas (开卷画布)
 */
(function(window) {
    'use strict';

    function injectShotBreakdownStyles() {
        if (document.getElementById('shotBreakdownStyles')) return;
        const style = document.createElement('style');
        style.id = 'shotBreakdownStyles';
        style.textContent = `
            .shotBreakdown-node { min-width: 310px; }
            .sb-body { display: flex; flex-direction: column; gap: 10px; }
            .sb-meta-row {
                display: flex; align-items: center; justify-content: space-between;
                font-size: 11px; color: var(--muted, #64748b); font-weight: 500;
            }
            .sb-meta-info {
                font-family: 'JetBrains Mono', monospace;
                font-size: 11px; color: var(--text, #111827); opacity: 0.82;
            }
            .sb-stage {
                position: relative; width: 100%; aspect-ratio: 16 / 9;
                border-radius: 10px; overflow: hidden;
                background: rgba(15, 20, 29, 0.06);
                border: 1px dashed var(--border, rgba(148, 163, 184, 0.35));
                display: flex; align-items: center; justify-content: center;
                transition: border-color 0.18s ease, background 0.18s ease;
            }
            .theme-dark .sb-stage, html.studio-theme-dark .sb-stage {
                background: rgba(255, 255, 255, 0.04);
                border-color: rgba(255, 255, 255, 0.14);
            }
            .sb-stage.has-video {
                border-style: solid;
                background: #0b0e14;
            }
            .sb-stage.drag-over {
                border-color: var(--accent, #c97b5a);
                background: rgba(201, 123, 90, 0.1);
            }
            .sb-stage video {
                width: 100%; height: 100%; object-fit: contain; display: block;
            }
            .sb-empty {
                display: flex; flex-direction: column; align-items: center; justify-content: center;
                gap: 6px; padding: 14px; text-align: center; cursor: pointer;
                color: var(--muted, #64748b); width: 100%; height: 100%;
            }
            .sb-empty:hover { color: var(--text, #111827); }
            .sb-empty span { font-size: 11px; font-weight: 500; line-height: 1.35; }
            .sb-sub-actions {
                display: flex; align-items: center; justify-content: flex-end;
                margin-top: -4px;
            }
            .sb-change-btn {
                background: none; border: none; padding: 2px 4px;
                font-size: 11px; font-weight: 500; color: var(--muted, #64748b);
                text-decoration: underline; cursor: pointer;
            }
            .sb-change-btn:hover { color: var(--text, #111827); }
            .sb-dim-label {
                font-size: 11px; font-weight: 600; color: var(--muted, #64748b);
                margin-bottom: -2px;
            }
            .sb-dim-grid {
                display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px;
            }
            .sb-dim-pill {
                display: inline-flex; align-items: center; justify-content: center; gap: 4px;
                height: 32px; border-radius: 999px;
                border: 1px solid var(--border, rgba(148, 163, 184, 0.28));
                background: rgba(148, 163, 184, 0.08);
                color: var(--muted, #64748b);
                font-size: 11px; font-weight: 600; cursor: pointer;
                transition: all 0.16s ease;
                padding: 0 6px; white-space: nowrap;
            }
            .sb-dim-pill svg { width: 13px; height: 13px; flex-shrink: 0; }
            .sb-dim-pill.active {
                border-color: var(--accent, #c97b5a);
                background: rgba(201, 123, 90, 0.15);
                color: var(--text, #111827);
            }
            .theme-dark .sb-dim-pill.active, html.studio-theme-dark .sb-dim-pill.active {
                background: rgba(201, 123, 90, 0.24);
                color: #f8fafc;
            }
            .sb-run-btn {
                width: 100%; height: 36px; border-radius: 9px;
                border: 1px solid rgba(17, 24, 39, 0.12);
                background: var(--text, #111827);
                color: var(--panel, #ffffff);
                font-size: 12px; font-weight: 600; letter-spacing: 0.02em;
                display: inline-flex; align-items: center; justify-content: center; gap: 6px;
                cursor: pointer; transition: opacity 0.15s ease, transform 0.1s ease;
            }
            .theme-dark .sb-run-btn, html.studio-theme-dark .sb-run-btn {
                background: #f1f5f9; color: #0f172a;
            }
            .sb-run-btn:hover:not(:disabled) { opacity: 0.9; }
            .sb-run-btn:disabled { opacity: 0.55; cursor: wait; }
        `;
        document.head.appendChild(style);
    }

    function t(key, fallback) {
        if (typeof window.tr === 'function') {
            const v = window.tr(key);
            if (v && v !== key) return v;
        }
        return fallback || key;
    }

    function resolveUpstreamVideoForBreakdown(node) {
        if (!node || !Array.isArray(window.connections) || !Array.isArray(window.nodes)) return null;
        const incoming = window.connections
            .filter(c => c.to === node.id)
            .map(c => window.nodes.find(n => n.id === c.from))
            .filter(Boolean);
        for (const up of incoming) {
            if (up.type === 'image' && up.url && window.mediaKindForNode?.(up) === 'video') {
                return { url: up.url, name: up.name || 'video.mp4', fromNodeId: up.id };
            }
            if (up.type === 'output' && Array.isArray(up.images)) {
                const rev = [...up.images].reverse();
                for (const item of rev) {
                    const u = window.outputUrlValue ? window.outputUrlValue(item) : (item?.url || item);
                    if (u && window.isVideoUrl?.(u)) {
                        return { url: u, name: window.outputImageName?.(u) || 'video.mp4', fromNodeId: up.id };
                    }
                }
            }
            if (typeof window.generatedImageRefs === 'function') {
                const refs = window.generatedImageRefs(up) || [];
                const vref = refs.find(r => r?.kind === 'video' || window.isVideoUrl?.(r?.url));
                if (vref?.url) {
                    return { url: vref.url, name: vref.name || 'video.mp4', fromNodeId: up.id };
                }
            }
            if ((up.type === 'group' || up.type === 'frame_group') && Array.isArray(up.items)) {
                for (const id of up.items) {
                    const item = window.nodes.find(x => x.id === id);
                    if (item?.type === 'image' && item.url && window.mediaKindForNode?.(item) === 'video') {
                        return { url: item.url, name: item.name || 'video.mp4', fromNodeId: item.id };
                    }
                }
            }
        }
        return null;
    }

    function effectiveShotBreakdownVideo(node) {
        const upstream = resolveUpstreamVideoForBreakdown(node);
        if (upstream?.url) return upstream;
        if (node?.videoUrl) return { url: node.videoUrl, name: node.videoName || 'video.mp4', fromNodeId: '' };
        return null;
    }

    async function probeShotBreakdownVideoMeta(node, url) {
        if (!node || !url) return;
        if (node._probingUrl === url) return;
        if (node.videoMeta && node.videoMeta.url === url) return;
        node._probingUrl = url;
        try {
            const resp = await fetch(`/api/video/probe?url=${encodeURIComponent(url)}`);
            if (!resp.ok) return;
            const data = await resp.json();
            if (data?.ok) {
                node.videoMeta = {
                    url,
                    duration: data.duration,
                    duration_text: data.duration_text || '00:00',
                    width: data.width || 0,
                    height: data.height || 0,
                    has_audio: Boolean(data.has_audio),
                };
                const el = document.querySelector(`.shotBreakdown-node[data-id="${CSS.escape(node.id)}"] .sb-meta-info`);
                if (el) {
                    el.textContent = formatVideoMetaText(node.videoMeta);
                }
                if (typeof window.scheduleSave === 'function') window.scheduleSave();
            }
        } catch (e) {
            // Silent fallback when probe is unavailable
        } finally {
            if (node._probingUrl === url) delete node._probingUrl;
        }
    }

    function formatVideoMetaText(meta) {
        if (!meta) return '--:--';
        const dur = meta.duration_text || '00:00';
        const dim = (meta.width && meta.height) ? ` · ${meta.width}×${meta.height}` : '';
        return `${dur}${dim}`;
    }

    function pickVideoForShotBreakdown(nodeId) {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'video/mp4,video/webm,video/quicktime,video/x-matroska,.mp4,.webm,.mov,.m4v,.mkv';
        input.onchange = async () => {
            const file = input.files?.[0];
            if (!file) return;
            await uploadVideoToShotBreakdownNode(nodeId, file);
        };
        input.click();
    }

    async function uploadVideoToShotBreakdownNode(nodeId, file) {
        const node = window.nodes?.find(n => n.id === nodeId);
        if (!node || !file) return;
        try {
            if (typeof window.setStatus === 'function') window.setStatus('Uploading video...');
            const form = new FormData();
            form.append('files', file);
            const r = await fetch('/api/ai/upload', { method: 'POST', body: form });
            const data = await r.json().catch(() => ({}));
            const uploaded = data?.files?.[0];
            if (!r.ok || !uploaded?.url) {
                throw new Error(data?.detail || '视频上传失败');
            }
            if (typeof window.pushUndo === 'function') window.pushUndo();
            node.videoUrl = uploaded.url;
            node.videoName = uploaded.name || file.name || 'video.mp4';
            node.videoMeta = null;
            if (typeof window.refreshNodes === 'function') window.refreshNodes([node.id]);
            else if (typeof window.render === 'function') window.render();
            if (typeof window.scheduleSave === 'function') window.scheduleSave();
            probeShotBreakdownVideoMeta(node, node.videoUrl);
        } catch (err) {
            if (typeof window.showErrorModal === 'function') {
                window.showErrorModal(err.message || '视频上传失败', '视频上传失败');
            }
        } finally {
            if (typeof window.setStatus === 'function') window.setStatus('Ready');
        }
    }

    function renderShotBreakdownBody(node) {
        injectShotBreakdownStyles();
        if (node.dimStoryboard === undefined) node.dimStoryboard = true;
        if (node.dimMotion === undefined) node.dimMotion = true;
        if (node.dimAudio === undefined) node.dimAudio = true;
        if (node.dimScript === undefined) node.dimScript = false;

        const src = effectiveShotBreakdownVideo(node);
        const videoUrl = src?.url || '';
        if (videoUrl && (!node.videoMeta || node.videoMeta.url !== videoUrl)) {
            probeShotBreakdownVideoMeta(node, videoUrl);
        }
        const metaText = videoUrl
            ? formatVideoMetaText(node.videoMeta?.url === videoUrl ? node.videoMeta : null)
            : '--:--';
        const isRunning = node.runStatus === 'running';

        const wrap = document.createElement('div');
        wrap.className = 'sb-body';
        wrap.innerHTML = `
            <div class="sb-meta-row">
                <span>${escapeHtml(t('canvas.sbVideoSource', '视频素材'))}</span>
                <span class="sb-meta-info">${escapeHtml(metaText)}</span>
            </div>
            <div class="sb-stage ${videoUrl ? 'has-video' : ''}">
                ${videoUrl
                    ? `<video src="${escapeAttr(videoUrl)}" data-url="${escapeAttr(videoUrl)}" controls preload="metadata" playsinline></video>`
                    : `<div class="sb-empty" data-sb-pick>
                        <i data-lucide="clapperboard" class="w-7 h-7"></i>
                        <span>${escapeHtml(t('canvas.sbUploadHint', '点击或拖入参考视频 / 连线视频节点'))}</span>
                    </div>`
                }
            </div>
            ${videoUrl ? `<div class="sb-sub-actions"><button type="button" class="sb-change-btn" data-sb-pick>${escapeHtml(t('canvas.sbChangeVideo', '更换视频'))}</button></div>` : ''}
            <div class="sb-dim-label">${escapeHtml(t('canvas.sbDimensions', '拆解维度'))}</div>
            <div class="sb-dim-grid">
                <button type="button" class="sb-dim-pill ${node.dimStoryboard ? 'active' : ''}" data-sb-dim="dimStoryboard">
                    <i data-lucide="layout-grid"></i><span>${escapeHtml(t('canvas.sbDimStoryboard', '分镜'))}</span>
                </button>
                <button type="button" class="sb-dim-pill ${node.dimMotion ? 'active' : ''}" data-sb-dim="dimMotion">
                    <i data-lucide="film"></i><span>${escapeHtml(t('canvas.sbDimMotion', '动态'))}</span>
                </button>
                <button type="button" class="sb-dim-pill ${node.dimAudio ? 'active' : ''}" data-sb-dim="dimAudio">
                    <i data-lucide="music"></i><span>${escapeHtml(t('canvas.sbDimAudio', '音乐'))}</span>
                </button>
                <button type="button" class="sb-dim-pill ${node.dimScript ? 'active' : ''}" data-sb-dim="dimScript">
                    <i data-lucide="file-text"></i><span>${escapeHtml(t('canvas.sbDimScript', '脚本'))}</span>
                </button>
            </div>
            <button type="button" class="sb-run-btn" data-sb-run ${isRunning ? 'disabled' : ''}>
                <span>${escapeHtml(isRunning ? t('canvas.sbRunning', '正在拉片...') : t('canvas.sbStart', '开始拉片'))}</span>
            </button>
        `;

        wrap.querySelectorAll('[data-sb-pick]').forEach(btn => {
            btn.onclick = e => {
                e.stopPropagation();
                pickVideoForShotBreakdown(node.id);
            };
        });

        const stage = wrap.querySelector('.sb-stage');
        if (stage) {
            stage.ondragover = e => {
                e.preventDefault();
                e.stopPropagation();
                stage.classList.add('drag-over');
            };
            stage.ondragleave = e => {
                e.stopPropagation();
                stage.classList.remove('drag-over');
            };
            stage.ondrop = async e => {
                e.preventDefault();
                e.stopPropagation();
                stage.classList.remove('drag-over');
                const droppedUrl = e.dataTransfer?.getData('application/x-canvas-output-image') || '';
                if (droppedUrl && window.isVideoUrl?.(droppedUrl)) {
                    node.videoUrl = droppedUrl;
                    node.videoName = window.outputImageName?.(droppedUrl) || 'video.mp4';
                    node.videoMeta = null;
                    window.refreshNodes?.([node.id]);
                    window.scheduleSave?.();
                    probeShotBreakdownVideoMeta(node, droppedUrl);
                    return;
                }
                const files = [...(e.dataTransfer?.files || [])];
                const videoFile = files.find(f => String(f.type || '').startsWith('video/') || /\.(mp4|webm|mov|m4v|mkv)$/i.test(f.name || ''));
                if (videoFile) {
                    await uploadVideoToShotBreakdownNode(node.id, videoFile);
                }
            };
        }

        wrap.querySelectorAll('[data-sb-dim]').forEach(btn => {
            btn.onclick = e => {
                e.stopPropagation();
                const field = btn.dataset.sbDim;
                node[field] = !node[field];
                btn.classList.toggle('active', Boolean(node[field]));
                window.scheduleSave?.();
            };
        });

        const runBtn = wrap.querySelector('[data-sb-run]');
        if (runBtn) {
            runBtn.onclick = e => {
                e.stopPropagation();
                runShotBreakdownNode(node.id);
            };
        }

        return wrap;
    }

    function addShotBreakdownNode(point, initialVideoUrl = '', initialVideoName = '') {
        if (typeof window.ensureCanvas === 'function' && !window.ensureCanvas()) return null;
        const p = point || (typeof window.defaultPoint === 'function' ? window.defaultPoint(120, 0) : { x: 200, y: 160 });
        return window.addNode({
            id: window.uid('sb'),
            type: 'shotBreakdown',
            x: p.x,
            y: p.y,
            w: 332,
            videoUrl: initialVideoUrl || '',
            videoName: initialVideoName || '',
            videoMeta: null,
            dimStoryboard: true,
            dimMotion: true,
            dimAudio: true,
            dimScript: false,
            breakdownChildIds: [],
        });
    }

    function openShotBreakdownFromVideoNode(sourceNodeId) {
        const src = window.nodes?.find(n => n.id === sourceNodeId);
        if (!src) return null;
        if (typeof window.pushUndo === 'function') window.pushUndo();
        const pt = {
            x: Math.round((src.x || 0) + (src.w || 280) + 84),
            y: Math.round(src.y || 0),
        };
        const sbNode = addShotBreakdownNode(pt, src.url || '', src.name || '');
        if (sbNode) {
            window.connections.push({ id: window.uid('c'), from: src.id, to: sbNode.id });
            window.render?.();
            window.scheduleSave?.();
            window.triggerConnectionAnimation?.(src.id, sbNode.id);
        }
        return sbNode;
    }

    function buildBreakdownGridOutputNode(parent, groupData, kind, x, y) {
        const groupId = window.uid('sbgrid');
        const cols = Math.max(1, Number(groupData.cols || 2));
        const rows = Math.max(1, Number(groupData.rows || 1));
        const layout = { type: 'grid-split', groupId, rows, cols, gap: 0 };
        const images = (groupData.items || []).map((item, idx) => ({
            url: item.url,
            kind,
            name: item.name || `${kind}-${idx + 1}`,
            model: item.badge || `#${String(item.shot_index || idx + 1).padStart(2, '0')}`,
            prompt: `${item.timecode || ''} (${item.duration || 0}s)`.trim(),
            runMs: 0,
            viewed: true,
            grid: {
                groupId,
                rows,
                cols,
                row: Number.isFinite(item.row) ? item.row : Math.floor(idx / cols),
                col: Number.isFinite(item.col) ? item.col : (idx % cols),
                w: Math.max(1, Number(item.w || 16)),
                h: Math.max(1, Number(item.h || 9)),
            },
        }));
        return {
            id: window.uid('out'),
            type: 'output',
            customTitle: groupData.title || (kind === 'video' ? '运镜动作' : '分镜组'),
            passAllRefs: true,
            shotBreakdownCard: true,
            x: Math.round(x),
            y: Math.round(y),
            w: 440,
            outputLayout: layout,
            images,
        };
    }

    async function runShotBreakdownNode(nodeId, runOpts = {}) {
        const node = window.nodes?.find(n => n.id === nodeId);
        if (!node || node.runStatus === 'running') return;
        const src = effectiveShotBreakdownVideo(node);
        if (!src?.url) {
            alert(t('canvas.sbNeedVideo', '请先上传参考视频或连线输入视频节点'));
            return;
        }
        if (!(node.dimStoryboard || node.dimMotion || node.dimAudio || node.dimScript)) {
            alert('请至少开启一个拆解维度（分镜 / 动态 / 音乐 / 脚本）');
            return;
        }

        const startedAt = Date.now();
        node.runStatus = 'running';
        window.refreshNodes?.([node.id]);

        try {
            const resp = await fetch('/api/video/breakdown', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_url: src.url,
                    extract_storyboard: Boolean(node.dimStoryboard),
                    extract_motion: Boolean(node.dimMotion),
                    extract_audio: Boolean(node.dimAudio),
                    extract_script: Boolean(node.dimScript),
                    group_size: 6,
                    max_shots: 18,
                    max_motion_clips: 4,
                }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || !data?.ok) {
                throw new Error(data?.detail || '逐帧拉片失败');
            }

            if (data.video_meta) {
                node.videoMeta = { url: src.url, ...data.video_meta };
            }

            if (typeof window.pushUndo === 'function') window.pushUndo();

            // 清理同节点上一次生成的旧拉片子节点（仅限仍与当前节点相连的自动产物）
            if (Array.isArray(node.breakdownChildIds) && node.breakdownChildIds.length) {
                const oldSet = new Set(
                    node.breakdownChildIds.filter(cid =>
                        window.connections.some(c => c.from === node.id && c.to === cid)
                    )
                );
                if (oldSet.size) {
                    window.nodes = window.nodes.filter(n => !oldSet.has(n.id));
                    window.connections = window.connections.filter(c => !oldSet.has(c.from) && !oldSet.has(c.to));
                }
            }

            const createdNodes = [];
            const startX = Math.round((node.x || 0) + (node.w || 332) + 120);
            const startY = Math.round((node.y || 0) - 80);
            const cardW = 440;
            const gapX = 36;
            const rowStepY = 390;

            const gridCards = [];
            (data.storyboard_groups || []).forEach(grp => {
                if (grp?.items?.length) gridCards.push({ data: grp, kind: 'image' });
            });
            if (data.motion_group?.items?.length) {
                gridCards.push({ data: data.motion_group, kind: 'video' });
            }

            gridCards.forEach((entry, idx) => {
                const col = idx % 2;
                const row = Math.floor(idx / 2);
                const cx = startX + col * (cardW + gapX);
                const cy = startY + row * rowStepY;
                const outNode = buildBreakdownGridOutputNode(node, entry.data, entry.kind, cx, cy);
                createdNodes.push(outNode);
            });

            const bottomRowIndex = Math.ceil(gridCards.length / 2);
            const bottomY = startY + bottomRowIndex * rowStepY;

            if (data.audio?.url) {
                createdNodes.push({
                    id: window.uid('img'),
                    type: 'image',
                    url: data.audio.url,
                    name: data.audio.name || '音频参考.mp3',
                    mediaKind: 'audio',
                    x: startX,
                    y: bottomY,
                    w: 320,
                });
            }

            if (data.script_text) {
                createdNodes.push({
                    id: window.uid('p'),
                    type: 'prompt',
                    text: data.script_text,
                    x: data.audio?.url ? (startX + 356) : startX,
                    y: bottomY,
                    w: 440,
                });
            }

            node.breakdownChildIds = createdNodes.map(n => n.id);
            createdNodes.forEach(child => {
                window.nodes.push(child);
                window.connections.push({ id: window.uid('c'), from: node.id, to: child.id });
            });

            node.runStatus = 'done';
            window.render?.();
            window.scheduleSave?.();
            createdNodes.forEach(child => {
                window.triggerConnectionAnimation?.(node.id, child.id);
            });

            if (typeof window.addGenerationLog === 'function') {
                const allUrls = [
                    ...(data.storyboard_groups || []).flatMap(g => (g.items || []).map(i => i.url)),
                    ...((data.motion_group?.items || []).map(i => i.url)),
                ].filter(Boolean);
                window.addGenerationLog({
                    title: '逐帧拉片',
                    status: 'done',
                    prompt: `${src.name || '视频'} · ${data.video_meta?.shot_count || 0} 个镜头`,
                    elapsedMs: Date.now() - startedAt,
                    images: allUrls.slice(0, 6),
                });
            }
        } catch (err) {
            node.runStatus = 'failed';
            window.refreshNodes?.([node.id]);
            if (!runOpts.cascade && typeof window.showErrorModal === 'function') {
                window.showErrorModal(err.message || '逐帧拉片失败', '逐帧拉片失败');
            }
        }
    }

    window.addShotBreakdownNode = addShotBreakdownNode;
    window.renderShotBreakdownBody = renderShotBreakdownBody;
    window.runShotBreakdownNode = runShotBreakdownNode;
    window.openShotBreakdownFromVideoNode = openShotBreakdownFromVideoNode;
})(window);
