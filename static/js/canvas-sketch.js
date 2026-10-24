/**
 * Infinite-Canvas Sketch & Geometry System (Jaaz Magic Canvas Style)
 * =================================================================
 * Features:
 *   - Jaaz-style floating bottom Tool Dock (Select V, Hand H, Pen P, Arrow A, Line L, Rect R, Ellipse O, Text T)
 *   - Left floating Property Inspector (Stroke colors, Fill, Width S/M/L, Opacity, Layers & Delete)
 *   - 8-point resize handles + top rotation handle in board screen coordinates
 *   - Smooth freehand curve rendering (quadratic midpoint interpolation)
 *   - "Add to chat ⌘↵" one-click rasterize and feed directly to Agent references
 *   - Real-time Rhino 3D Viewport Direct-Push receiver & auto-insertion
 *   - Canvas persistence via canvas.settings.sketchElements
 */

(function(){
    'use strict';

    const CanvasSketch = {
        activeTool: 'select', // 'select' | 'hand' | 'pen' | 'arrow' | 'line' | 'rect' | 'ellipse' | 'text'
        strokeColor: '#ffffff',
        fillColor: 'transparent',
        strokeWidth: 4,
        lineStyle: 'solid', // 'solid' | 'dashed' | 'dotted'
        opacity: 1.0,
        elements: [], // Array of sketch element objects
        selectedElementIds: new Set(),
        activeDrag: null,
        undoStack: [],
        redoStack: [],
        isSpaceHeld: false,
        lastRhinoTimestamp: 0,
        rhinoWs: null,

        getDashArray(lineStyle, strokeWidth = 4) {
            const w = Number(strokeWidth) || 4;
            if (lineStyle === 'dashed') {
                const dash = Math.max(Math.round(w * 2.5), 8);
                const gap = Math.max(Math.round(w * 1.8), 6);
                return `${dash} ${gap}`;
            }
            if (lineStyle === 'dotted') {
                const dot = Math.max(Math.round(w * 0.5), 2);
                const gap = Math.max(Math.round(w * 2.2), 7);
                return `${dot} ${gap}`;
            }
            return '';
        },

        init() {
            this.cacheDom();
            this.bindEvents();
            this.startRhinoReceiver();
            this.loadInitialElements();
            if (window.lucide) window.lucide.createIcons();
        },

        cacheDom() {
            this.board = document.getElementById('board');
            this.world = document.getElementById('world');
            this.sketchLayer = document.getElementById('sketchLayer');
            this.elementsGroup = document.getElementById('sketchElementsGroup');
            this.tempGroup = document.getElementById('sketchTempGroup');
            this.toolDock = document.getElementById('canvasToolDock');
            this.propertyInspector = document.getElementById('sketchPropertyInspector');
            this.quickAction = document.getElementById('sketchQuickAction');
            this.transformBox = document.getElementById('sketchTransformBox');
            this.strokePalette = document.getElementById('sketchStrokePalette');
            this.fillPalette = document.getElementById('sketchFillPalette');
            this.widthGroup = document.getElementById('sketchWidthGroup');
            this.lineStyleGroup = document.getElementById('sketchLineStyleGroup');
            this.opacityGroup = document.getElementById('sketchOpacityGroup');
            this.clearBtn = document.getElementById('sketchClearBtn');
        },

        bindEvents() {
            // Tool dock switching
            if (this.toolDock) {
                this.toolDock.addEventListener('click', (e) => {
                    const btn = e.target.closest('.dock-tool-btn');
                    if (!btn) return;
                    const tool = btn.dataset.tool;
                    if (tool) {
                        this.setTool(tool);
                    }
                });
            }

            // Clear sketch with undo support (no blocking confirm)
            if (this.clearBtn) {
                this.clearBtn.addEventListener('click', () => {
                    if (!this.elements.length) return;
                    this.pushUndo();
                    this.elements = [];
                    this.selectedElementIds.clear();
                    this.renderElements();
                    this.updateTransformBox();
                    this.persist();
                    this.showToast('已清空手绘元素（按 Ctrl+Z 可撤销）');
                });
            }

            // Property inspector events
            if (this.strokePalette) {
                this.strokePalette.addEventListener('click', (e) => {
                    const swatch = e.target.closest('.color-swatch');
                    if (!swatch) return;
                    this.strokeColor = swatch.dataset.color;
                    this.strokePalette.querySelectorAll('.color-swatch').forEach(s => s.classList.toggle('active', s === swatch));
                    this.applyPropertyToSelected('stroke', this.strokeColor);
                });
            }

            if (this.fillPalette) {
                this.fillPalette.addEventListener('click', (e) => {
                    const swatch = e.target.closest('.color-swatch');
                    if (!swatch) return;
                    this.fillColor = swatch.dataset.color;
                    this.fillPalette.querySelectorAll('.color-swatch').forEach(s => s.classList.toggle('active', s === swatch));
                    this.applyPropertyToSelected('fill', this.fillColor);
                });
            }

            if (this.widthGroup) {
                this.widthGroup.addEventListener('click', (e) => {
                    const btn = e.target.closest('.width-btn');
                    if (!btn) return;
                    this.strokeWidth = Number(btn.dataset.width) || 4;
                    this.widthGroup.querySelectorAll('.width-btn').forEach(b => b.classList.toggle('active', b === btn));
                    this.applyPropertyToSelected('strokeWidth', this.strokeWidth);
                });
            }

            if (this.lineStyleGroup) {
                this.lineStyleGroup.addEventListener('click', (e) => {
                    const btn = e.target.closest('.style-btn');
                    if (!btn) return;
                    this.lineStyle = btn.dataset.style || 'solid';
                    this.lineStyleGroup.querySelectorAll('.style-btn').forEach(b => b.classList.toggle('active', b === btn));
                    this.applyPropertyToSelected('lineStyle', this.lineStyle);
                });
            }

            if (this.opacityGroup) {
                this.opacityGroup.addEventListener('click', (e) => {
                    const btn = e.target.closest('.opacity-btn');
                    if (!btn) return;
                    this.opacity = Number(btn.dataset.opacity) || 1.0;
                    this.opacityGroup.querySelectorAll('.opacity-btn').forEach(b => b.classList.toggle('active', b === btn));
                    this.applyPropertyToSelected('opacity', this.opacity);
                });
            }

            // Layer actions in inspector
            const bringFrontBtn = document.getElementById('sketchBringToFrontBtn');
            const sendBackBtn = document.getElementById('sketchSendToBackBtn');
            const duplicateBtn = document.getElementById('sketchDuplicateBtn');
            const deleteBtn = document.getElementById('sketchDeleteBtn');

            if (bringFrontBtn) {
                bringFrontBtn.addEventListener('click', () => this.bringSelectedToFront());
            }
            if (sendBackBtn) {
                sendBackBtn.addEventListener('click', () => this.sendSelectedToBack());
            }
            if (duplicateBtn) {
                duplicateBtn.addEventListener('click', () => this.duplicateSelected());
            }
            if (deleteBtn) {
                deleteBtn.addEventListener('click', () => this.deleteSelected());
            }

            // Quick Action (Add to chat)
            if (this.quickAction) {
                this.quickAction.addEventListener('click', () => this.addToChat());
            }

            // Board pointer events for robust, non-sticking drawing & transforms
            if (this.board) {
                this.board.addEventListener('pointerdown', (e) => this.onBoardPointerDown(e), true);
                this.board.addEventListener('mousedown', (e) => {
                    if (!this._lastPointerDownTime || Date.now() - this._lastPointerDownTime > 350) {
                        this.onBoardPointerDown(e);
                    }
                }, true);
            }
            window.addEventListener('pointermove', (e) => this.onWindowPointerMove(e));
            window.addEventListener('mousemove', (e) => {
                if (!this._lastPointerMoveTime || Date.now() - this._lastPointerMoveTime > 350) {
                    this.onWindowPointerMove(e);
                }
            });
            window.addEventListener('pointerup', (e) => this.onWindowPointerUp(e));
            window.addEventListener('pointercancel', (e) => this.onWindowPointerUp(e));
            window.addEventListener('mouseup', (e) => this.onWindowPointerUp(e));
            window.addEventListener('blur', () => this.onWindowPointerUp());

            // Transform handles
            if (this.transformBox) {
                this.transformBox.addEventListener('pointerdown', (e) => this.onTransformMouseDown(e));
                this.transformBox.addEventListener('mousedown', (e) => this.onTransformMouseDown(e));
            }

            // Keyboard shortcuts
            window.addEventListener('keydown', (e) => this.onKeyDown(e));
            window.addEventListener('keyup', (e) => this.onKeyUp(e));

            // Sync transform box on viewport pan/zoom
            const originalApplyViewport = window.applyViewport;
            if (typeof originalApplyViewport === 'function') {
                window.applyViewport = () => {
                    originalApplyViewport();
                    this.updateTransformBox();
                };
            }
        },

        capturePointer(e) {
            if (this.board && this.board.setPointerCapture && e && e.pointerId !== undefined) {
                try {
                    this.board.setPointerCapture(e.pointerId);
                    this._capturedPointerId = e.pointerId;
                } catch(err) {}
            }
        },

        releasePointer(pointerId) {
            const pid = pointerId !== undefined ? pointerId : this._capturedPointerId;
            if (this.board && this.board.releasePointerCapture && pid !== undefined) {
                try {
                    this.board.releasePointerCapture(pid);
                } catch(err) {}
            }
            this._capturedPointerId = null;
        },

        setTool(tool) {
            this.activeTool = tool;
            if (this.toolDock) {
                this.toolDock.querySelectorAll('.dock-tool-btn').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.tool === tool);
                });
            }

            if (this.board) {
                this.board.classList.toggle('sketch-drawing-mode', ['pen', 'arrow', 'line', 'rect', 'ellipse', 'text'].includes(tool));
                this.board.classList.toggle('sketch-hand-mode', tool === 'hand');
            }

            // Deselect elements if switching away from select tool
            if (tool !== 'select') {
                this.selectedElementIds.clear();
                this.updateTransformBox();
            }

            this.updateInspectorVisibility();

            if (tool === 'pen') {
                this.showToast('画笔绘制模式（按住空格键可平移画布）');
            } else if (tool === 'hand') {
                this.showToast('抓手平移模式（拖拽任意位置平移画布）');
            } else if (tool === 'select') {
                this.showToast('选择模式（点击选中或框选手绘元素）');
            }
        },

        updateInspectorVisibility() {
            if (!this.propertyInspector) return;
            const isDrawingTool = ['pen', 'arrow', 'line', 'rect', 'ellipse', 'text'].includes(this.activeTool);
            const hasSelection = this.selectedElementIds.size > 0;
            const shouldOpen = isDrawingTool || hasSelection;
            this.propertyInspector.classList.toggle('open', shouldOpen);

            // Update quick action visibility
            if (this.quickAction) {
                this.quickAction.classList.toggle('visible', this.elements.length > 0);
            }
        },

        // ===== Coordinate Helpers =====
        getMouseWorld(e) {
            if (typeof window.screenToWorld === 'function') {
                return window.screenToWorld(e.clientX, e.clientY);
            }
            const rect = this.board.getBoundingClientRect();
            const vp = window.viewport || { x: 0, y: 0, scale: 1 };
            return {
                x: (e.clientX - rect.left - vp.x) / vp.scale,
                y: (e.clientY - rect.top - vp.y) / vp.scale
            };
        },

        getWorldScreen(wx, wy) {
            if (typeof window.worldToBoardScreen === 'function') {
                return window.worldToBoardScreen(wx, wy);
            }
            const vp = window.viewport || { x: 0, y: 0, scale: 1 };
            return {
                x: wx * vp.scale + vp.x,
                y: wy * vp.scale + vp.y
            };
        },

        // ===== Pointer Event Handlers =====
        onBoardPointerDown(e) {
            // Deduplicate pointerdown and mousedown
            if (e.type === 'pointerdown') {
                this._lastPointerDownTime = Date.now();
            } else if (e.type === 'mousedown') {
                if (this._lastPointerDownTime && Date.now() - this._lastPointerDownTime < 350) return;
            }

            // Ignore if clicking inside UI controls or modals
            if (e.target.closest('#canvasToolDock, #sketchPropertyInspector, #sketchQuickAction, #sketchTransformBox, .panel, .node, .toolbar, #minimap, .modal, .agent-dock-trigger, #canvasAgentPanel, .create-menu')) {
                return;
            }

            // Middle click (wheel), Spacebar held, or Hand tool: ALWAYS pan canvas
            if (e.button === 1 || this.isSpaceHeld || this.activeTool === 'hand') {
                if (typeof window.startBoardPan === 'function') {
                    window.startBoardPan(e);
                }
                return;
            }

            // Only left click for drawing
            if (e.button !== 0) return;

            // Safety: if any previous drag is still dangling, finalize it before starting new
            if (this.activeDrag) {
                this.finalizeActiveDrag(e);
            }

            const mouse = this.getMouseWorld(e);

            if (this.activeTool === 'select') {
                const clickedElement = this.hitTestElement(mouse.x, mouse.y);
                if (clickedElement) {
                    if (e.shiftKey) {
                        if (this.selectedElementIds.has(clickedElement.id)) {
                            this.selectedElementIds.delete(clickedElement.id);
                        } else {
                            this.selectedElementIds.add(clickedElement.id);
                        }
                    } else {
                        this.selectedElementIds.clear();
                        this.selectedElementIds.add(clickedElement.id);
                    }
                    this.updateTransformBox();
                    this.syncInspectorWithSelected();
                    this.updateInspectorVisibility();

                    // Start moving selected elements
                    this.activeDrag = {
                        type: 'move',
                        pointerId: e.pointerId,
                        startX: mouse.x,
                        startY: mouse.y,
                        initialElements: this.elements.map(el => ({ ...el })),
                        initialElementsSnapshot: JSON.parse(JSON.stringify(this.elements))
                    };
                    this.capturePointer(e);
                    e.stopPropagation();
                } else {
                    // Clicked empty space: deselect sketch elements
                    if (this.selectedElementIds.size > 0) {
                        this.selectedElementIds.clear();
                        this.updateTransformBox();
                        this.updateInspectorVisibility();
                    }
                }
                return;
            }

            // Drawing tools: pen, rect, ellipse, line, arrow, text
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation?.();

            // Deselect any elements so transform box never interferes
            if (this.selectedElementIds.size > 0) {
                this.selectedElementIds.clear();
                this.updateTransformBox();
            }
            const id = 'sketch_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
            this.capturePointer(e);

            if (this.activeTool === 'pen') {
                this.activeDrag = {
                    type: 'draw_pen',
                    pointerId: e.pointerId,
                    id,
                    points: [[mouse.x, mouse.y]],
                    lastScreenX: e.clientX,
                    lastScreenY: e.clientY,
                    stroke: this.strokeColor,
                    strokeWidth: this.strokeWidth,
                    lineStyle: this.lineStyle,
                    opacity: this.opacity
                };
                this.renderTempPen(this.activeDrag);
            } else if (['rect', 'ellipse', 'line', 'arrow'].includes(this.activeTool)) {
                this.activeDrag = {
                    type: 'draw_shape',
                    pointerId: e.pointerId,
                    shape: this.activeTool,
                    id,
                    startX: mouse.x,
                    startY: mouse.y,
                    currX: mouse.x,
                    currY: mouse.y,
                    stroke: this.strokeColor,
                    strokeWidth: this.strokeWidth,
                    lineStyle: this.lineStyle,
                    fill: this.fillColor,
                    opacity: this.opacity
                };
            } else if (this.activeTool === 'text') {
                this.createInPlaceTextInput(mouse.x, mouse.y);
            }
        },

        onWindowPointerMove(e) {
            if (e.type === 'pointermove') {
                this._lastPointerMoveTime = Date.now();
            } else if (e.type === 'mousemove') {
                if (this._lastPointerMoveTime && Date.now() - this._lastPointerMoveTime < 350) return;
            }

            if (!this.activeDrag) return;

            // Defensive Liveness Guard: If left button is no longer down, automatically finalize!
            // This eliminates "sticky strokes" (粘连) caused by missed mouseup/pointerup events.
            if (e.buttons !== undefined && e.buttons !== 1 && !['resize', 'rotate'].includes(this.activeDrag.type)) {
                this.finalizeActiveDrag(e);
                return;
            }

            const mouse = this.getMouseWorld(e);

            if (this.activeDrag.type === 'draw_pen') {
                const pts = this.activeDrag.points;
                // Dynamic screen-distance sampling: sample every ~2.0 screen pixels regardless of zoom
                const screenDist = Math.hypot(e.clientX - this.activeDrag.lastScreenX, e.clientY - this.activeDrag.lastScreenY);
                if (screenDist >= 2.0 || pts.length < 2) {
                    pts.push([mouse.x, mouse.y]);
                    this.activeDrag.lastScreenX = e.clientX;
                    this.activeDrag.lastScreenY = e.clientY;
                    this.renderTempPen(this.activeDrag);
                }
            } else if (this.activeDrag.type === 'draw_shape') {
                this.activeDrag.currX = mouse.x;
                this.activeDrag.currY = mouse.y;
                this.renderTempShape(this.activeDrag);
            } else if (this.activeDrag.type === 'move') {
                const dx = mouse.x - this.activeDrag.startX;
                const dy = mouse.y - this.activeDrag.startY;
                const initialMap = new Map(this.activeDrag.initialElements.map(el => [el.id, el]));

                this.elements.forEach(el => {
                    if (this.selectedElementIds.has(el.id)) {
                        const init = initialMap.get(el.id);
                        if (!init) return;
                        el.x = init.x + dx;
                        el.y = init.y + dy;
                        if (init.points) {
                            el.points = init.points.map(([px, py]) => [px + dx, py + dy]);
                        }
                    }
                });
                this.renderElements();
                this.updateTransformBox();
            } else if (this.activeDrag.type === 'resize') {
                this.handleResizeMove(mouse);
            } else if (this.activeDrag.type === 'rotate') {
                this.handleRotateMove(mouse);
            }
        },

        onWindowPointerUp(e) {
            this.finalizeActiveDrag(e);
        },

        finalizeActiveDrag(e) {
            if (!this.activeDrag) return;
            const drag = this.activeDrag;
            this.activeDrag = null;
            this.releasePointer(drag.pointerId);

            if (drag.type === 'draw_pen') {
                if (drag.points.length > 1) {
                    const bounds = this.calcPointsBounds(drag.points);
                    const el = {
                        id: drag.id,
                        type: 'pen',
                        x: bounds.x,
                        y: bounds.y,
                        w: bounds.w,
                        h: bounds.h,
                        points: drag.points,
                        stroke: drag.stroke,
                        strokeWidth: drag.strokeWidth,
                        lineStyle: drag.lineStyle || this.lineStyle,
                        fill: 'transparent',
                        opacity: drag.opacity,
                        rotation: 0
                    };
                    this.pushUndo();
                    this.elements.push(el);
                } else if (drag.points.length === 1) {
                    const pt = drag.points[0];
                    const el = {
                        id: drag.id,
                        type: 'pen',
                        x: pt[0] - 2,
                        y: pt[1] - 2,
                        w: 4,
                        h: 4,
                        points: [[pt[0], pt[1]], [pt[0] + 0.1, pt[1] + 0.1]],
                        stroke: drag.stroke,
                        strokeWidth: drag.strokeWidth,
                        lineStyle: drag.lineStyle || this.lineStyle,
                        fill: 'transparent',
                        opacity: drag.opacity,
                        rotation: 0
                    };
                    this.pushUndo();
                    this.elements.push(el);
                }
                this.selectedElementIds.clear();
                if (this.tempGroup) this.tempGroup.innerHTML = '';
                this.renderElements();
                this.updateTransformBox();
                this.updateInspectorVisibility();
                this.persist();
            } else if (drag.type === 'draw_shape') {
                const w = Math.abs(drag.currX - drag.startX);
                const h = Math.abs(drag.currY - drag.startY);
                if (w > 3 || h > 3) {
                    const x = Math.min(drag.startX, drag.currX);
                    const y = Math.min(drag.startY, drag.currY);
                    const el = {
                        id: drag.id,
                        type: drag.shape,
                        x,
                        y,
                        w: Math.max(w, 8),
                        h: Math.max(h, 8),
                        startX: drag.startX,
                        startY: drag.startY,
                        endX: drag.currX,
                        endY: drag.currY,
                        stroke: drag.stroke,
                        strokeWidth: drag.strokeWidth,
                        lineStyle: drag.lineStyle || this.lineStyle,
                        fill: drag.fill,
                        opacity: drag.opacity,
                        rotation: 0
                    };
                    this.pushUndo();
                    this.elements.push(el);
                    // Do NOT auto-select shapes upon drawing! Keeps the user in fluid drawing flow
                    this.selectedElementIds.clear();
                }
                if (this.tempGroup) this.tempGroup.innerHTML = '';
                this.renderElements();
                this.updateTransformBox();
                this.updateInspectorVisibility();
                this.persist();
            } else if (['move', 'resize', 'rotate'].includes(drag.type)) {
                if (drag.initialElementsSnapshot) {
                    if (!this.undoStack) this.undoStack = [];
                    this.undoStack.push(drag.initialElementsSnapshot);
                    if (this.undoStack.length > 50) this.undoStack.shift();
                    this.redoStack = [];
                }
                this.persist();
            }
        },

        // ===== In-Place Text Input =====
        createInPlaceTextInput(wx, wy) {
            const screen = this.getWorldScreen(wx, wy);
            const input = document.createElement('textarea');
            input.className = 'sketch-text-input-overlay';
            input.style.left = `${screen.x}px`;
            input.style.top = `${screen.y}px`;
            input.style.minWidth = '120px';
            input.style.minHeight = '36px';
            input.style.fontSize = '16px';
            input.style.color = this.strokeColor === '#ffffff' ? '#ffffff' : this.strokeColor;
            input.placeholder = '输入文字...';
            this.board.appendChild(input);
            input.focus();

            const commitText = () => {
                const text = input.value.trim();
                input.remove();
                if (text) {
                    this.pushUndo();
                    const el = {
                        id: 'sketch_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6),
                        type: 'text',
                        x: wx,
                        y: wy,
                        text,
                        fontSize: 18,
                        stroke: this.strokeColor,
                        fill: this.strokeColor,
                        opacity: this.opacity,
                        rotation: 0
                    };
                    this.elements.push(el);
                    this.selectedElementIds.clear();
                    this.selectedElementIds.add(el.id);
                    this.renderElements();
                    this.updateTransformBox();
                    this.updateInspectorVisibility();
                    this.persist();
                }
            };

            input.addEventListener('blur', commitText);
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    commitText();
                } else if (e.key === 'Escape') {
                    input.remove();
                }
            });
        },

        // ===== Temp Previews =====
        renderTempPen(drag) {
            if (!this.tempGroup) return;
            const pathData = this.pointsToSmoothPath(drag.points);
            const dash = this.getDashArray(drag.lineStyle || this.lineStyle, drag.strokeWidth);
            const dashAttr = dash ? `stroke-dasharray="${dash}"` : '';
            this.tempGroup.innerHTML = `<path d="${pathData}" fill="none" stroke="${drag.stroke}" stroke-width="${drag.strokeWidth}" stroke-linecap="round" stroke-linejoin="round" opacity="${drag.opacity}" ${dashAttr} />`;
        },

        renderTempShape(drag) {
            if (!this.tempGroup) return;
            const w = Math.abs(drag.currX - drag.startX);
            const h = Math.abs(drag.currY - drag.startY);
            const x = Math.min(drag.startX, drag.currX);
            const y = Math.min(drag.startY, drag.currY);
            const dash = this.getDashArray(drag.lineStyle || this.lineStyle, drag.strokeWidth);
            const dashAttr = dash ? `stroke-dasharray="${dash}"` : '';

            let html = '';
            if (drag.shape === 'rect') {
                html = `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" fill="${drag.fill}" stroke="${drag.stroke}" stroke-width="${drag.strokeWidth}" opacity="${drag.opacity}" ${dashAttr} />`;
            } else if (drag.shape === 'ellipse') {
                html = `<ellipse cx="${x + w / 2}" cy="${y + h / 2}" rx="${w / 2}" ry="${h / 2}" fill="${drag.fill}" stroke="${drag.stroke}" stroke-width="${drag.strokeWidth}" opacity="${drag.opacity}" ${dashAttr} />`;
            } else if (drag.shape === 'line') {
                html = `<line x1="${drag.startX}" y1="${drag.startY}" x2="${drag.currX}" y2="${drag.currY}" stroke="${drag.stroke}" stroke-width="${drag.strokeWidth}" stroke-linecap="round" opacity="${drag.opacity}" ${dashAttr} />`;
            } else if (drag.shape === 'arrow') {
                html = `<line x1="${drag.startX}" y1="${drag.startY}" x2="${drag.currX}" y2="${drag.currY}" stroke="${drag.stroke}" stroke-width="${drag.strokeWidth}" stroke-linecap="round" marker-end="url(#sketchArrowMarker)" opacity="${drag.opacity}" ${dashAttr} />`;
            }
            this.tempGroup.innerHTML = html;
        },

        // ===== SVG Elements Rendering =====
        renderElements() {
            if (!this.elementsGroup) return;
            let svgHtml = '';

            this.elements.forEach(el => {
                const isSelected = this.selectedElementIds.has(el.id);
                const selClass = isSelected ? 'selected' : '';
                const rot = el.rotation ? `transform="rotate(${el.rotation}, ${el.x + (el.w || 0) / 2}, ${el.y + (el.h || 0) / 2})"` : '';
                const dash = this.getDashArray(el.lineStyle || 'solid', el.strokeWidth);
                const dashAttr = dash ? `stroke-dasharray="${dash}"` : '';

                if (el.type === 'pen' && el.points) {
                    const d = this.pointsToSmoothPath(el.points);
                    svgHtml += `<path class="sketch-element ${selClass}" data-id="${el.id}" d="${d}" fill="none" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" stroke-linecap="round" stroke-linejoin="round" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                } else if (el.type === 'rect') {
                    svgHtml += `<rect class="sketch-element ${selClass}" data-id="${el.id}" x="${el.x}" y="${el.y}" width="${el.w}" height="${el.h}" rx="4" fill="${el.fill}" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                } else if (el.type === 'ellipse') {
                    svgHtml += `<ellipse class="sketch-element ${selClass}" data-id="${el.id}" cx="${el.x + el.w / 2}" cy="${el.y + el.h / 2}" rx="${el.w / 2}" ry="${el.h / 2}" fill="${el.fill}" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                } else if (el.type === 'line') {
                    svgHtml += `<line class="sketch-element ${selClass}" data-id="${el.id}" x1="${el.startX || el.x}" y1="${el.startY || el.y}" x2="${el.endX || (el.x + el.w)}" y2="${el.endY || (el.y + el.h)}" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" stroke-linecap="round" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                } else if (el.type === 'arrow') {
                    svgHtml += `<line class="sketch-element ${selClass}" data-id="${el.id}" x1="${el.startX || el.x}" y1="${el.startY || el.y}" x2="${el.endX || (el.x + el.w)}" y2="${el.endY || (el.y + el.h)}" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" stroke-linecap="round" marker-end="url(#sketchArrowMarker)" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                } else if (el.type === 'text') {
                    svgHtml += `<text class="sketch-element ${selClass}" data-id="${el.id}" x="${el.x}" y="${el.y + (el.fontSize || 18)}" fill="${el.fill || el.stroke}" font-size="${el.fontSize || 18}px" font-family="var(--font-mixed)" font-weight="500" opacity="${el.opacity}" ${rot}>${this.escapeHtml(el.text)}</text>`;
                }
            });

            this.elementsGroup.innerHTML = svgHtml;
        },

        // ===== Curve Smoothing =====
        pointsToSmoothPath(points) {
            if (!points || !points.length) return '';
            if (points.length === 1) return `M ${points[0][0]} ${points[0][1]} L ${points[0][0] + 0.1} ${points[0][1] + 0.1}`;
            if (points.length === 2) return `M ${points[0][0]} ${points[0][1]} L ${points[1][0]} ${points[1][1]}`;
            let d = `M ${points[0][0]} ${points[0][1]}`;
            const m0x = (points[0][0] + points[1][0]) / 2;
            const m0y = (points[0][1] + points[1][1]) / 2;
            d += ` L ${m0x} ${m0y}`;
            for (let i = 1; i < points.length - 1; i++) {
                const xc = (points[i][0] + points[i + 1][0]) / 2;
                const yc = (points[i][1] + points[i + 1][1]) / 2;
                d += ` Q ${points[i][0]} ${points[i][1]}, ${xc} ${yc}`;
            }
            const last = points[points.length - 1];
            d += ` L ${last[0]} ${last[1]}`;
            return d;
        },

        calcPointsBounds(points) {
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            points.forEach(([x, y]) => {
                if (x < minX) minX = x;
                if (y < minY) minY = y;
                if (x > maxX) maxX = x;
                if (y > maxY) maxY = y;
            });
            return {
                x: minX,
                y: minY,
                w: Math.max(maxX - minX, 6),
                h: Math.max(maxY - minY, 6)
            };
        },

        // ===== Hit Testing =====
        hitTestElement(wx, wy) {
            // Test from top to bottom
            for (let i = this.elements.length - 1; i >= 0; i--) {
                const el = this.elements[i];
                const pad = Math.max((el.strokeWidth || 4) + 6, 10);
                if (el.type === 'pen' && el.points) {
                    for (const [px, py] of el.points) {
                        const dist = Math.hypot(wx - px, wy - py);
                        if (dist <= pad) return el;
                    }
                } else {
                    const ex = el.x - pad;
                    const ey = el.y - pad;
                    const ew = (el.w || 20) + pad * 2;
                    const eh = (el.h || 20) + pad * 2;
                    if (wx >= ex && wx <= ex + ew && wy >= ey && wy <= ey + eh) {
                        return el;
                    }
                }
            }
            return null;
        },

        // ===== Transform Box & Handles =====
        updateTransformBox() {
            if (!this.transformBox) return;
            if (this.activeTool !== 'select' || this.selectedElementIds.size === 0) {
                this.transformBox.style.display = 'none';
                return;
            }

            const selectedEls = this.elements.filter(el => this.selectedElementIds.has(el.id));
            if (!selectedEls.length) {
                this.transformBox.style.display = 'none';
                return;
            }

            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            selectedEls.forEach(el => {
                minX = Math.min(minX, el.x);
                minY = Math.min(minY, el.y);
                maxX = Math.max(maxX, el.x + (el.w || 20));
                maxY = Math.max(maxY, el.y + (el.h || 20));
            });

            const p1 = this.getWorldScreen(minX, minY);
            const p2 = this.getWorldScreen(maxX, maxY);

            this.transformBox.style.left = `${Math.min(p1.x, p2.x)}px`;
            this.transformBox.style.top = `${Math.min(p1.y, p2.y)}px`;
            this.transformBox.style.width = `${Math.abs(p2.x - p1.x)}px`;
            this.transformBox.style.height = `${Math.abs(p2.y - p1.y)}px`;
            this.transformBox.style.display = 'block';
        },

        onTransformMouseDown(e) {
            if (this.activeTool !== 'select') return;
            const handle = e.target.dataset.handle;
            if (!handle) return;
            e.stopPropagation();

            const selectedEls = this.elements.filter(el => this.selectedElementIds.has(el.id));
            if (!selectedEls.length) return;

            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            selectedEls.forEach(el => {
                minX = Math.min(minX, el.x);
                minY = Math.min(minY, el.y);
                maxX = Math.max(maxX, el.x + (el.w || 20));
                maxY = Math.max(maxY, el.y + (el.h || 20));
            });

            const mouse = this.getMouseWorld(e);
            const initialElementsSnapshot = JSON.parse(JSON.stringify(this.elements));

            if (handle === 'rotate') {
                const cx = (minX + maxX) / 2;
                const cy = (minY + maxY) / 2;
                this.activeDrag = {
                    type: 'rotate',
                    cx,
                    cy,
                    selectedEls,
                    initialRotation: selectedEls[0]?.rotation || 0,
                    startAngle: Math.atan2(mouse.y - cy, mouse.x - cx),
                    initialElementsSnapshot
                };
            } else {
                this.activeDrag = {
                    type: 'resize',
                    handle,
                    minX,
                    minY,
                    maxX,
                    maxY,
                    selectedEls,
                    startX: mouse.x,
                    startY: mouse.y,
                    initialStates: selectedEls.map(el => ({ ...el })),
                    initialElementsSnapshot
                };
            }
        },

        handleRotateMove(mouse) {
            const drag = this.activeDrag;
            const currentAngle = Math.atan2(mouse.y - drag.cy, mouse.x - drag.cx);
            const deltaAngle = (currentAngle - drag.startAngle) * (180 / Math.PI);
            const nextRot = Math.round((drag.initialRotation + deltaAngle) % 360);

            drag.selectedEls.forEach(el => {
                el.rotation = nextRot;
            });
            this.renderElements();
            this.updateTransformBox();
        },

        handleResizeMove(mouse) {
            const drag = this.activeDrag;
            const dx = mouse.x - drag.startX;
            const dy = mouse.y - drag.startY;

            let newMinX = drag.minX, newMinY = drag.minY, newMaxX = drag.maxX, newMaxY = drag.maxY;

            if (drag.handle.includes('w')) newMinX += dx;
            if (drag.handle.includes('e')) newMaxX += dx;
            if (drag.handle.includes('n')) newMinY += dy;
            if (drag.handle.includes('s')) newMaxY += dy;

            const oldW = Math.max(drag.maxX - drag.minX, 1);
            const oldH = Math.max(drag.maxY - drag.minY, 1);
            const newW = Math.max(newMaxX - newMinX, 10);
            const newH = Math.max(newMaxY - newMinY, 10);
            const scaleX = newW / oldW;
            const scaleY = newH / oldH;

            const initialMap = new Map(drag.initialStates.map(s => [s.id, s]));

            drag.selectedEls.forEach(el => {
                const init = initialMap.get(el.id);
                if (!init) return;
                const relX = (init.x - drag.minX) * scaleX;
                const relY = (init.y - drag.minY) * scaleY;
                el.x = newMinX + relX;
                el.y = newMinY + relY;
                el.w = Math.max((init.w || 20) * scaleX, 4);
                el.h = Math.max((init.h || 20) * scaleY, 4);

                if (init.points) {
                    el.points = init.points.map(([px, py]) => [
                        newMinX + (px - drag.minX) * scaleX,
                        newMinY + (py - drag.minY) * scaleY
                    ]);
                }
            });

            this.renderElements();
            this.updateTransformBox();
        },

        // ===== Property & Layer Manipulations =====
        applyPropertyToSelected(prop, val) {
            if (this.selectedElementIds.size === 0) return;
            this.pushUndo();
            this.elements.forEach(el => {
                if (this.selectedElementIds.has(el.id)) {
                    el[prop] = val;
                    if (prop === 'stroke' && el.type === 'text') {
                        el.fill = val;
                    }
                }
            });
            this.renderElements();
            this.persist();
        },

        syncInspectorWithSelected() {
            const first = this.elements.find(el => this.selectedElementIds.has(el.id));
            if (!first) return;

            if (first.stroke && this.strokePalette) {
                this.strokeColor = first.stroke;
                this.strokePalette.querySelectorAll('.color-swatch').forEach(s => {
                    s.classList.toggle('active', s.dataset.color === first.stroke);
                });
            }
            if (first.fill && this.fillPalette) {
                this.fillColor = first.fill;
                this.fillPalette.querySelectorAll('.color-swatch').forEach(s => {
                    s.classList.toggle('active', s.dataset.color === first.fill);
                });
            }
            if (first.strokeWidth && this.widthGroup) {
                this.strokeWidth = first.strokeWidth;
                this.widthGroup.querySelectorAll('.width-btn').forEach(b => {
                    b.classList.toggle('active', Number(b.dataset.width) === first.strokeWidth);
                });
            }
            if (first.opacity !== undefined && this.opacityGroup) {
                this.opacity = first.opacity;
                this.opacityGroup.querySelectorAll('.opacity-btn').forEach(b => {
                    b.classList.toggle('active', Number(b.dataset.opacity) === first.opacity);
                });
            }
            if (this.lineStyleGroup) {
                const style = first.lineStyle || 'solid';
                this.lineStyle = style;
                this.lineStyleGroup.querySelectorAll('.style-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.style === style);
                });
            }
        },

        bringSelectedToFront() {
            if (!this.selectedElementIds.size) return;
            this.pushUndo();
            const selected = this.elements.filter(el => this.selectedElementIds.has(el.id));
            const unselected = this.elements.filter(el => !this.selectedElementIds.has(el.id));
            this.elements = [...unselected, ...selected];
            this.renderElements();
            this.persist();
        },

        sendSelectedToBack() {
            if (!this.selectedElementIds.size) return;
            this.pushUndo();
            const selected = this.elements.filter(el => this.selectedElementIds.has(el.id));
            const unselected = this.elements.filter(el => !this.selectedElementIds.has(el.id));
            this.elements = [...selected, ...unselected];
            this.renderElements();
            this.persist();
        },

        duplicateSelected() {
            if (!this.selectedElementIds.size) return;
            this.pushUndo();
            const newIds = new Set();
            const copies = [];

            this.elements.forEach(el => {
                if (this.selectedElementIds.has(el.id)) {
                    const copy = JSON.parse(JSON.stringify(el));
                    copy.id = 'sketch_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
                    copy.x += 24;
                    copy.y += 24;
                    if (copy.points) {
                        copy.points = copy.points.map(([px, py]) => [px + 24, py + 24]);
                    }
                    copies.push(copy);
                    newIds.add(copy.id);
                }
            });

            this.elements.push(...copies);
            this.selectedElementIds = newIds;
            this.renderElements();
            this.updateTransformBox();
            this.persist();
        },

        deleteSelected() {
            if (!this.selectedElementIds.size) return;
            this.pushUndo();
            this.elements = this.elements.filter(el => !this.selectedElementIds.has(el.id));
            this.selectedElementIds.clear();
            this.renderElements();
            this.updateTransformBox();
            this.updateInspectorVisibility();
            this.persist();
        },

        // ===== Undo / Redo History =====
        pushUndo() {
            if (!this.undoStack) this.undoStack = [];
            this.undoStack.push(JSON.parse(JSON.stringify(this.elements)));
            if (this.undoStack.length > 50) this.undoStack.shift();
            this.redoStack = [];
        },

        performUndo() {
            if (!this.undoStack || this.undoStack.length === 0) {
                this.showToast('没有可撤销的手绘操作');
                return;
            }
            if (!this.redoStack) this.redoStack = [];
            this.redoStack.push(JSON.parse(JSON.stringify(this.elements)));
            this.elements = this.undoStack.pop();
            this.selectedElementIds.clear();
            if (this.tempGroup) this.tempGroup.innerHTML = '';
            this.renderElements();
            this.updateTransformBox();
            this.updateInspectorVisibility();
            this.persist();
            this.showToast('已撤销上一步操作');
        },

        performRedo() {
            if (!this.redoStack || this.redoStack.length === 0) {
                return;
            }
            this.undoStack.push(JSON.parse(JSON.stringify(this.elements)));
            this.elements = this.redoStack.pop();
            this.selectedElementIds.clear();
            if (this.tempGroup) this.tempGroup.innerHTML = '';
            this.renderElements();
            this.updateTransformBox();
            this.updateInspectorVisibility();
            this.persist();
            this.showToast('已恢复重做');
        },

        onKeyDown(e) {
            // Ignore if typing in input/textarea or contenteditable
            if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.target.isContentEditable) return;

            const sketchActive = (this.activeTool && this.activeTool !== 'select' && this.activeTool !== 'hand') || (this.selectedElementIds && this.selectedElementIds.size > 0);
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
                if (e.shiftKey) {
                    if (sketchActive && this.redoStack && this.redoStack.length > 0) {
                        e.preventDefault();
                        e.stopPropagation();
                        this.performRedo();
                    }
                } else if (sketchActive && this.undoStack && this.undoStack.length > 0) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.performUndo();
                }
                return;
            }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
                if (sketchActive && this.redoStack && this.redoStack.length > 0) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.performRedo();
                }
                return;
            }

            if (!e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
                const toolMap = { v: 'select', h: 'hand', p: 'pen', o: 'ellipse', a: 'arrow', t: 'text' };
                const mappedTool = toolMap[e.key.toLowerCase()];
                if (mappedTool) {
                    this.setTool(mappedTool);
                    return;
                }
            }

            if (e.code === 'Space' && !this.isSpaceHeld) {
                this.isSpaceHeld = true;
                if (this.board) this.board.classList.add('sketch-space-pan');
                return;
            }

            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (this.selectedElementIds.size > 0) {
                    e.preventDefault();
                    this.deleteSelected();
                }
            } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                this.addToChat();
            } else if (e.key === 'Escape') {
                this.setTool('select');
                this.selectedElementIds.clear();
                this.updateTransformBox();
                this.updateInspectorVisibility();
            }
        },

        onKeyUp(e) {
            if (e.code === 'Space') {
                this.isSpaceHeld = false;
                if (this.board) this.board.classList.remove('sketch-space-pan');
            }
        },

        // ===== Add to Chat ⌘↵ (Rasterize to PNG and Feed to Canvas Agent) =====
        async addToChat() {
            const targetEls = this.selectedElementIds.size > 0
                ? this.elements.filter(el => this.selectedElementIds.has(el.id))
                : this.elements;

            if (!targetEls.length) {
                this.showToast('画布上暂无手绘草图，请先用画笔绘制');
                return;
            }

            this.showToast('正在栅格化草图并加入 Agent...');

            try {
                // Calculate bounding box
                let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
                targetEls.forEach(el => {
                    minX = Math.min(minX, el.x);
                    minY = Math.min(minY, el.y);
                    maxX = Math.max(maxX, el.x + (el.w || 40));
                    maxY = Math.max(maxY, el.y + (el.h || 40));
                });

                const pad = 36;
                minX -= pad;
                minY -= pad;
                maxX += pad;
                maxY += pad;

                const width = Math.max(Math.round(maxX - minX), 120);
                const height = Math.max(Math.round(maxY - minY), 120);

                // Clone target elements SVG string translated to origin
                let contentSvg = '';
                targetEls.forEach(el => {
                    const rot = el.rotation ? `transform="rotate(${el.rotation}, ${el.x - minX + (el.w || 0) / 2}, ${el.y - minY + (el.h || 0) / 2})"` : '';
                    const dash = this.getDashArray(el.lineStyle || 'solid', el.strokeWidth);
                    const dashAttr = dash ? `stroke-dasharray="${dash}"` : '';

                    if (el.type === 'pen' && el.points) {
                        const localPoints = el.points.map(([px, py]) => [px - minX, py - minY]);
                        const d = this.pointsToSmoothPath(localPoints);
                        contentSvg += `<path d="${d}" fill="none" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" stroke-linecap="round" stroke-linejoin="round" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                    } else if (el.type === 'rect') {
                        contentSvg += `<rect x="${el.x - minX}" y="${el.y - minY}" width="${el.w}" height="${el.h}" rx="4" fill="${el.fill}" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                    } else if (el.type === 'ellipse') {
                        contentSvg += `<ellipse cx="${el.x - minX + el.w / 2}" cy="${el.y - minY + el.h / 2}" rx="${el.w / 2}" ry="${el.h / 2}" fill="${el.fill}" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                    } else if (el.type === 'line' || el.type === 'arrow') {
                        const marker = el.type === 'arrow' ? 'marker-end="url(#sketchArrowMarker)"' : '';
                        contentSvg += `<line x1="${(el.startX || el.x) - minX}" y1="${(el.startY || el.y) - minY}" x2="${(el.endX || (el.x + el.w)) - minX}" y2="${(el.endY || (el.y + el.h)) - minY}" stroke="${el.stroke}" stroke-width="${el.strokeWidth}" stroke-linecap="round" ${marker} opacity="${el.opacity}" ${dashAttr} ${rot} />`;
                    } else if (el.type === 'text') {
                        contentSvg += `<text x="${el.x - minX}" y="${el.y - minY + (el.fontSize || 18)}" fill="${el.fill || el.stroke}" font-size="${el.fontSize || 18}px" font-family="sans-serif" font-weight="500" opacity="${el.opacity}" ${rot}>${this.escapeHtml(el.text)}</text>`;
                    }
                });

                const fullSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                    <defs>
                        <marker id="sketchArrowMarker" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#ffffff" />
                        </marker>
                    </defs>
                    <rect width="100%" height="100%" fill="#18181b" />
                    ${contentSvg}
                </svg>`;

                const blob = new Blob([fullSvg], { type: 'image/svg+xml;charset=utf-8' });
                const url = URL.createObjectURL(blob);

                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    canvas.width = width * 2;
                    canvas.height = height * 2;
                    const ctx = canvas.getContext('2d');
                    ctx.scale(2, 2);
                    ctx.drawImage(img, 0, 0);
                    URL.revokeObjectURL(url);

                    const pngDataUrl = canvas.toDataURL('image/png');

                    // Register to CanvasAgent
                    const sketchRef = {
                        id: 'sketch_' + Date.now(),
                        type: 'image',
                        url: pngDataUrl,
                        name: '手绘草图'
                    };

                    if (window.CanvasAgent && typeof window.CanvasAgent.addReferencedNode === 'function') {
                        window.CanvasAgent.addReferencedNode(sketchRef);
                    }

                    // Open Agent panel if closed
                    const agentPanel = document.getElementById('canvasAgentPanel');
                    if (agentPanel && !agentPanel.classList.contains('open')) {
                        agentPanel.classList.add('open');
                        const toggle = document.getElementById('canvasAgentToggle');
                        if (toggle) toggle.classList.add('active');
                    }

                    const input = document.getElementById('agentInput');
                    if (input) {
                        input.focus();
                        if (!input.value) {
                            input.value = tr('canvas.sketchAgentPrompt');
                        }
                    }

                    this.showToast(tr('canvas.sketchAgentToast'));
                };
                img.onerror = () => {
                    URL.revokeObjectURL(url);
                    this.showToast('栅格化草图失败');
                };
                img.src = url;
            } catch (err) {
                console.error('[CanvasSketch] Add to chat error:', err);
                this.showToast('处理手绘草图时出错');
            }
        },

        // ===== Rhino 3D Viewport Direct-Push Bridge =====
        startRhinoReceiver() {
            // 1. Listen for cross-window / iframe messages
            window.addEventListener('message', (event) => {
                if (event.data?.type === 'rhino_capture' && event.data.data) {
                    this.handleRhinoCapture(event.data.data);
                }
            });

            // 2. Real-time push via WebSocket (zero polling overhead when idle)
            this.connectRhinoWebSocket();
        },

        connectRhinoWebSocket() {
            if (this._rhinoEventBound) return;
            this._rhinoEventBound = true;
            window.addEventListener('canvas:ws-message', (e) => {
                const msg = e.detail;
                if (msg?.type === 'rhino_capture' && msg.data) {
                    this.handleRhinoCapture(msg.data);
                }
            });
        },

        handleRhinoCapture(capture) {
            if (!capture || !capture.url) return;
            if (this.lastProcessedRhinoId === capture.id) return;
            this.lastProcessedRhinoId = capture.id;

            if (typeof window.addNode === 'function' && typeof window.uid === 'function') {
                const pos = typeof window.defaultPoint === 'function'
                    ? window.defaultPoint(0, 0)
                    : { x: 0, y: 0 };

                const node = window.addNode({
                    id: window.uid('img'),
                    type: 'image',
                    x: pos.x,
                    y: pos.y,
                    url: capture.url,
                    name: `Rhino: ${capture.view_name || '视角'}`
                });

                if (node && typeof window.selectNode === 'function') {
                    window.selectNode(node.id);
                }

                this.showToast(`Rhino 视口 [${capture.view_name || 'Perspective'}] 已实时推送到画布！`);
            }
        },

        // ===== Persistence =====
        persist() {
            if (!window.canvas) return;
            if (!window.canvas.settings) window.canvas.settings = {};
            window.canvas.settings.sketchElements = this.elements;
            if (typeof window.scheduleSave === 'function') {
                window.scheduleSave();
            }
        },

        loadInitialElements() {
            if (window.canvas?.settings?.sketchElements && Array.isArray(window.canvas.settings.sketchElements)) {
                this.elements = window.canvas.settings.sketchElements;
                this.renderElements();
                if (this.quickAction) {
                    this.quickAction.classList.toggle('visible', this.elements.length > 0);
                }
            }
        },

        // ===== Utility =====
        escapeHtml(str) {
            return String(str || '').replace(/[&<>"']/g, m => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[m]));
        },

        showToast(msg) {
            if (typeof window.showCanvasAgentToast === 'function') {
                window.showCanvasAgentToast(msg);
                return;
            }
            if (typeof window.setStatus === 'function') {
                window.setStatus(msg);
            }
            let toast = document.querySelector('.agent-toast');
            if (!toast) {
                toast = document.createElement('div');
                toast.className = 'agent-toast';
                document.body.appendChild(toast);
            }
            toast.textContent = msg;
            toast.classList.add('visible');
            clearTimeout(this._toastTimer);
            this._toastTimer = setTimeout(() => {
                toast.classList.remove('visible');
            }, 3000);
        }
    };

    window.CanvasSketch = CanvasSketch;

    // Auto-init when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => CanvasSketch.init());
    } else {
        CanvasSketch.init();
    }
})();
