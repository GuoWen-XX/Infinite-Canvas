/**
 * CanvasReve - Reve-Style Instruction & Regional Image Editing Module
 * Part of MeansCanvas (原 Infinite-Canvas)
 */
(function(window) {
    'use strict';

    // 与 static/js/canvas-list.js、api-settings.js 保持一致的转义实现。
    // 快捷条以 innerHTML 构建，一旦模型列表改为从 /api/providers 动态拉取，
    // 未转义的插值即成为存储型 XSS sink。
    function escapeHtml(str) {
        return String(str == null ? '' : str).replace(/[&<>"']/g, s => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[s]));
    }
    function escapeAttr(str) { return escapeHtml(str); }

    const CanvasReve = {
        activeNodeId: null,
        barEl: null,
        bboxActive: false,
        bboxOverlayEl: null,
        currentRegion: null,

        init() {
            // Keyboard shortcut Shift+E
            window.addEventListener('keydown', (e) => {
                if (e.shiftKey && (e.key === 'E' || e.key === 'e')) {
                    if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
                    const selId = Array.from(window.selected || [])[0];
                    if (selId) {
                        const node = window.nodes?.find(n => n.id === selId);
                        if (node && node.type === 'image' && node.url) {
                            e.preventDefault();
                            this.open(selId);
                        }
                    }
                } else if (e.key === 'Escape' && this.activeNodeId) {
                    this.close();
                }
            });

            // Close when clicking outside
            document.addEventListener('mousedown', (e) => {
                if (!this.activeNodeId) return;
                if (e.target.closest('#reveQuickBar, .reve-bbox-overlay, .node-reve-btn, [data-image-reve]')) return;
                this.close();
            });

            window.addEventListener('resize', () => {
                if (this.activeNodeId) this.updatePosition();
            });
            window.addEventListener('scroll', () => {
                if (this.activeNodeId) this.updatePosition();
            }, { passive: true });
        },

        open(nodeId) {
            const node = window.nodes?.find(n => n.id === nodeId);
            if (!node || node.type !== 'image' || !node.url) return;

            this.close();
            this.activeNodeId = nodeId;
            this.currentRegion = null;
            this.bboxActive = false;

            this.renderBar(node);
            this.updatePosition();
        },

        close() {
            if (this.barEl) {
                this.barEl.remove();
                this.barEl = null;
            }
            this.removeBoxOverlay();
            this.activeNodeId = null;
            this.currentRegion = null;
            this.bboxActive = false;
        },

        renderBar(node) {
            const bar = document.createElement('div');
            bar.id = 'reveQuickBar';
            bar.className = 'reve-quick-bar';

            const tr = window.tr || ((k, f) => f || k);
            const placeholder = tr('canvas.revePlaceholder', '输入修改指令（如：换成金黄晚霞背景、为人物戴上墨镜）...');
            const boxLabel = tr('canvas.reveBoxSelect', '选区框选');
            const submitLabel = tr('canvas.reveGenerate', '修图');

            const models = this.getAvailableEditModels(node);
            const modelOptions = models.map(m => `<option value="${escapeAttr(m.id)}" data-provider="${escapeAttr(m.providerId)}">${escapeHtml(m.label)}</option>`).join('');

            bar.innerHTML = `
                <i data-lucide="wand-2" class="w-4 h-4" style="color:var(--accent,#c97b5a);flex-shrink:0;"></i>
                <input type="text" class="reve-bar-input" id="revePromptInput" placeholder="${escapeAttr(placeholder)}" />
                <button type="button" class="reve-bar-btn" id="reveBoxToggle" title="${escapeAttr(boxLabel)}">
                    <i data-lucide="box-select" class="w-3.5 h-3.5"></i>
                    <span>${escapeHtml(boxLabel)}</span>
                </button>
                <select class="reve-model-select" id="reveModelSelect">
                    ${modelOptions}
                </select>
                <button type="button" class="reve-bar-submit" id="reveSubmitBtn">
                    <i data-lucide="arrow-right" class="w-3.5 h-3.5"></i>
                    <span>${escapeHtml(submitLabel)}</span>
                </button>
            `;

            document.body.appendChild(bar);
            this.barEl = bar;

            // Default model to node's existing model & provider if available
            const selectEl = bar.querySelector('#reveModelSelect');
            const targetModel = node?.model || '';
            const targetProv = node?.apiProvider || node?.providerId || node?.provider || '';
            if (targetModel && selectEl) {
                const opt = Array.from(selectEl.options).find(o =>
                    o.value === targetModel && (!targetProv || o.dataset.provider === targetProv)
                ) || Array.from(selectEl.options).find(o => o.value === targetModel);
                if (opt) selectEl.value = opt.value;
            }

            const input = bar.querySelector('#revePromptInput');
            input.focus();
            input.addEventListener('input', () => {
                input.classList.remove('reve-input-empty');
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.submit();
                }
            });

            bar.querySelector('#reveBoxToggle').addEventListener('click', () => {
                this.toggleBoxSelection();
            });

            bar.querySelector('#reveSubmitBtn').addEventListener('click', () => {
                this.submit();
            });

            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons({ root: bar });
            }
        },

        updatePosition() {
            if (!this.barEl || !this.activeNodeId) return;
            const nodeEl = document.querySelector(`.node[data-id="${this.activeNodeId}"]`);
            if (!nodeEl) {
                this.close();
                return;
            }
            const rect = nodeEl.getBoundingClientRect();
            const top = rect.bottom + 8 < window.innerHeight - 60 ? rect.bottom + 8 : Math.max(10, rect.top - 46);
            const left = Math.max(10, Math.min(window.innerWidth - 440, rect.left));
            this.barEl.style.top = `${top}px`;
            this.barEl.style.left = `${left}px`;
        },

        updateBoxButton() {
            const btn = this.barEl?.querySelector('#reveBoxToggle');
            if (!btn) return;
            const tr = window.tr || ((k, f) => f || k);
            const hasRegion = Boolean(this.currentRegion && this.currentRegion.width > 0 && this.currentRegion.height > 0);
            btn.classList.toggle('active', this.bboxActive || hasRegion);
            const span = btn.querySelector('span');
            if (span) {
                span.textContent = hasRegion ? tr('canvas.reveBoxSelected', '选区 (已框选)') : tr('canvas.reveBoxSelect', '选区框选');
            }
            btn.title = hasRegion ? tr('canvas.reveBoxSelectedTip', '选区已就绪，点击可重新框选') : tr('canvas.reveBoxSelect', '选区框选');
        },

        toggleBoxSelection() {
            this.bboxActive = !this.bboxActive;
            if (this.bboxActive) {
                this.mountBoxOverlay();
            } else {
                this.removeBoxOverlay();
            }
            this.updateBoxButton();
        },

        mountBoxOverlay() {
            this.removeBoxOverlay();
            const nodeEl = document.querySelector(`.node[data-id="${this.activeNodeId}"]`);
            if (!nodeEl) return;
            const wrap = nodeEl.querySelector('.image-preview-wrap') || nodeEl;
            const img = wrap.querySelector('img');

            const overlay = document.createElement('div');
            overlay.className = 'reve-bbox-overlay';

            const box = document.createElement('div');
            box.className = 'reve-bbox-rect';

            if (this.currentRegion && img) {
                const imgRect = img.getBoundingClientRect();
                const wrapRect = wrap.getBoundingClientRect();
                const nw = img.naturalWidth || imgRect.width;
                const nh = img.naturalHeight || imgRect.height;
                const sx = (imgRect.width || 1) / (nw || 1);
                const sy = (imgRect.height || 1) / (nh || 1);
                const relLeft = (imgRect.left - wrapRect.left) + this.currentRegion.x * sx;
                const relTop = (imgRect.top - wrapRect.top) + this.currentRegion.y * sy;
                box.style.left = `${Math.max(0, relLeft)}px`;
                box.style.top = `${Math.max(0, relTop)}px`;
                box.style.width = `${Math.max(4, this.currentRegion.width * sx)}px`;
                box.style.height = `${Math.max(4, this.currentRegion.height * sy)}px`;
                box.style.display = 'block';
            } else {
                box.style.display = 'none';
            }

            overlay.appendChild(box);
            wrap.appendChild(overlay);
            this.bboxOverlayEl = overlay;

            let isDrawing = false;
            let startX = 0, startY = 0;

            const onMouseMove = (e) => {
                if (!isDrawing) return;
                const rect = overlay.getBoundingClientRect();
                const curX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
                const curY = Math.max(0, Math.min(rect.height, e.clientY - rect.top));

                const left = Math.min(startX, curX);
                const top = Math.min(startY, curY);
                const width = Math.abs(curX - startX);
                const height = Math.abs(curY - startY);

                box.style.left = `${left}px`;
                box.style.top = `${top}px`;
                box.style.width = `${width}px`;
                box.style.height = `${height}px`;
                box.style.display = 'block';
            };

            const finishDrawing = (e) => {
                if (!isDrawing) return;
                isDrawing = false;
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', finishDrawing);

                const rect = overlay.getBoundingClientRect();
                const curX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
                const curY = Math.max(0, Math.min(rect.height, e.clientY - rect.top));

                const left = Math.min(startX, curX);
                const top = Math.min(startY, curY);
                const width = Math.abs(curX - startX);
                const height = Math.abs(curY - startY);

                if (width > 6 && height > 6) {
                    const targetImg = wrap.querySelector('img') || img;
                    if (targetImg) {
                        const imgRect = targetImg.getBoundingClientRect();
                        const nw = targetImg.naturalWidth || imgRect.width;
                        const nh = targetImg.naturalHeight || imgRect.height;

                        const screenLeft = rect.left + left;
                        const screenTop = rect.top + top;
                        const screenRight = screenLeft + width;
                        const screenBottom = screenTop + height;

                        const clampedLeft = Math.max(imgRect.left, Math.min(imgRect.right, screenLeft));
                        const clampedTop = Math.max(imgRect.top, Math.min(imgRect.bottom, screenTop));
                        const clampedRight = Math.max(imgRect.left, Math.min(imgRect.right, screenRight));
                        const clampedBottom = Math.max(imgRect.top, Math.min(imgRect.bottom, screenBottom));

                        const clampedW = clampedRight - clampedLeft;
                        const clampedH = clampedBottom - clampedTop;

                        if (clampedW > 4 && clampedH > 4) {
                            const scaleX = nw / (imgRect.width || 1);
                            const scaleY = nh / (imgRect.height || 1);

                            this.currentRegion = {
                                x: Math.round((clampedLeft - imgRect.left) * scaleX),
                                y: Math.round((clampedTop - imgRect.top) * scaleY),
                                width: Math.round(clampedW * scaleX),
                                height: Math.round(clampedH * scaleY),
                            };
                            this.updateBoxButton();
                            return;
                        }
                    }
                }
                box.style.display = 'none';
                this.currentRegion = null;
                this.updateBoxButton();
            };

            const onMouseDown = (e) => {
                e.stopPropagation();
                isDrawing = true;
                const rect = overlay.getBoundingClientRect();
                startX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
                startY = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
                box.style.left = `${startX}px`;
                box.style.top = `${startY}px`;
                box.style.width = '0px';
                box.style.height = '0px';
                box.style.display = 'block';

                window.addEventListener('mousemove', onMouseMove);
                window.addEventListener('mouseup', finishDrawing);
            };

            overlay.addEventListener('mousedown', onMouseDown);
            this._overlayCleanup = () => {
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', finishDrawing);
            };
        },

        removeBoxOverlay() {
            if (this._overlayCleanup) {
                this._overlayCleanup();
                this._overlayCleanup = null;
            }
            if (this.bboxOverlayEl) {
                this.bboxOverlayEl.remove();
                this.bboxOverlayEl = null;
            }
        },

        getAvailableEditModels(node) {
            const list = [];
            const seen = new Set();
            const add = (id, label, providerId) => {
                if (!id) return;
                const key = `${id}@@${providerId || ''}`;
                if (seen.has(key)) return;
                seen.add(key);
                list.push({ id, label: label || id, providerId: providerId || '' });
            };

            const nodeModel = node?.model || '';
            const nodeProvider = node?.apiProvider || node?.providerId || node?.provider || '';
            const providers = Array.isArray(window.apiProviders) ? window.apiProviders : [];

            if (nodeModel) {
                const provObj = providers.find(p => p.id === nodeProvider);
                const provName = provObj?.name || nodeProvider;
                add(nodeModel, provName ? `${nodeModel} (${provName})` : nodeModel, nodeProvider);
            }

            for (const p of providers) {
                if (!p || p.enabled === false) continue;
                const models = Array.isArray(p.image_models) ? p.image_models : [];
                for (const m of models) {
                    add(m, `${m} (${p.name || p.id})`, p.id);
                }
            }

            if (list.length === 0) {
                return [
                    { id: 'qwen-image-edit', label: '通义万相修图', providerId: 'siliconflow-cn' },
                    { id: 'flux-pro-1.0-fill', label: 'FLUX.1 Fill', providerId: 'bfl' },
                    { id: 'gpt-image-2', label: 'GPT Image 2', providerId: 'openai' },
                    { id: 'black-forest-labs/FLUX.2-klein-9B', label: 'FLUX Klein', providerId: 'modelscope' }
                ];
            }

            return list;
        },

        async submit() {
            if (!this.activeNodeId) return;
            const node = window.nodes?.find(n => n.id === this.activeNodeId);
            if (!node || !node.url) return;

            const input = this.barEl?.querySelector('#revePromptInput');
            const prompt = (input?.value || '').trim();
            if (!prompt) {
                const tr = window.tr || ((k, f) => f || k);
                const tip = tr('canvas.revePromptRequired', '请输入修图指令');
                if (typeof window.showToast === 'function') window.showToast(tip, 'warning');
                else if (typeof window.toast === 'function') window.toast(tip);
                else if (typeof window.showQuickNotification === 'function') window.showQuickNotification(tip);

                if (input) {
                    input.classList.add('reve-input-empty');
                    input.focus();
                    setTimeout(() => input.classList.remove('reve-input-empty'), 1500);
                }
                return;
            }

            const select = this.barEl?.querySelector('#reveModelSelect');
            const model = select?.value || node?.model || 'gpt-image-2';
            const selectedOpt = select?.selectedOptions?.[0];
            const providerId = selectedOpt?.dataset?.provider || node?.apiProvider || node?.providerId || '';
            const region = this.currentRegion;

            const sourceNodeId = this.activeNodeId;
            const sourceUrl = node.url;

            // Spawn derived node right next to original
            const newNodeId = 'node_' + Date.now() + '_' + Math.random().toString(36).substring(2, 6);
            const newNode = {
                id: newNodeId,
                type: 'image',
                name: (node.name || 'image') + ' (Reve Edit)',
                x: node.x + (node.w || 300) + 60,
                y: node.y,
                w: node.w || 300,
                h: node.h || 300,
                url: '',
                prompt: prompt,
                modelLabel: model,
                model: model,
                running: true,
                runStatus: 'running',
            };

            if (window.nodes) {
                if (typeof window.pushUndo === 'function') window.pushUndo();
                window.nodes.push(newNode);
                const connList = Array.isArray(window.connections) ? window.connections : (Array.isArray(window.links) ? window.links : null);
                if (connList) {
                    connList.push({
                        id: 'conn_' + Date.now(),
                        from: sourceNodeId,
                        to: newNodeId,
                    });
                }
                if (typeof window.render === 'function') window.render();
                if (typeof window.scheduleSave === 'function') window.scheduleSave();
            }

            this.close();

            try {
                const resp = await fetch('/api/canvas-edit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        source_image_url: sourceUrl,
                        prompt: prompt,
                        model: model,
                        provider_id: providerId,
                        region: region,
                    }),
                });

                if (!resp.ok) {
                    const errData = await resp.json().catch(() => ({}));
                    throw new Error(errData.detail || `请求失败 (${resp.status})`);
                }

                const data = await resp.json();
                newNode.url = data.output_url || '';
                newNode.running = false;
                newNode.runStatus = 'done';
                if (typeof window.render === 'function') window.render();
                if (typeof window.scheduleSave === 'function') window.scheduleSave();
            } catch (err) {
                newNode.running = false;
                newNode.runStatus = 'failed';
                newNode.runError = err.message || String(err);
                if (typeof window.render === 'function') window.render();
                if (window.showErrorModal) {
                    window.showErrorModal(err.message || String(err), 'Reve 修图失败');
                }
            }
        }
    };

    window.CanvasReve = CanvasReve;
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => CanvasReve.init());
    } else {
        CanvasReve.init();
    }
})(window);
