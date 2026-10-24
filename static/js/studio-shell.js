        function generateUUID() {
            if (typeof crypto !== 'undefined' && crypto.randomUUID) {
                try { return crypto.randomUUID(); } catch (e) { }
            }
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        }
        const CID = localStorage.getItem("client_id") || generateUUID();
        localStorage.setItem("client_id", CID);
        const ACTIVE_PAGE_KEY = 'studio_active_page';
        const LOCAL_NAV_COLLAPSED_KEY = 'studio_local_nav_collapsed';
        const SIDEBAR_SETTINGS_COLLAPSED_KEY = 'studio_sidebar_settings_collapsed';
        const SIDEBAR_PINNED_KEY = 'studio_sidebar_pinned';
        const DEFAULT_PAGE_ID = 'canvas';
        const PAGE_IDS = ['zimage','enhance','klein','angle','online','gpt-chat','canvas','asset-manager','api-settings','comfyui-settings','about'];
        const LOCAL_PAGE_IDS = ['zimage','enhance','klein','angle'];
        const PROJECT_URL = 'https://github.com/zhoushimiaov/MeansCanvas';
        let appInfo = { version:'', repo_url:PROJECT_URL, version_url:'https://raw.githubusercontent.com/zhoushimiaov/MeansCanvas/main/VERSION' };
        let updateConnectivityResult = null;
        let projectUpdateRunning = false;
        let projectUpdateAbort = null;  // 当前更新请求的 AbortController，便于用户中途取消
        let updateSource = localStorage.getItem('studio_update_source') || 'github';
        let projectUpdateNotes = null;

        function setSidebarPinned(pinned, options = {}) {
            const sidebar = document.getElementById('studioSidebar');
            const logo = document.getElementById('sidebarLogoToggle');
            if(!sidebar) return;
            pauseScaleInFrames();
            sidebar.classList.toggle('is-pinned', pinned);
            if(!pinned) {
                sidebar.style.width = '';
                sidebar.classList.add('is-collapsing');
                window.setTimeout(() => sidebar.classList.remove('is-collapsing'), 360);
            } else {
                sidebar.classList.remove('is-collapsing');
                const savedW = localStorage.getItem('studio_sidebar_width');
                if (savedW) {
                    const parsed = parseInt(savedW, 10);
                    const maxLimit = Math.floor(window.innerWidth * 0.5);
                    if (!isNaN(parsed) && parsed >= 190 && parsed <= maxLimit) {
                        sidebar.style.setProperty('--sidebar-pinned-width', `${parsed}px`);
                        sidebar.style.width = `${parsed}px`;
                    }
                }
            }
            if(logo) {
                logo.setAttribute('aria-pressed', pinned ? 'true' : 'false');
                logo.title = pinned ? '收起导航栏' : '固定导航栏';
            }
            if(!options.skipRemember) localStorage.setItem(SIDEBAR_PINNED_KEY, pinned ? '1' : '0');
        }

        function toggleSidebarPinned(event) {
            event?.preventDefault?.();
            event?.stopPropagation?.();
            const sidebar = document.getElementById('studioSidebar');
            setSidebarPinned(!sidebar?.classList.contains('is-pinned'));
        }

        function restoreSidebarPinned() {
            setSidebarPinned(localStorage.getItem(SIDEBAR_PINNED_KEY) === '1', { skipRemember:true });
        }

        function setLocalNavCollapsed(collapsed, options = {}) {
            const group = document.getElementById('local-nav-group');
            const toggle = document.getElementById('local-nav-toggle');
            if(group) group.classList.toggle('is-collapsed', collapsed);
            if(toggle) {
                toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                toggle.title = collapsed ? '展开本地功能' : '折叠本地功能';
            }
            if(!options.skipRemember) localStorage.setItem(LOCAL_NAV_COLLAPSED_KEY, collapsed ? '1' : '0');
        }

        function toggleLocalNav() {
            const group = document.getElementById('local-nav-group');
            setLocalNavCollapsed(!group?.classList.contains('is-collapsed'));
        }

        function restoreLocalNav(id) {
            const savedCollapsed = localStorage.getItem(LOCAL_NAV_COLLAPSED_KEY) === '1';
            setLocalNavCollapsed(savedCollapsed && !LOCAL_PAGE_IDS.includes(id), { skipRemember:true });
        }

        function setSidebarSettingsCollapsed(collapsed, options = {}) {
            const group = document.getElementById('settings-fold-group');
            const toggle = document.getElementById('settings-fold-toggle');
            if(group) group.classList.toggle('is-collapsed', collapsed);
            if(toggle) {
                toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                toggle.title = collapsed ? '展开更多设置' : '收起更多设置';
            }
            if(!options.skipRemember) localStorage.setItem(SIDEBAR_SETTINGS_COLLAPSED_KEY, collapsed ? '1' : '0');
        }

        function toggleSidebarSettings() {
            const group = document.getElementById('settings-fold-group');
            setSidebarSettingsCollapsed(!group?.classList.contains('is-collapsed'));
        }

        function restoreSidebarSettings(id) {
            const savedCollapsed = localStorage.getItem(SIDEBAR_SETTINGS_COLLAPSED_KEY) !== '0';
            setSidebarSettingsCollapsed(savedCollapsed && id !== 'comfyui-settings' && id !== 'about', { skipRemember:true });
        }

        function resetStudioRootScroll() {
            try {
                window.scrollTo(0, 0);
                document.documentElement.scrollTop = 0;
                document.body.scrollTop = 0;
            } catch(e) {}
        }

        function switchUI(el, id, options = {}) {
            resetStudioRootScroll();
            if(!PAGE_IDS.includes(id)) id = DEFAULT_PAGE_ID;
            document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active'));
            if(!el) el = document.querySelector(`[onclick*="'${id}'"],[onclick*='"${id}"']`);
            if(el) el.classList.add('active');
            document.querySelectorAll('iframe').forEach(f => f.classList.remove('active'));
            const target = document.getElementById('frame-' + id);
            target.classList.add('active');
            if (!target.src) {
                target.addEventListener('load', () => {
                    syncThemeToFrame(target);
                    syncLanguageToFrame(target);
                    syncScaleToFrame(target);
                }, { once: true });
                target.src = target.dataset.src;
            }
            if(!options.skipRemember) localStorage.setItem(ACTIVE_PAGE_KEY, id);
            // sync theme to newly activated iframe
            syncThemeToFrame(target);
            syncLanguageToFrame(target);
            syncScaleToFrame(target);
            if(LOCAL_PAGE_IDS.includes(id)) {
                setLocalNavCollapsed(false, { skipRemember:true });
            } else {
                setLocalNavCollapsed(localStorage.getItem(LOCAL_NAV_COLLAPSED_KEY) === '1', { skipRemember:true });
            }
            if(id === 'comfyui-settings' || id === 'about') {
                setSidebarSettingsCollapsed(false, { skipRemember:true });
            }
            // 切换到画布时通知刷新工作流列表（防止在 comfyui-settings 修改后画布未及时更新）
            if (id === 'canvas' && target.src) {
                try { target.contentWindow?.postMessage({ type: 'canvas-focus' }, window.location.origin); } catch(e) {}
            }
            resetStudioRootScroll();
        }

        // MAI Playground blocks iframe embedding (X-Frame-Options: SAMEORIGIN).
        // Open it in a standalone browser window instead; reuse the window if already open.
        let maiPlaygroundWindow = null;
        function openMaiPlayground(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (maiPlaygroundWindow && !maiPlaygroundWindow.closed) {
                maiPlaygroundWindow.focus();
                return;
            }
            maiPlaygroundWindow = window.open('https://playground.microsoft.ai/', 'mai_playground', 'width=1280,height=860');
            if (!maiPlaygroundWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5728\u5730\u5740\u680f\u53f3\u4fa7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // Copilot Imagine 同样禁止 iframe 嵌入（CSP frame-ancestors 白名单仅微软自家域），用独立窗口打开 Imagine 页。
        let copilotImagineWindow = null;
        function openCopilotImagine(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (copilotImagineWindow && !copilotImagineWindow.closed) {
                copilotImagineWindow.focus();
                return;
            }
            copilotImagineWindow = window.open('https://copilot.microsoft.com/imagine', 'copilot_imagine', 'width=1280,height=880');
            if (!copilotImagineWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // Arena AI 同样禁止 iframe 内嵌（SAMEORIGIN），用独立窗口打开。
        let arenaAiWindow = null;
        function openArenaAi(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (arenaAiWindow && !arenaAiWindow.closed) { arenaAiWindow.focus(); return; }
            arenaAiWindow = window.open('https://arena.ai', 'arena_ai', 'width=1280,height=880');
            if (!arenaAiWindow) { alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002'); }
        }

        // Reve 生图同样禁止 iframe 嵌入（XFO SAMEORIGIN），用独立窗口打开。
        let reveImageWindow = null;
        function openReveImage(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (reveImageWindow && !reveImageWindow.closed) {
                reveImageWindow.focus();
                return;
            }
            reveImageWindow = window.open('https://www.reve.com/', 'reve_image', 'width=1280,height=880');
            if (!reveImageWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // Google Flow 生图端：独立窗口打开 labs.google Flow。
        let googleFlowWindow = null;
        function openGoogleFlow(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (googleFlowWindow && !googleFlowWindow.closed) {
                googleFlowWindow.focus();
                return;
            }
            googleFlowWindow = window.open('https://labs.google/fx/zh/tools/flow', 'google_flow', 'width=1280,height=880');
            if (!googleFlowWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // Grok Imagine 与千问创作：独立窗口打开（grok.com 封锁机器指纹且均禁止 iframe）。
        let grokImagineWindow = null;
        function openGrokImagine(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (grokImagineWindow && !grokImagineWindow.closed) {
                grokImagineWindow.focus();
                return;
            }
            grokImagineWindow = window.open('https://grok.com/imagine', 'grok_imagine', 'width=1280,height=880');
            if (!grokImagineWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }
        let qianwenCreateWindow = null;
        function openQianwenCreate(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (qianwenCreateWindow && !qianwenCreateWindow.closed) {
                qianwenCreateWindow.focus();
                return;
            }
            qianwenCreateWindow = window.open('https://create.qianwen.com/r/ai-studio-pc/main/gen?click=ai_image&tab=video', 'qianwen_create', 'width=1360,height=900');
            if (!qianwenCreateWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // ChatGPT 网页版
        let chatgptWindow = null;
        function openChatgptWeb(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (chatgptWindow && !chatgptWindow.closed) {
                chatgptWindow.focus();
                return;
            }
            chatgptWindow = window.open('https://chatgpt.com/', 'chatgpt_web', 'width=1360,height=900');
            if (!chatgptWindow) {
                alert('弹窗被浏览器拦截，请在地址栏右侧允许弹窗后重试。');
            }
        }

        // RunningHub 画布
        let rhCanvasWindow = null;
        function openRhCanvas(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (rhCanvasWindow && !rhCanvasWindow.closed) {
                rhCanvasWindow.focus();
                return;
            }
            rhCanvasWindow = window.open('https://rhtv.runninghub.cn/projects?inviteCode=rh-v1331&setDistinctIDCtx=aWQ9ODA0YzhjM2ItNGVhMy00Y2QzLTk3NmItYmU3MjM0Y2E3YmJkJnR5cGU9MTAwMQ%253D%253D.8fe34b4731a0eeecf4afb99aa0754c6c', 'rh_canvas', 'width=1440,height=920');
            if (!rhCanvasWindow) {
                alert('弹窗被浏览器拦截，请在地址栏右侧允许弹窗后重试。');
            }
        }

        // RunningHub 个人中心
        let rhUserWindow = null;
        function openRhUser(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (rhUserWindow && !rhUserWindow.closed) {
                rhUserWindow.focus();
                return;
            }
            rhUserWindow = window.open('https://www.runninghub.cn/user-center', 'rh_user', 'width=1360,height=900');
            if (!rhUserWindow) {
                alert('弹窗被浏览器拦截，请在地址栏右侧允许弹窗后重试。');
            }
        }

        // CloudCB 图像编辑
        let cloudcbWindow = null;
        function openCloudcb(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (cloudcbWindow && !cloudcbWindow.closed) {
                cloudcbWindow.focus();
                return;
            }
            cloudcbWindow = window.open('https://www.cloudcb.me/', 'cloudcb_window', 'width=1360,height=900');
            if (!cloudcbWindow) {
                alert('弹窗被浏览器拦截，请在地址栏右侧允许弹窗后重试。');
            }
        }

        // ASCII Lab：目标站无 XFO/frame-ancestors 限制，可直接 iframe 内嵌。
        let asciiLabPanel = null;
        let asciiLabLoaded = false;
        let asciiLabWindow = null;
        function openAsciiLabWindow() {
            if (asciiLabWindow && !asciiLabWindow.closed) {
                asciiLabWindow.focus();
                return;
            }
            asciiLabWindow = window.open('https://ascii-lab.sg.agentos-app.run/', 'ascii_lab', 'width=1360,height=900,noopener,noreferrer');
            if (asciiLabWindow) asciiLabWindow.opener = null;
            if (!asciiLabWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }
        function toggleAsciiLab(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (!asciiLabPanel) {
                asciiLabPanel = document.createElement('div');
                asciiLabPanel.id = 'ascii-lab-panel';
                asciiLabPanel.style.cssText = 'position:fixed;top:60px;right:16px;width:620px;height:calc(100vh - 84px);z-index:99999;display:none;flex-direction:column;background:#0d0f12;border:1px solid rgba(255,255,255,.12);border-radius:14px;overflow:hidden;box-shadow:0 16px 48px rgba(0,0,0,.5);';
                asciiLabPanel.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.08);color:#cfd3d8;font-size:13px;background:rgba(255,255,255,0.02);">'
                    + '<b style="font-size:13px;color:#fff">ASCII Lab</b><span style="color:#8fa0b3;flex:1;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">ascii-lab.sg.agentos-app.run</span>'
                    + '<button title="在新窗口打开" onclick="openAsciiLabWindow()" style="display:inline-flex;align-items:center;gap:4px;background:rgba(90,140,220,0.15);border:1px solid rgba(90,140,220,0.3);color:#7fb0e8;cursor:pointer;font-size:11px;padding:3px 8px;border-radius:6px;font-weight:600"><i data-lucide="external-link" class="w-3 h-3"></i><span>独立窗口</span></button>'
                    + '<button title="重新加载" onclick="reloadAsciiLab()" style="background:none;border:none;color:#9aa5b1;cursor:pointer;padding:2px 6px;border-radius:4px;display:inline-flex;align-items:center"><i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i></button>'
                    + '<button title="关闭" onclick="toggleAsciiLab()" style="background:none;border:none;color:#9aa5b1;cursor:pointer;padding:2px 6px;border-radius:4px;display:inline-flex;align-items:center"><i data-lucide="x" class="w-3.5 h-3.5"></i></button></div>'
                    + '<iframe id="ascii-lab-frame" src="about:blank" style="flex:1;width:100%;border:none;background:#0d0f12" sandbox="allow-scripts allow-same-origin allow-forms" allow="accelerometer; autoplay; clipboard-read; clipboard-write; encrypted-media; gyroscope; picture-in-picture" referrerpolicy="no-referrer"></iframe>'
                    + '<div style="padding:6px 14px;background:rgba(0,0,0,0.5);border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#8fa0b3;display:flex;justify-content:space-between;align-items:center;"><span>若因浏览器安全策略内嵌黑屏，请点击右上角「独立窗口」</span><a href="https://ascii-lab.sg.agentos-app.run/" target="_blank" rel="noopener noreferrer" style="color:#7fb0e8;text-decoration:none;font-weight:600;display:inline-flex;align-items:center;gap:3px"><span>直接访问</span><i data-lucide="arrow-right" class="w-3 h-3"></i></a></div>';
                document.body.appendChild(asciiLabPanel);
                if (window.lucide) lucide.createIcons();
            }
            const isOpen = asciiLabPanel.style.display === 'flex';
            asciiLabPanel.style.display = isOpen ? 'none' : 'flex';
            if (!isOpen && !asciiLabLoaded) { reloadAsciiLab(); }
        }
        function reloadAsciiLab() {
            const frame = document.getElementById('ascii-lab-frame');
            if (frame) { frame.src = 'https://ascii-lab.sg.agentos-app.run/'; asciiLabLoaded = true; }
        }

        // Ladybug FX（图片/视频特效工作室）：CSP frame-ancestors 限同源，用独立窗口。
        let ladybugFxWindow = null;
        function openLadybugFx(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (ladybugFxWindow && !ladybugFxWindow.closed) {
                ladybugFxWindow.focus();
                return;
            }
            ladybugFxWindow = window.open('https://app.theladybug.app/', 'ladybug_fx', 'width=1360,height=900,noopener,noreferrer');
            if (ladybugFxWindow) ladybugFxWindow.opener = null;
            if (!ladybugFxWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // Boardmix 博思白板：独立窗口打开，复用窗口保持登录态（登录 cookie 留在浏览器，重开不丢）。
        let boardmixWindow = null;
        function openBoardmix(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (boardmixWindow && !boardmixWindow.closed) {
                boardmixWindow.focus();
                return;
            }
            boardmixWindow = window.open('https://boardmix.cn', 'boardmix', 'width=1360,height=900,noopener,noreferrer');
            if (boardmixWindow) boardmixWindow.opener = null;
            if (!boardmixWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        const EXT_TAB_DEFS = [
            ["mai", "MAI 体验站"],
            ["copilot", "Copilot 生图"],
            ["arena", "Arena AI"],
            ["reve", "Reve 生图"],
            ["gflow", "Google Flow"],
            ["grok", "Grok Imagine"],
            ["qianwen", "千问创作"],
            ["chatgpt", "ChatGPT 对话"],
            ["rh-canvas", "RunningHub 画布"],
            ["rh-user", "RunningHub 个人中心"],
            ["cloudcb", "CloudCB 图像编辑"],
            ["ascii", "ASCII Lab"],
            ["ladybug", "Ladybug FX"],
            ["boardmix", "Boardmix 白板"],
            ["canva", "Canva"],
            ["longcat", "LongCat"],
            ["dola", "Dola"],
            ["agnes-wb", "Agnes 工作台"],
            ["lovart", "Lovart"],
            ["topaz", "Topaz Studio"],
            ["tooootem", "Tooootem"],
            ["feralui", "FeralUI 渐变"],
            ["valessa", "Valessa"],
            ["google-pics", "Google Pics"],
            ["mindvideo", "MindVideo"],
            ["gen-design", "Generative Design"],
            ["shadergpt", "ShaderGPT"],
            ["sensenova", "商汤日日新"],
            ["fal-ai", "fal.ai"],
            ["aihubmix", "AIHubMix"],
            ["omniakey", "OmniaKey"],
            ["eachlabs", "EachLabs"],
            ["apikey-fun", "ApiKey.fun"],
            ["merge-gateway", "Merge Gateway"],
            ["animos", "Animos 动效设计"],
            ["brand-gen", "Brand Generator"],
            ["adam", "Adam"],
            ["cutia", "Cutia 在线剪辑"],
            ["opencut", "OpenCut 视频编辑"],
            ["motion-dev", "Motion 动效库"],
            ["minimax-h3", "MiniMax H3-Max"],
            ["openprocessing", "OpenProcessing 创意编程"],
            ["gen-gestaltung", "Generative Gestaltung"],
            ["recent-design", "Recent Design 灵感库"],
            ["codrops-gsap", "Codrops GSAP 动效库"],
            ["artificial-lab", "Image Lab 画质评测"],
            ["brik-space", "Brik Space 画廊"],
            ["asc11", "ASC11 字符艺术"],
            ["design-arena", "Design Arena 竞技场"],
            ["snitscanner", "Snit Scanner 扫描仪"],
            ["spinespine", "Spine 曲线工具"],
            ["intr-pattern", "INTR 纹理生成器"],
            ["tooooools", "Tooooools 工具库"],
            ["effect-app", "Effect 动效探索"],
            ["gianluca-sketches", "Gianluca 创意草图"],
            ["digitiles", "Digitiles 瓷砖排布"],
            ["pixelsynth", "PixelSynth 图像发声"],
            ["fontbox", "FontBox 字体推敲"],
            ["pixel-perfect", "Pixel Perfect 空间"],
            ["divisare", "Divisare 建筑宝典"],
            ["kontextur", "Kontextur 建筑名录"],
            ["gradient-lab", "Gradient Lab 渐变工坊"],
            ["bg-freebies", "Backgrounds 免费背景素材"],
            ["ascii-magic", "ASCII Magic 字符画转换"],
            ["dotforge", "DotForge 点阵工坊"],
            ["duck-ai", "Duck.ai 隐私 AI 对话"],
            ["flux-tools", "FLUX 官方工具箱"],
            ["flux-precise", "FLUX 精准编辑"],
            ["brik-editor", "Brik 工具编辑器"],
            ["brik-mousegrid", "Brik 鼠标网格交互"],
            ["aholo3d", "Aholo 空间智能平台"],
            ["artcraft", "ArtCraft 视觉工作台"]
        ];
        const EXT_TABS_KEY = "dx_ext_tabs_enabled";
        const EXT_FOLDER_COLLAPSED_KEY = "dx_ext_folder_collapsed";

        function escapeHtml(str) {
            if (!str) return '';
            return String(str).replace(/[&<>"']/g, m => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[m]));
        }

        let extCurrentCategory = 'all';
        let extCurrentSearchQuery = '';

        function updateExtPillsScrollMask() {
            const wrap = document.getElementById('ext-cat-scroll-wrap');
            const pills = document.getElementById('ext-cat-pills');
            if (!wrap || !pills) return;
            const canLeft = pills.scrollLeft > 2;
            const atEnd = pills.scrollLeft + pills.clientWidth >= pills.scrollWidth - 3;
            wrap.classList.toggle('can-scroll-left', canLeft);
            wrap.classList.toggle('at-scroll-end', atEnd);
        }

        function renderExtCategoryPills() {
            const pillsContainer = document.getElementById('ext-cat-pills');
            if (!pillsContainer) return;
            const layout = getExtToolsLayout();
            const cats = ['all', ...layout.map(g => g.category)];
            if (!cats.includes(extCurrentCategory)) {
                extCurrentCategory = 'all';
            }
            pillsContainer.innerHTML = '';
            cats.forEach(cat => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'ext-cat-pill' + (cat === extCurrentCategory ? ' active' : '');
                btn.setAttribute('data-cat', cat);
                btn.textContent = (cat === 'all' ? '全部' : cat);
                btn.onclick = () => setExtCategory(cat, btn);
                pillsContainer.appendChild(btn);
            });
            if (!pillsContainer.__wheelBound) {
                pillsContainer.addEventListener('wheel', e => {
                    if (e.deltaY !== 0) {
                        e.preventDefault();
                        pillsContainer.scrollLeft += e.deltaY;
                        updateExtPillsScrollMask();
                    }
                }, { passive: false });
                pillsContainer.addEventListener('scroll', updateExtPillsScrollMask, { passive: true });
                pillsContainer.__wheelBound = true;
            }
            setTimeout(updateExtPillsScrollMask, 50);
        }

        function setExtCategory(cat, btnEl) {
            extCurrentCategory = cat || 'all';
            const pillsContainer = document.getElementById('ext-cat-pills');
            const pills = document.querySelectorAll('.ext-cat-pill');
            pills.forEach(p => {
                const isTarget = btnEl ? p === btnEl : p.getAttribute('data-cat') === extCurrentCategory;
                p.classList.toggle('active', isTarget);
                if (isTarget && pillsContainer) {
                    const pLeft = p.offsetLeft;
                    const pWidth = p.offsetWidth;
                    const cWidth = pillsContainer.clientWidth;
                    try {
                        pillsContainer.scrollTo({ left: pLeft - (cWidth - pWidth) / 2, behavior: 'smooth' });
                    } catch(_) {
                        pillsContainer.scrollLeft = pLeft - (cWidth - pWidth) / 2;
                    }
                }
            });
            updateExtPillsScrollMask();
            applyExtFolderFilters();
        }

        function handleExtSearch(val) {
            extCurrentSearchQuery = (val || '').trim().toLowerCase();
            const clearBtn = document.getElementById('ext-search-clear');
            if (clearBtn) {
                clearBtn.style.display = extCurrentSearchQuery ? 'inline-flex' : 'none';
            }
            applyExtFolderFilters();
        }

        function clearExtSearch() {
            const input = document.getElementById('ext-search-input');
            if (input) input.value = '';
            handleExtSearch('');
            if (input) input.focus();
        }

        function getExtToolsLayout() {
            try {
                const raw = localStorage.getItem('dx_ext_tools_custom_layout');
                if (raw) {
                    const parsed = JSON.parse(raw);
                    if (Array.isArray(parsed) && parsed.length > 0) return parsed;
                }
            } catch(e) {}
            if (window.EXT_DEFAULT_GROUPS && Array.isArray(window.EXT_DEFAULT_GROUPS)) {
                return JSON.parse(JSON.stringify(window.EXT_DEFAULT_GROUPS));
            }
            return [
                { category: "AI 生图与设计", tools: ["copilot", "reve", "grok", "agnes-wb", "qianwen", "topaz", "cloudcb", "canva", "brand-gen", "feralui", "gradient-lab", "flux-tools", "flux-precise", "artcraft"] },
                { category: "视频与动效", tools: ["mindvideo", "minimax-h3", "cutia", "opencut", "codrops-gsap", "effect-app", "animos", "motion-dev"] },
                { category: "建筑与空间灵感", tools: ["divisare", "kontextur", "recent-design", "brik-space", "brik-editor", "aholo3d", "intr-pattern", "tooooools", "digitiles", "pixel-perfect", "adam", "google-pics", "lovart", "bg-freebies"] },
                { category: "创意编程与实验", tools: ["gflow", "asc11", "ascii", "tooootem", "ladybug", "shadergpt", "valessa", "gen-design", "openprocessing", "gen-gestaltung", "snitscanner", "spinespine", "gianluca-sketches", "pixelsynth", "ascii-magic", "dotforge", "brik-mousegrid"] },
                { category: "大模型与评测", tools: ["chatgpt", "longcat", "dola", "mai", "sensenova", "arena", "artificial-lab", "design-arena", "boardmix", "fontbox", "duck-ai"] },
                { category: "工作流与 API", tools: ["rh-canvas", "rh-user", "fal-ai", "aihubmix", "omniakey", "apikey-fun", "eachlabs", "merge-gateway"] }
            ];
        }

        function matchExtCategory(tabId, cat) {
            if (!cat || cat === 'all') return true;
            const layout = getExtToolsLayout();
            const group = layout.find(g => (g.tools || []).includes(tabId));
            if (group) {
                return group.category === cat;
            }
            const meta = (window.EXT_TOOL_META && window.EXT_TOOL_META[tabId]) || null;
            return (meta && meta.category === cat);
        }

        function matchExtSearch(tabId, itemEl, q) {
            if (!q) return true;
            const meta = (window.EXT_TOOL_META && window.EXT_TOOL_META[tabId]) || null;
            const name = (meta && meta.name ? meta.name.toLowerCase() : '');
            const nameZh = (meta && meta.nameZh ? meta.nameZh.toLowerCase() : '');
            const domain = (meta && meta.domain ? meta.domain.toLowerCase() : '');
            const desc = (meta && meta.desc ? meta.desc.toLowerCase() : '');
            const cat = (meta && meta.category ? meta.category.toLowerCase() : '');
            const text = (itemEl ? itemEl.textContent.toLowerCase() : '');
            return name.includes(q) || nameZh.includes(q) || domain.includes(q) || desc.includes(q) || cat.includes(q) || text.includes(q);
        }

        function applyExtFolderFilters() {
            const enabledState = getExtTabState();
            const items = document.querySelectorAll('#ext-folder-body .ext-tab-item');
            let totalEnabled = 0;
            let matchedCount = 0;

            items.forEach(item => {
                const tabId = item.getAttribute('data-ext-tab');
                if (!tabId) return;
                const isEnabled = enabledState[tabId] !== false;
                if (!isEnabled) {
                    item.style.display = 'none';
                    return;
                }
                totalEnabled++;
                const catMatch = matchExtCategory(tabId, extCurrentCategory);
                const searchMatch = matchExtSearch(tabId, item, extCurrentSearchQuery);
                if (catMatch && searchMatch) {
                    item.style.display = '';
                    matchedCount++;
                } else {
                    item.style.display = 'none';
                }
            });

            // Update each category group's visibility and badge
            const catGroups = document.querySelectorAll('#ext-folder-body .ext-cat-group');
            catGroups.forEach(group => {
                const visibleInGroup = group.querySelectorAll('.ext-tab-item:not([style*="display: none"])').length;
                const badge = group.querySelector('.ext-cat-badge');
                if (badge) badge.textContent = visibleInGroup;
                if (visibleInGroup === 0) {
                    group.style.display = 'none';
                } else {
                    group.style.display = '';
                    if (extCurrentSearchQuery || (extCurrentCategory !== 'all' && extCurrentCategory === group.getAttribute('data-category'))) {
                        group.classList.remove('is-collapsed');
                    }
                }
            });

            const countTextEl = document.getElementById('ext-filter-count-text');
            if (countTextEl) {
                if (extCurrentSearchQuery || extCurrentCategory !== 'all') {
                    countTextEl.textContent = `显示 ${matchedCount}/${totalEnabled} 款工具`;
                } else {
                    countTextEl.textContent = `显示 ${totalEnabled}/${totalEnabled} 款工具`;
                }
            }

            const emptyEl = document.getElementById('ext-empty-state');
            if (emptyEl) {
                emptyEl.style.display = (matchedCount === 0 && totalEnabled > 0) ? 'block' : 'none';
            }
        }

        function initExtCategories() {
            const folderBody = document.getElementById('ext-folder-body');
            if (!folderBody) return;

            // First gather all .ext-tab-item and move them out directly to folderBody
            // so they are not deleted when previous group wrappers are removed
            const allItemsMap = new Map();
            Array.from(folderBody.querySelectorAll('.ext-tab-item')).forEach(el => {
                const tabId = el.getAttribute('data-ext-tab');
                if (tabId) {
                    allItemsMap.set(tabId, el);
                    folderBody.appendChild(el);
                }
            });

            // Safely remove existing .ext-cat-group wrappers
            const existingGroups = Array.from(folderBody.querySelectorAll('.ext-cat-group'));
            existingGroups.forEach(g => g.remove());

            const layout = getExtToolsLayout();

            let collapsedState = {};
            try {
                collapsedState = JSON.parse(localStorage.getItem('ext_categories_collapsed') || '{}');
            } catch(e) {}

            const placedTabIds = new Set();

            layout.forEach(groupDef => {
                const catName = groupDef.category;
                const toolIds = groupDef.tools || [];
                const catItems = [];

                toolIds.forEach(tid => {
                    const itemEl = allItemsMap.get(tid);
                    if (itemEl) {
                        catItems.push(itemEl);
                        placedTabIds.add(tid);
                    }
                });

                const groupEl = document.createElement('div');
                groupEl.className = 'ext-cat-group';
                groupEl.setAttribute('data-category', catName);
                if (collapsedState[catName]) groupEl.classList.add('is-collapsed');

                const header = document.createElement('div');
                header.className = 'ext-cat-header';
                header.setAttribute('title', `点击折叠/展开 ${catName}`);
                header.innerHTML = `
                    <svg class="ext-cat-arrow" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                    <span class="ext-cat-name">${escapeHtml(catName)}</span>
                    <span class="ext-cat-badge">${catItems.length}</span>
                `;

                header.onclick = (e) => {
                    e.stopPropagation();
                    const isNowCollapsed = groupEl.classList.toggle('is-collapsed');
                    try {
                        collapsedState[catName] = isNowCollapsed;
                        localStorage.setItem('ext_categories_collapsed', JSON.stringify(collapsedState));
                    } catch(err) {}
                };

                const body = document.createElement('div');
                body.className = 'ext-cat-body';
                catItems.forEach(item => body.appendChild(item));

                groupEl.appendChild(header);
                groupEl.appendChild(body);
                folderBody.appendChild(groupEl);
            });

            // Catch-all: Any tool not explicitly in layout is placed under "其它"
            const remainingItems = [];
            allItemsMap.forEach((itemEl, tid) => {
                if (!placedTabIds.has(tid)) {
                    remainingItems.push(itemEl);
                }
            });

            if (remainingItems.length > 0) {
                const otherGroup = document.createElement('div');
                otherGroup.className = 'ext-cat-group';
                otherGroup.setAttribute('data-category', '其它');
                const header = document.createElement('div');
                header.className = 'ext-cat-header';
                header.innerHTML = `
                    <svg class="ext-cat-arrow" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                    <span class="ext-cat-name">其它</span>
                    <span class="ext-cat-badge">${remainingItems.length}</span>
                `;
                header.onclick = (e) => {
                    e.stopPropagation();
                    otherGroup.classList.toggle('is-collapsed');
                };
                const body = document.createElement('div');
                body.className = 'ext-cat-body';
                remainingItems.forEach(item => body.appendChild(item));
                otherGroup.appendChild(header);
                otherGroup.appendChild(body);
                folderBody.appendChild(otherGroup);
            }
        }

        function getExtTabState() {
            try {
                const raw = localStorage.getItem(EXT_TABS_KEY);
                if (raw) return JSON.parse(raw);
            } catch(e) {}
            const defaults = {};
            EXT_TAB_DEFS.forEach(([key]) => { defaults[key] = true; });
            return defaults;
        }

        function setExtTabState(state) {
            localStorage.setItem(EXT_TABS_KEY, JSON.stringify(state));
        }

        function applyExternalTabVisibility() {
            renderExtCategoryPills();
            initExtCategories();
            const state = getExtTabState();
            let visibleCount = 0;
            EXT_TAB_DEFS.forEach(([key]) => {
                const el = document.querySelector('[data-ext-tab="' + key + '"]');
                if (!el) return;
                const show = state[key] !== false;
                if (show) visibleCount++;
            });
            const folder = document.getElementById('ext-folder');
            if (folder) folder.style.display = visibleCount > 0 ? "" : "none";
            const countEl = document.getElementById('ext-folder-count');
            if (countEl) countEl.textContent = visibleCount;
            applyExtFolderFilters();
        }

        window.addEventListener('storage', (e) => {
            if (e.key === 'dx_ext_tools_custom_layout' || e.key === 'dx_ext_tabs_enabled' || e.key === EXT_TABS_KEY) {
                applyExternalTabVisibility();
            }
        });
        window.addEventListener('message', (e) => {
            if (e.data && (e.data.type === 'dx_ext_layout_updated' || e.data.type === 'dx_ext_tabs_updated')) {
                applyExternalTabVisibility();
            }
        });

        function setExtFolderCollapsed(collapsed, options = {}) {
            const group = document.getElementById('ext-folder-body');
            const toggle = document.getElementById('ext-nav-toggle');
            if (group) group.classList.toggle('is-collapsed', collapsed);
            if (toggle) {
                toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                toggle.title = collapsed ? '展开外部工具' : '折叠外部工具';
            }
            if (!options.skipRemember) localStorage.setItem(EXT_FOLDER_COLLAPSED_KEY, collapsed ? '1' : '0');
        }

        function toggleExtFolder() {
            const group = document.getElementById('ext-folder-body');
            setExtFolderCollapsed(!group?.classList.contains('is-collapsed'));
        }

        function restoreExtFolder() {
            const savedCollapsed = localStorage.getItem(EXT_FOLDER_COLLAPSED_KEY) !== '0';
            setExtFolderCollapsed(savedCollapsed, { skipRemember:true });
        }

        function toggleAllExtCategories(collapsed) {
            const folderBody = document.getElementById('ext-folder-body');
            if (!folderBody) return;

            // When expanding, make sure the outer external tools folder is also open
            if (!collapsed && folderBody.classList.contains('is-collapsed')) {
                setExtFolderCollapsed(false);
            }

            const groups = folderBody.querySelectorAll('.ext-cat-group');
            let collapsedState = {};
            try {
                collapsedState = JSON.parse(localStorage.getItem('ext_categories_collapsed') || '{}');
            } catch(e) {}

            groups.forEach(group => {
                const catName = group.getAttribute('data-category');
                group.classList.toggle('is-collapsed', collapsed);
                if (catName) {
                    collapsedState[catName] = collapsed;
                }
            });

            try {
                localStorage.setItem('ext_categories_collapsed', JSON.stringify(collapsedState));
            } catch(e) {}
        }

        let extTooltipShowTimer = null;
        let extTooltipHideTimer = null;
        let extTooltipActiveItem = null;

        function initExtTabTooltips() {
            const folderBody = document.getElementById('ext-folder-body');
            const tooltip = document.getElementById('ext-tab-tooltip');
            if (!folderBody || !tooltip) return;
            if (folderBody._extTooltipsBound) return;
            folderBody._extTooltipsBound = true;

            const titleEl = document.getElementById('ext-tooltip-title');
            const domainEl = document.getElementById('ext-tooltip-domain');
            const descEl = document.getElementById('ext-tooltip-desc');
            const badgeEl = document.getElementById('ext-tooltip-badge');
            const imgEl = document.getElementById('ext-tooltip-img');

            function hideTooltip() {
                clearTimeout(extTooltipShowTimer);
                clearTimeout(extTooltipHideTimer);
                extTooltipActiveItem = null;
                tooltip.classList.remove('is-visible');
                tooltip.setAttribute('aria-hidden', 'true');
            }

            function scheduleHide() {
                clearTimeout(extTooltipShowTimer);
                clearTimeout(extTooltipHideTimer);
                extTooltipHideTimer = setTimeout(() => {
                    hideTooltip();
                }, 80);
            }

            function positionTooltip(targetEl) {
                const rect = targetEl.getBoundingClientRect();
                const tooltipRect = tooltip.getBoundingClientRect();
                let top = rect.top + (rect.height - tooltipRect.height) / 2;
                if (top < 12) top = 12;
                if (top + tooltipRect.height > window.innerHeight - 12) {
                    top = window.innerHeight - 12 - tooltipRect.height;
                }
                let left = rect.right + 12;
                if (left + tooltipRect.width > window.innerWidth - 12) {
                    left = Math.max(12, rect.left - tooltipRect.width - 12);
                }
                tooltip.style.left = Math.round(left) + 'px';
                tooltip.style.top = Math.round(top) + 'px';
            }

            function showTooltip(targetEl) {
                const tabId = targetEl.getAttribute('data-ext-tab');
                if (!tabId) {
                    hideTooltip();
                    return;
                }
                const meta = (window.EXT_TOOL_META && window.EXT_TOOL_META[tabId]) || null;
                if (!meta) {
                    hideTooltip();
                    return;
                }

                // 移除原生 title 避免浏览器默认黑底提示框与高级预览卡片打架重叠
                if (targetEl.hasAttribute('title')) {
                    targetEl.setAttribute('data-orig-title', targetEl.getAttribute('title'));
                    targetEl.removeAttribute('title');
                }

                if (titleEl) {
                    titleEl.textContent = meta.nameZh || meta.name || '';
                }
                if (domainEl) {
                    domainEl.textContent = meta.domain || '';
                }
                if (descEl) {
                    descEl.textContent = meta.desc || '';
                }
                if (badgeEl) {
                    badgeEl.textContent = meta.category || 'TOOL';
                }

                if (imgEl) {
                    imgEl.onerror = function() {
                        imgEl.style.display = 'none';
                    };
                    imgEl.onload = function() {
                        imgEl.style.display = 'block';
                    };
                    imgEl.style.display = 'block';
                    imgEl.src = meta.preview || '';
                    imgEl.alt = meta.name || 'Preview';
                }

                positionTooltip(targetEl);
                tooltip.classList.add('is-visible');
                tooltip.setAttribute('aria-hidden', 'false');
            }

            // 事件委托监听 #ext-folder-body
            folderBody.addEventListener('mouseover', (e) => {
                const item = e.target.closest('.ext-tab-item');
                if (!item || !folderBody.contains(item)) return;
                if (item === extTooltipActiveItem) {
                    clearTimeout(extTooltipHideTimer);
                    return;
                }
                extTooltipActiveItem = item;
                clearTimeout(extTooltipHideTimer);
                clearTimeout(extTooltipShowTimer);
                extTooltipShowTimer = setTimeout(() => {
                    showTooltip(item);
                }, 120);
            });

            folderBody.addEventListener('mouseout', (e) => {
                const item = e.target.closest('.ext-tab-item');
                if (!item) return;
                if (item.hasAttribute('data-orig-title')) {
                    item.setAttribute('title', item.getAttribute('data-orig-title'));
                    item.removeAttribute('data-orig-title');
                }
                const related = e.relatedTarget;
                if (related && item.contains(related)) return;
                clearTimeout(extTooltipShowTimer);
                scheduleHide();
            });

            // 卡片本体交互监听
            tooltip.addEventListener('mouseenter', () => {
                clearTimeout(extTooltipHideTimer);
            });

            tooltip.addEventListener('mouseleave', () => {
                scheduleHide();
            });
        }

        const MODULE_TOGGLES_KEY = 'dx_module_toggles';

        function getModuleState() {
            try {
                const raw = localStorage.getItem(MODULE_TOGGLES_KEY);
                if (raw) return JSON.parse(raw);
            } catch(e) {}
            return {
                local_suite: true,
                zimage: true,
                enhance: true,
                klein: true,
                angle: true,
                online: true,
                gpt_chat: true,
                asset_manager: true,
                task_center: true
            };
        }

        function setModuleState(state) {
            localStorage.setItem(MODULE_TOGGLES_KEY, JSON.stringify(state));
        }

        function applyModuleVisibility() {
            const state = getModuleState();

            // 1. 本地功能独立开关条控制（文生图、细节增强、图片编辑、角度控制）
            const suiteMaster = state.local_suite !== false;
            const showZimage = suiteMaster && state.zimage !== false;
            const showEnhance = suiteMaster && state.enhance !== false;
            const showKlein = suiteMaster && state.klein !== false;
            const showAngle = suiteMaster && state.angle !== false;

            const zimageItem = document.getElementById('nav-item-zimage');
            const enhanceItem = document.getElementById('nav-item-enhance');
            const kleinItem = document.getElementById('nav-item-klein');
            const angleItem = document.getElementById('nav-item-angle');

            if (zimageItem) zimageItem.style.display = showZimage ? '' : 'none';
            if (enhanceItem) enhanceItem.style.display = showEnhance ? '' : 'none';
            if (kleinItem) kleinItem.style.display = showKlein ? '' : 'none';
            if (angleItem) angleItem.style.display = showAngle ? '' : 'none';

            const anyLocalVisible = showZimage || showEnhance || showKlein || showAngle;
            const localToggle = document.getElementById('local-nav-toggle');
            const localGroup = document.getElementById('local-nav-group');
            const localDivider = document.getElementById('local-nav-divider');
            if (localToggle) localToggle.style.display = anyLocalVisible ? '' : 'none';
            if (localGroup) localGroup.style.display = anyLocalVisible ? '' : 'none';
            if (localDivider) localDivider.style.display = anyLocalVisible ? '' : 'none';

            // 2. 独立在线生图
            const showOnline = state.online !== false;
            const onlineItem = document.getElementById('nav-item-online');
            if (onlineItem) onlineItem.style.display = showOnline ? '' : 'none';

            // 3. GPT 对话
            const showGpt = state.gpt_chat !== false;
            const gptItem = document.getElementById('nav-item-gpt-chat');
            if (gptItem) gptItem.style.display = showGpt ? '' : 'none';

            // 4. 素材库
            const showAsset = state.asset_manager !== false;
            const assetItem = document.getElementById('nav-item-asset-manager');
            if (assetItem) assetItem.style.display = showAsset ? '' : 'none';

            // 5. 任务中心
            const showTask = state.task_center !== false;
            const taskItem = document.getElementById('nav-item-task-center');
            if (taskItem) taskItem.style.display = showTask ? '' : 'none';

            // 6. 安全回退机制：如果当前页面被禁用，平滑切回画布
            const activePage = localStorage.getItem(ACTIVE_PAGE_KEY) || 'canvas';
            let activeDisabled = false;
            if (activePage === 'zimage' && !showZimage) activeDisabled = true;
            if (activePage === 'enhance' && !showEnhance) activeDisabled = true;
            if (activePage === 'klein' && !showKlein) activeDisabled = true;
            if (activePage === 'angle' && !showAngle) activeDisabled = true;
            if (activePage === 'online' && !showOnline) activeDisabled = true;
            if (activePage === 'gpt-chat' && !showGpt) activeDisabled = true;
            if (activePage === 'asset-manager' && !showAsset) activeDisabled = true;

            if (activeDisabled) {
                switchUI(null, 'canvas');
            }
        }
        try { applyModuleVisibility(); } catch(e) {}

        document.addEventListener("DOMContentLoaded", () => {
            applyExternalTabVisibility();
            applyModuleVisibility();
            restoreExtFolder();
            initExtTabTooltips();
        });
        if (document.readyState === 'complete' || document.readyState === 'interactive') {
            initExtTabTooltips();
        }
        // Canva：独立窗口打开用户的设计编辑器，登录态由 cookie 保持。
        let canvaWindow = null;
        function openCanva(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (canvaWindow && !canvaWindow.closed) {
                canvaWindow.focus();
                return;
            }
            canvaWindow = window.open('https://www.canva.com/design/DAHPcqoVOgc/crjPXkkHP_wLvIb-u3PL2Q/edit?ui=e30', 'canva', 'width=1360,height=900');
            if (!canvaWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // LongCat 与 Dola：独立窗口，复用窗口保持登录与会话状态。
        let longcatWindow = null;
        function openLongcatChat(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (longcatWindow && !longcatWindow.closed) {
                longcatWindow.focus();
                return;
            }
            longcatWindow = window.open('https://longcat.chat/c/ed58f113-3574-48c4-a580-4ab4f3185477', 'longcat', 'width=1280,height=880');
            if (!longcatWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }
        let dolaWindow = null;
        function openDolaChat(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (dolaWindow && !dolaWindow.closed) {
                dolaWindow.focus();
                return;
            }
            dolaWindow = window.open('https://www.dola.com/chat/', 'dola', 'width=1280,height=880');
            if (!dolaWindow) {
                alert('\u5f39\u7a97\u88ab\u6d4f\u89c8\u5668\u62e6\u622a\uff0c\u8bf7\u5141\u8bb8\u5f39\u7a97\u540e\u91cd\u8bd5\u3002');
            }
        }

        // Agnes 工作台：netlify 设置 X-Frame-Options: DENY，用独立窗口。
        let agnesWorkbenchWindow = null;
        function openAgnesWorkbench(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (agnesWorkbenchWindow && !agnesWorkbenchWindow.closed) {
                agnesWorkbenchWindow.focus();
                return;
            }
            agnesWorkbenchWindow = window.open('https://agnes-image-gen.netlify.app/', 'agnes_workbench', 'width=1280,height=880');
            if (!agnesWorkbenchWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        // Lovart 与 Topaz Studio：独立窗口
        let lovartWindow = null;
        function openLovart(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (lovartWindow && !lovartWindow.closed) {
                lovartWindow.focus();
                return;
            }
            lovartWindow = window.open('https://www.lovart.ai/home', 'lovart', 'width=1360,height=900');
            if (!lovartWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let topazStudioWindow = null;
        function openTopazStudio(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (topazStudioWindow && !topazStudioWindow.closed) {
                topazStudioWindow.focus();
                return;
            }
            topazStudioWindow = window.open('https://www.topazlabs.com/studio', 'topaz_studio', 'width=1360,height=900');
            if (!topazStudioWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let tooootemWindow = null;
        function openTooootem(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (tooootemWindow && !tooootemWindow.closed) {
                tooootemWindow.focus();
                return;
            }
            tooootemWindow = window.open('https://tooootem.vercel.app/', 'tooootem', 'width=1360,height=900');
            if (!tooootemWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let feralUiWindow = null;
        function openFeralUi(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (feralUiWindow && !feralUiWindow.closed) {
                feralUiWindow.focus();
                return;
            }
            feralUiWindow = window.open('https://feralui.dev/gradients', 'feralui', 'width=1360,height=900');
            if (!feralUiWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let valessaWindow = null;
        function openValessa(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (valessaWindow && !valessaWindow.closed) {
                valessaWindow.focus();
                return;
            }
            valessaWindow = window.open('https://valessa.riotters.com/', 'valessa', 'width=1360,height=900');
            if (!valessaWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let googlePicsWindow = null;
        function openGooglePics(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (googlePicsWindow && !googlePicsWindow.closed) {
                googlePicsWindow.focus();
                return;
            }
            googlePicsWindow = window.open('https://docs.google.com/images/d/1cm3eiOdmL1Z-0ZDrzgWu4MjvxeWEAT05NRWT_dy7keI/edit?pli=1', 'google_pics', 'width=1360,height=900');
            if (!googlePicsWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let mindVideoWindow = null;
        function openMindVideo(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (mindVideoWindow && !mindVideoWindow.closed) {
                mindVideoWindow.focus();
                return;
            }
            mindVideoWindow = window.open('https://www.mindvideo.ai/zh/creative-studio/', 'mindvideo', 'width=1360,height=900');
            if (!mindVideoWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let genDesignWindow = null;
        function openGenDesign(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (genDesignWindow && !genDesignWindow.closed) {
                genDesignWindow.focus();
                return;
            }
            genDesignWindow = window.open('http://www.generative-gestaltung.de/2/', 'gen_design', 'width=1360,height=900');
            if (!genDesignWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let shaderGptWindow = null;
        function openShaderGpt(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (shaderGptWindow && !shaderGptWindow.closed) {
                shaderGptWindow.focus();
                return;
            }
            shaderGptWindow = window.open('https://shadergpt.14islands.com/1a1d14d3-9453-449e-be9d-d8477b22d825', 'shadergpt', 'width=1360,height=900');
            if (!shaderGptWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let senseNovaWindow = null;
        function openSenseNova(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (senseNovaWindow && !senseNovaWindow.closed) {
                senseNovaWindow.focus();
                return;
            }
            senseNovaWindow = window.open('https://unify.light-ai.top/home?model=u15-lite', 'sensenova', 'width=1360,height=900');
            if (!senseNovaWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let falAiWindow = null;
        function openFalAi(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (falAiWindow && !falAiWindow.closed) {
                falAiWindow.focus();
                return;
            }
            falAiWindow = window.open('https://fal.ai/dashboard', 'fal_ai', 'width=1360,height=900');
            if (!falAiWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let aihubmixWindow = null;
        function openAihubmix(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (aihubmixWindow && !aihubmixWindow.closed) {
                aihubmixWindow.focus();
                return;
            }
            aihubmixWindow = window.open('https://aihubmix.com/', 'aihubmix', 'width=1360,height=900');
            if (!aihubmixWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let omniakeyWindow = null;
        function openOmniakey(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (omniakeyWindow && !omniakeyWindow.closed) {
                omniakeyWindow.focus();
                return;
            }
            omniakeyWindow = window.open('https://omniakey.com/', 'omniakey', 'width=1360,height=900');
            if (!omniakeyWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let eachlabsWindow = null;
        function openEachlabs(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (eachlabsWindow && !eachlabsWindow.closed) {
                eachlabsWindow.focus();
                return;
            }
            eachlabsWindow = window.open('https://www.eachlabs.ai/', 'eachlabs', 'width=1360,height=900');
            if (!eachlabsWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let apikeyFunWindow = null;
        function openApikeyFun(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (apikeyFunWindow && !apikeyFunWindow.closed) {
                apikeyFunWindow.focus();
                return;
            }
            apikeyFunWindow = window.open('https://apikey.fun/', 'apikey_fun', 'width=1360,height=900');
            if (!apikeyFunWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let mergeGatewayWindow = null;
        function openMergeGateway(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (mergeGatewayWindow && !mergeGatewayWindow.closed) {
                mergeGatewayWindow.focus();
                return;
            }
            mergeGatewayWindow = window.open('https://gateway.merge.dev/', 'merge_gateway', 'width=1360,height=900');
            if (!mergeGatewayWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let animosWindow = null;
        function openAnimos(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (animosWindow && !animosWindow.closed) {
                animosWindow.focus();
                return;
            }
            animosWindow = window.open('https://animos.app/editor', 'animos', 'width=1360,height=900');
            if (!animosWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let brandGenWindow = null;
        function openBrandGen(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (brandGenWindow && !brandGenWindow.closed) {
                brandGenWindow.focus();
                return;
            }
            brandGenWindow = window.open('https://brand-generator.stoyanov.works/', 'brand_gen', 'width=1360,height=900');
            if (!brandGenWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let adamWindow = null;
        function openAdam(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (adamWindow && !adamWindow.closed) {
                adamWindow.focus();
                return;
            }
            adamWindow = window.open('https://adam.new/', 'adam', 'width=1360,height=900');
            if (!adamWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let cutiaWindow = null;
        function openCutia(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (cutiaWindow && !cutiaWindow.closed) {
                cutiaWindow.focus();
                return;
            }
            cutiaWindow = window.open('https://cutia.msgbyte.com/zh', 'cutia', 'width=1360,height=900');
            if (!cutiaWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let openCutWindow = null;
        function openOpenCut(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (openCutWindow && !openCutWindow.closed) {
                openCutWindow.focus();
                return;
            }
            openCutWindow = window.open('https://opencut.app/', 'opencut', 'width=1360,height=900');
            if (!openCutWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let motionDevWindow = null;
        function openMotionDev(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (motionDevWindow && !motionDevWindow.closed) {
                motionDevWindow.focus();
                return;
            }
            motionDevWindow = window.open('https://motion.dev/', 'motion_dev', 'width=1360,height=900');
            if (!motionDevWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let minimaxH3Window = null;
        function openMinimaxH3(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (minimaxH3Window && !minimaxH3Window.closed) {
                minimaxH3Window.focus();
                return;
            }
            minimaxH3Window = window.open('https://fal.ai/models/minimax/h3-max/image-to-video', 'minimax_h3', 'width=1360,height=900');
            if (!minimaxH3Window) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let openProcessingWindow = null;
        function openOpenProcessing(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (openProcessingWindow && !openProcessingWindow.closed) {
                openProcessingWindow.focus();
                return;
            }
            openProcessingWindow = window.open('https://openprocessing.org/', 'openprocessing', 'width=1360,height=900');
            if (!openProcessingWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let genGestaltungWindow = null;
        function openGenGestaltung(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (genGestaltungWindow && !genGestaltungWindow.closed) {
                genGestaltungWindow.focus();
                return;
            }
            genGestaltungWindow = window.open('http://www.generative-gestaltung.de/', 'gen_gestaltung', 'width=1360,height=900');
            if (!genGestaltungWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let recentDesignWindow = null;
        function openRecentDesign(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (recentDesignWindow && !recentDesignWindow.closed) {
                recentDesignWindow.focus();
                return;
            }
            recentDesignWindow = window.open('https://recent.design', 'recent_design', 'width=1360,height=900');
            if (!recentDesignWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let codropsGsapWindow = null;
        function openCodropsGsap(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (codropsGsapWindow && !codropsGsapWindow.closed) {
                codropsGsapWindow.focus();
                return;
            }
            codropsGsapWindow = window.open('https://tympanus.net/codrops/hub/tag/gsap/', 'codrops_gsap', 'width=1360,height=900');
            if (!codropsGsapWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let artificialLabWindow = null;
        function openArtificialLab(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (artificialLabWindow && !artificialLabWindow.closed) {
                artificialLabWindow.focus();
                return;
            }
            artificialLabWindow = window.open('https://artificialanalysis.ai/image/image-lab', 'artificial_lab', 'width=1360,height=900');
            if (!artificialLabWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let brikSpaceWindow = null;
        function openBrikSpace(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (brikSpaceWindow && !brikSpaceWindow.closed) {
                brikSpaceWindow.focus();
                return;
            }
            brikSpaceWindow = window.open('https://brik.space/gallery', 'brik_space', 'width=1360,height=900');
            if (!brikSpaceWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let asc11Window = null;
        function openAsc11(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (asc11Window && !asc11Window.closed) {
                asc11Window.focus();
                return;
            }
            asc11Window = window.open('https://asc11.com/', 'asc11', 'width=1360,height=900');
            if (!asc11Window) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let designArenaWindow = null;
        function openDesignArena(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (designArenaWindow && !designArenaWindow.closed) {
                designArenaWindow.focus();
                return;
            }
            designArenaWindow = window.open('https://www.designarena.ai/', 'design_arena', 'width=1360,height=900');
            if (!designArenaWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let snitScannerWindow = null;
        function openSnitScanner(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (snitScannerWindow && !snitScannerWindow.closed) {
                snitScannerWindow.focus();
                return;
            }
            snitScannerWindow = window.open('https://snitscanner.xyz/', 'snitscanner', 'width=1360,height=900');
            if (!snitScannerWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let spineSpineWindow = null;
        function openSpineSpine(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (spineSpineWindow && !spineSpineWindow.closed) {
                spineSpineWindow.focus();
                return;
            }
            spineSpineWindow = window.open('https://www.spinespinespine.tools/', 'spinespine', 'width=1360,height=900');
            if (!spineSpineWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let intrPatternWindow = null;
        function openIntrPattern(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (intrPatternWindow && !intrPatternWindow.closed) {
                intrPatternWindow.focus();
                return;
            }
            intrPatternWindow = window.open('https://wangxian.work/tools/intr-tools/INTR-PATTERN.html', 'intr_pattern', 'width=1360,height=900');
            if (!intrPatternWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let toooooolsWindow = null;
        function openTooooools(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (toooooolsWindow && !toooooolsWindow.closed) {
                toooooolsWindow.focus();
                return;
            }
            toooooolsWindow = window.open('https://www.tooooools.app/', 'tooooools', 'width=1360,height=900');
            if (!toooooolsWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let effectAppWindow = null;
        function openEffectApp(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (effectAppWindow && !effectAppWindow.closed) {
                effectAppWindow.focus();
                return;
            }
            effectAppWindow = window.open('https://effect.app/explore', 'effect_app', 'width=1360,height=900');
            if (!effectAppWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let gianlucaSketchesWindow = null;
        function openGianlucaSketches(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (gianlucaSketchesWindow && !gianlucaSketchesWindow.closed) {
                gianlucaSketchesWindow.focus();
                return;
            }
            gianlucaSketchesWindow = window.open('https://www.gianluca.club/sketches', 'gianluca_sketches', 'width=1360,height=900');
            if (!gianlucaSketchesWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let digitilesWindow = null;
        function openDigitiles(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (digitilesWindow && !digitilesWindow.closed) {
                digitilesWindow.focus();
                return;
            }
            digitilesWindow = window.open('https://eduardadu.github.io/Digitiles/create.html', 'digitiles', 'width=1360,height=900');
            if (!digitilesWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let pixelSynthWindow = null;
        function openPixelSynth(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (pixelSynthWindow && !pixelSynthWindow.closed) {
                pixelSynthWindow.focus();
                return;
            }
            pixelSynthWindow = window.open('https://pixelsynth.com/', 'pixelsynth', 'width=1360,height=900');
            if (!pixelSynthWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let fontBoxWindow = null;
        function openFontBox(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (fontBoxWindow && !fontBoxWindow.closed) {
                fontBoxWindow.focus();
                return;
            }
            fontBoxWindow = window.open('https://fontbox.barcoloudly.com/', 'fontbox', 'width=1360,height=900');
            if (!fontBoxWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let pixelPerfectWindow = null;
        function openPixelPerfect(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (pixelPerfectWindow && !pixelPerfectWindow.closed) {
                pixelPerfectWindow.focus();
                return;
            }
            pixelPerfectWindow = window.open('https://www.pixel-perfect.space/', 'pixel_perfect', 'width=1360,height=900');
            if (!pixelPerfectWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let divisareWindow = null;
        function openDivisare(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (divisareWindow && !divisareWindow.closed) {
                divisareWindow.focus();
                return;
            }
            divisareWindow = window.open('https://www.divisare.com', 'divisare', 'width=1360,height=900');
            if (!divisareWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let kontexturWindow = null;
        function openKontextur(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (kontexturWindow && !kontexturWindow.closed) {
                kontexturWindow.focus();
                return;
            }
            kontexturWindow = window.open('https://kontextur.info/studiolists', 'kontextur', 'width=1360,height=900');
            if (!kontexturWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let gradientLabWindow = null;
        function openGradientLab(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (gradientLabWindow && !gradientLabWindow.closed) {
                gradientLabWindow.focus();
                return;
            }
            gradientLabWindow = window.open('https://backgrounds.supply/gradient-lab', 'gradient_lab', 'width=1360,height=900');
            if (!gradientLabWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let bgFreebiesWindow = null;
        function openBgFreebies(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (bgFreebiesWindow && !bgFreebiesWindow.closed) {
                bgFreebiesWindow.focus();
                return;
            }
            bgFreebiesWindow = window.open('https://backgrounds.supply/freebies', 'bg_freebies', 'width=1360,height=900');
            if (!bgFreebiesWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let asciiMagicWindow = null;
        function openAsciiMagic(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (asciiMagicWindow && !asciiMagicWindow.closed) {
                asciiMagicWindow.focus();
                return;
            }
            asciiMagicWindow = window.open('https://www.ascii-magic.com/', 'ascii_magic', 'width=1360,height=900');
            if (!asciiMagicWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let dotForgeWindow = null;
        function openDotForge(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (dotForgeWindow && !dotForgeWindow.closed) {
                dotForgeWindow.focus();
                return;
            }
            dotForgeWindow = window.open('https://dotforge.vercel.app/', 'dotforge', 'width=1360,height=900');
            if (!dotForgeWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let duckAiWindow = null;
        function openDuckAi(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (duckAiWindow && !duckAiWindow.closed) {
                duckAiWindow.focus();
                return;
            }
            duckAiWindow = window.open('https://duck.ai/', 'duck_ai', 'width=1360,height=900');
            if (!duckAiWindow) {
                alert('弹窗被浏览器拦截，请允许弹窗后重试。');
            }
        }

        let fluxToolsWindow = null;
        function openFluxTools(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (fluxToolsWindow && !fluxToolsWindow.closed) { fluxToolsWindow.focus(); return; }
            fluxToolsWindow = window.open('https://flux-tools.bfl.ai/', 'flux_tools', 'width=1360,height=900');
            if (!fluxToolsWindow) alert('弹窗被浏览器拦截，请允许弹窗后重试。');
        }

        let fluxPreciseWindow = null;
        function openFluxPrecise(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (fluxPreciseWindow && !fluxPreciseWindow.closed) { fluxPreciseWindow.focus(); return; }
            fluxPreciseWindow = window.open('https://flux-tools.bfl.ai/precise-editing', 'flux_precise', 'width=1360,height=900');
            if (!fluxPreciseWindow) alert('弹窗被浏览器拦截，请允许弹窗后重试。');
        }

        let brikEditorWindow = null;
        function openBrikEditor(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (brikEditorWindow && !brikEditorWindow.closed) { brikEditorWindow.focus(); return; }
            brikEditorWindow = window.open('https://brik.space/tooleditor/6ac799b728cbfe67305e50bf', 'brik_editor', 'width=1360,height=900');
            if (!brikEditorWindow) alert('弹窗被浏览器拦截，请允许弹窗后重试。');
        }

        let brikMousegridWindow = null;
        function openBrikMousegrid(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (brikMousegridWindow && !brikMousegridWindow.closed) { brikMousegridWindow.focus(); return; }
            brikMousegridWindow = window.open('https://brik.space/toolviewer?slug=mousegrid-mo0453fe', 'brik_mousegrid', 'width=1360,height=900');
            if (!brikMousegridWindow) alert('弹窗被浏览器拦截，请允许弹窗后重试。');
        }

        let aholo3dWindow = null;
        function openAholo3d(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (aholo3dWindow && !aholo3dWindow.closed) { aholo3dWindow.focus(); return; }
            aholo3dWindow = window.open('https://www.aholo3d.cn/', 'aholo3d', 'width=1360,height=900');
            if (!aholo3dWindow) alert('弹窗被浏览器拦截，请允许弹窗后重试。');
        }

        let artcraftWindow = null;
        function openArtcraft(el) {
            if (el) { document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active')); el.classList.add('active'); }
            if (artcraftWindow && !artcraftWindow.closed) { artcraftWindow.focus(); return; }
            artcraftWindow = window.open('https://app.getartcraft.com/', 'artcraft', 'width=1360,height=900');
            if (!artcraftWindow) alert('弹窗被浏览器拦截，请允许弹窗后重试。');
        }

        function forwardStudioApiChange(data) {
            if(!data) return;
            if(data.type === 'modules-changed') {
                applyModuleVisibility();
                return;
            }
            if(!['providers-changed','workflows-changed','comfy-instances-changed'].includes(data.type)) return;
            document.querySelectorAll('iframe').forEach(iframe => {
                try {
                    if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage(data, window.location.origin);
                } catch(e) {}
            });
        }

        window.addEventListener('message', event => {
            if (event.origin && event.origin !== location.origin) return;
            forwardStudioApiChange(event.data);
        });

        window.addEventListener('storage', event => {
            if (event.key === MODULE_TOGGLES_KEY) {
                applyModuleVisibility();
            }
            if (event.key === EXT_TABS_KEY) {
                applyExternalTabVisibility();
            }
        });
        window.addEventListener('focus', () => {
            applyExternalTabVisibility();
            applyModuleVisibility();
        });

        try {
            const studioApiChannel = new BroadcastChannel('studio-api');
            studioApiChannel.onmessage = event => forwardStudioApiChange(event.data);
        } catch(e) {}

        function initStudioSidebarResizer() {
            const sidebar = document.getElementById('studioSidebar');
            const resizer = document.getElementById('studioSidebarResizer');
            if (!sidebar || !resizer) return;

            const savedWidth = localStorage.getItem('studio_sidebar_width');
            if (savedWidth) {
                const parsed = parseInt(savedWidth, 10);
                const maxLimit = Math.floor(window.innerWidth * 0.5);
                if (!isNaN(parsed) && parsed >= 190 && parsed <= maxLimit) {
                    sidebar.style.setProperty('--sidebar-pinned-width', `${parsed}px`);
                    if (sidebar.classList.contains('is-pinned')) {
                        sidebar.style.width = `${parsed}px`;
                    }
                }
            }

            let isDragging = false;
            let startX = 0;
            let startWidth = 0;

            resizer.addEventListener('mousedown', (e) => {
                if (!sidebar.classList.contains('is-pinned')) return;
                isDragging = true;
                startX = e.clientX;
                startWidth = sidebar.getBoundingClientRect().width;
                resizer.classList.add('is-dragging');
                document.body.style.userSelect = 'none';
                document.body.style.cursor = 'col-resize';
                document.querySelectorAll('iframe').forEach(f => f.style.pointerEvents = 'none');
                e.preventDefault();
            });

            window.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const delta = e.clientX - startX;
                let newWidth = startWidth + delta;
                const minW = 190;
                const maxW = Math.floor(window.innerWidth * 0.5);
                if (newWidth < minW) newWidth = minW;
                if (newWidth > maxW) newWidth = maxW;
                sidebar.style.setProperty('--sidebar-pinned-width', `${newWidth}px`);
                sidebar.style.width = `${newWidth}px`;
            });

            window.addEventListener('mouseup', () => {
                if (!isDragging) return;
                isDragging = false;
                resizer.classList.remove('is-dragging');
                document.body.style.userSelect = '';
                document.body.style.cursor = '';
                document.querySelectorAll('iframe').forEach(f => f.style.pointerEvents = '');
                const currentWidth = Math.round(sidebar.getBoundingClientRect().width);
                localStorage.setItem('studio_sidebar_width', currentWidth);
            });
        }

        function restoreActivePage() {
            initStudioSidebarResizer();
            restoreSidebarPinned();
            const id = PAGE_IDS.includes(localStorage.getItem(ACTIVE_PAGE_KEY)) ? localStorage.getItem(ACTIVE_PAGE_KEY) : DEFAULT_PAGE_ID;
            restoreLocalNav(id);
            restoreExtFolder();
            restoreSidebarSettings(id);
            const trigger = document.querySelector(`[onclick*="'${id}'"],[onclick*='"${id}"']`);
            switchUI(trigger, id, { skipRemember:true });
            document.documentElement.classList.remove('studio-route-booting');
        }
        document.addEventListener('DOMContentLoaded', restoreActivePage, { once:true });

        async function syncStatus() {
            try {
                const res = await fetch(`/api/queue_status?client_id=${CID}`);
                const data = await res.json();
                const monitor = document.getElementById('nano-monitor');
                const queueVal = document.getElementById('queue-val');
                const logoDot = document.getElementById('logo-dot');
                const total = data.total || 0;
                const pos = data.position || 0;
                if (pos > 0) {
                    monitor?.classList.add('is-busy');
                    if (queueVal) queueVal.innerText = `${pos}/${total}`;
                    if (logoDot) logoDot.style.backgroundColor = '#3b82f6';
                } else {
                    monitor?.classList.remove('is-busy');
                    if (queueVal) queueVal.innerText = total > 0 ? total : '0';
                    if (logoDot) logoDot.style.backgroundColor = 'var(--text)';
                }
            } catch (e) { }
        }

        const host = window.location.host;
        if (host) {
            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            const ws = new WebSocket(`${protocol}://${host}/ws/stats?client_id=${CID}`);
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'stats') {
                    const ov = document.getElementById('online-val');
                    if (ov) ov.innerText = data.online_count;
                } else if (data.type === 'cloud_status') {
                    const iframe = document.querySelector('iframe.active');
                    if (iframe && iframe.contentWindow) {
                        iframe.contentWindow.postMessage(data, window.location.origin);
                    }
                } else if (data.type === 'canvas_updated') {
                    const iframe = document.querySelector('iframe.active');
                    if (iframe && iframe.contentWindow) {
                        iframe.contentWindow.postMessage(data, window.location.origin);
                    }
                } else if (data.type === 'asset_library_updated') {
                    document.querySelectorAll('iframe').forEach(iframe => {
                        if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage(data, window.location.origin);
                    });
                }
            };
            setInterval(syncStatus, 2000);
        }

        // --- 夜间模式 ---

        function syncThemeToFrame(iframe) {
            const theme = (window.StudioTheme || {get: () => 'light'}).get();
            try {
                if (iframe && iframe.contentWindow) {
                    iframe.contentWindow.postMessage({ type: 'studio-theme', theme }, window.location.origin);
                }
            } catch (e) {}
        }

        function syncScaleToFrame(iframe) {
            const mode = (window.StudioScale || {getMode: () => 'auto'}).getMode();
            const cssScale = Number(getComputedStyle(document.documentElement).getPropertyValue('--studio-ui-scale'));
            const scale = Number.isFinite(cssScale) && cssScale > 0 ? cssScale : ((window.StudioScale || {getScale: () => 1}).getScale());
            try {
                if (iframe && iframe.contentWindow) {
                    iframe.contentWindow.postMessage({ type: 'studio-ui-scale', mode, scale }, window.location.origin);
                }
            } catch (e) {}
        }

        function pauseScaleInFrame(frame, duration = 650) {
            try {
                frame?.contentWindow?.postMessage({ type:'studio-ui-scale-pause', duration }, window.location.origin);
            } catch(e) {}
        }

        function pauseScaleInFrames(duration = 650) {
            document.querySelectorAll('iframe').forEach(frame => pauseScaleInFrame(frame, duration));
        }

        function broadcastScaleToFrames() {
            document.querySelectorAll('iframe').forEach(frame => syncScaleToFrame(frame));
        }

        function broadcastTheme(theme) {
            if (window.StudioTheme) {
                window.StudioTheme.set(theme);
            }
            document.querySelectorAll('iframe').forEach(f => syncThemeToFrame(f));
            updateThemeIcon(theme);
        }

        function updateThemeIcon(theme) {
            const moon = document.getElementById('icon-moon');
            const sun = document.getElementById('icon-sun');
            const warm = document.getElementById('icon-warm');
            if (moon) moon.style.display = 'none';
            if (sun) sun.style.display = 'none';
            if (warm) warm.style.display = 'none';

            let currentKey = 'common.lightMode';
            let nextKey = 'common.warmMode';
            if (theme === 'dark') {
                if (moon) moon.style.display = 'block';
                currentKey = 'common.darkMode';
                nextKey = 'common.lightMode';
            } else if (theme === 'warm') {
                if (warm) warm.style.display = 'block';
                currentKey = 'common.warmMode';
                nextKey = 'common.darkMode';
            } else { // light
                if (sun) sun.style.display = 'block';
                currentKey = 'common.lightMode';
                nextKey = 'common.warmMode';
            }
            const label = document.querySelector('#theme-toggle-btn .side-pill-text');
            if (label) {
                label.dataset.i18n = currentKey;
                if (window.StudioI18n) label.textContent = window.StudioI18n.t(currentKey);
            }
            const btn = document.getElementById('theme-toggle-btn');
            if (btn) {
                const curName = window.StudioI18n ? window.StudioI18n.t(currentKey) : (theme === 'dark' ? '黑夜模式' : (theme === 'warm' ? '暖白模式' : '白天模式'));
                const nextName = window.StudioI18n ? window.StudioI18n.t(nextKey) : (theme === 'dark' ? '白天模式' : (theme === 'warm' ? '黑夜模式' : '暖白模式'));
                btn.title = `${curName}（点击切换至${nextName}）`;
            }
        }

        function toggleTheme() {
            const current = window.StudioTheme ? window.StudioTheme.get() : 'light';
            let next = 'warm';
            if (current === 'light') next = 'warm';
            else if (current === 'warm') next = 'dark';
            else next = 'light';
            broadcastTheme(next);
        }

        function toggleLanguage() {
            if(!window.StudioI18n) return;
            window.StudioI18n.toggle();
            document.querySelectorAll('iframe').forEach(frame => syncLanguageToFrame(frame));
            updateProjectUpdateTitle();
            refreshUpdateButtonText();
            refreshProjectUpdateModalText();
        }

        function syncLanguageToFrame(frame) {
            if(!window.StudioI18n) return;
            try {
                frame.contentWindow?.postMessage({ type:'studio-lang', lang:window.StudioI18n.lang() }, window.location.origin);
            } catch(e) {}
        }

        function broadcastLanguage() {
            document.querySelectorAll('iframe').forEach(frame => {
                try {
                    frame.contentWindow?.postMessage({ type:'studio-lang', lang:window.StudioI18n.lang() }, window.location.origin);
                } catch(e) {}
            });
        }

        // listen for theme changes triggered by theme.js
        window.addEventListener('studio-theme-change', (e) => {
            updateThemeIcon(e.detail.theme);
        });

        window.addEventListener('studio-ui-scale-change', () => {
            broadcastScaleToFrames();
        });

        // init icon state on load
        window.addEventListener('DOMContentLoaded', () => {
            const theme = window.StudioTheme ? window.StudioTheme.get() : 'light';
            updateThemeIcon(theme);
            if(window.StudioI18n) window.StudioI18n.apply();
            broadcastLanguage();
            const sidebar = document.getElementById('studioSidebar');
            if(sidebar) {
                sidebar.addEventListener('mouseenter', () => pauseScaleInFrames());
                sidebar.addEventListener('mouseleave', () => pauseScaleInFrames());
            }
            checkForUpdates();
        });

        // sync theme when iframe loads
        document.querySelectorAll('iframe').forEach(f => {
            f.addEventListener('load', () => {
                syncThemeToFrame(f);
                syncLanguageToFrame(f);
                syncScaleToFrame(f);
            });
        });

        function openProjectPage() {
            window.open(appInfo.repo_url || PROJECT_URL, '_blank', 'noopener');
        }

        function versionParts(value) {
            return String(value || '').match(/\d+/g)?.map(Number) || [];
        }

        function compareVersions(a, b) {
            const aa = versionParts(a);
            const bb = versionParts(b);
            const len = Math.max(aa.length, bb.length);
            for(let i = 0; i < len; i++){
                const diff = (aa[i] || 0) - (bb[i] || 0);
                if(diff) return diff;
            }
            return String(a || '').trim() === String(b || '').trim() ? 0 : 1;
        }

        function compactVersion(value) {
            const text = String(value || '').trim();
            const parts = text.match(/\d+/g) || [];
            if(parts.length >= 3) return `${parts[1]}.${parts[2]}`;
            return text.replace(/^v/i, '') || '-';
        }

        function versionLabel(value, mode = 'full') {
            const text = String(value || '').trim();
            if(!text) return 'v-';
            return mode === 'compact' ? `v${compactVersion(text)}` : `v${text.replace(/^v/i, '')}`;
        }

        function setProjectVersionBadge(version) {
            const badge = document.getElementById('project-version-badge');
            if(!badge) return;
            const full = versionLabel(version);
            badge.replaceChildren();
            if(version) {
                const compactSpan = document.createElement('span');
                compactSpan.className = 'project-version-compact';
                compactSpan.textContent = versionLabel(version, 'compact');
                const fullSpan = document.createElement('span');
                fullSpan.className = 'project-version-full';
                fullSpan.textContent = full;
                badge.append(compactSpan, fullSpan);
            } else {
                badge.textContent = 'v-';
            }
            badge.title = window.StudioI18n?.lang?.() === 'en'
                ? `Current version: ${full} · click to check for updates`
                : `当前版本：${full} · 点击检测更新`;
        }

        function refreshUpdateButtonText() {
            const btn = document.getElementById('update-now-btn');
            const text = document.getElementById('update-now-text');
            if(!btn || !text || !btn.classList.contains('show')) return;
            const remoteVersion = document.getElementById('github-entry-btn')?.dataset.remoteVersion || '';
            const isEn = window.StudioI18n?.lang?.() === 'en';
            text.removeAttribute('data-i18n');
            if(remoteVersion) {
                const prefix = isEn ? 'Update to' : '更新到';
                text.replaceChildren();
                const prefixSpan = document.createElement('span');
                prefixSpan.className = 'update-action-prefix';
                prefixSpan.textContent = `${prefix} `;
                const compactSpan = document.createElement('span');
                compactSpan.className = 'update-version-compact';
                compactSpan.textContent = versionLabel(remoteVersion, 'compact');
                const fullSpan = document.createElement('span');
                fullSpan.className = 'update-version-full';
                fullSpan.textContent = versionLabel(remoteVersion);
                text.append(prefixSpan, compactSpan, fullSpan);
                btn.setAttribute('aria-label', `${prefix} ${versionLabel(remoteVersion)}`);
            } else {
                text.textContent = isEn ? 'Update' : '一键更新';
                btn.setAttribute('aria-label', text.textContent);
            }
        }

        function updateProjectUpdateTitle() {
            const gitBtn = document.getElementById('github-entry-btn');
            setProjectVersionBadge(appInfo.version || gitBtn?.dataset.localVersion || '');
            if(!gitBtn?.classList.contains('update-available')) return;
            const remoteVersion = gitBtn.dataset.remoteVersion || '';
            const isEn = window.StudioI18n?.lang?.() === 'en';
            gitBtn.title = isEn
                ? `Current ${versionLabel(gitBtn.dataset.localVersion || appInfo.version)} · latest ${versionLabel(remoteVersion)}`
                : `当前 ${versionLabel(gitBtn.dataset.localVersion || appInfo.version)} · 最新 ${versionLabel(remoteVersion)}`;
            const updateBtn = document.getElementById('update-now-btn');
            if(updateBtn) updateBtn.title = remoteVersion
                ? (isEn ? `Update to ${versionLabel(remoteVersion)}` : `更新到 ${versionLabel(remoteVersion)}`)
                : (isEn ? 'Update main.py and static files from GitHub' : '从 GitHub 更新 main.py 和 static 文件');
            refreshUpdateButtonText();
        }

        function showUpdateNotice(localVersion, remoteVersion) {
            const gitBtn = document.getElementById('github-entry-btn');
            if(!gitBtn) return;
            gitBtn.classList.add('update-available');
            gitBtn.dataset.localVersion = localVersion || '';
            gitBtn.dataset.remoteVersion = remoteVersion || '';
            document.getElementById('update-now-btn')?.classList.add('show');
            updateProjectUpdateTitle();
        }

        function setProjectUpdateNotes(notes) {
            projectUpdateNotes = notes && typeof notes === 'object' ? notes : null;
            renderProjectUpdateNotes();
        }

        function renderProjectUpdateNotes() {
            const box = document.getElementById('project-update-notes');
            if(!box) return;
            const titleEl = document.getElementById('project-update-notes-title');
            const versionEl = document.getElementById('project-update-notes-version');
            const list = document.getElementById('project-update-notes-list');
            const empty = document.getElementById('project-update-notes-empty');
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const notes = projectUpdateNotes || {};
            const items = Array.isArray(notes.items) ? notes.items.filter(Boolean) : [];
            if(titleEl) titleEl.textContent = isEn ? 'What changed' : '本次更新内容';
            if(versionEl) versionEl.textContent = notes.version ? versionLabel(notes.version) : '';
            if(list) {
                list.replaceChildren();
                items.slice(0, 8).forEach(item => {
                    const text = typeof item === 'string' ? item : item.text;
                    if(!text) return;
                    const li = document.createElement('li');
                    li.textContent = String(text);
                    list.append(li);
                });
            }
            const hasItems = !!(list && list.children.length);
            if(empty) {
                empty.hidden = hasItems;
                empty.textContent = isEn ? 'No update notes were found for this version.' : '暂未获取到这个版本的更新说明。';
            }
            box.hidden = !(notes.version || hasItems);
        }

        function describeNetworkError(err, isEn){
            const msg = String(err?.message || err || '');
            const isNetwork = (err instanceof TypeError) || /Failed to fetch|NetworkError|ERR_|timed? ?out|超时|无法连接|GitHub|HTTP 4|HTTP 5/i.test(msg);
            if(isNetwork){
                return isEn
                    ? 'Cannot reach the selected update source. Check your network, proxy, or DNS, then try again.'
                    : '无法连接当前选择的更新源。请检查网络、代理或 DNS 后重试。';
            }
            return msg || (isEn ? 'Update failed' : '更新失败');
        }

        function updateUiText(zh, en) {
            return window.StudioI18n?.lang?.() === 'en' ? en : zh;
        }

        function updateSourceLabel(source = updateSource) {
            return source === 'modelscope' ? 'ModelScope' : 'GitHub';
        }

        function setUpdateSource(source) {
            updateSource = source === 'modelscope' ? 'modelscope' : 'github';
            localStorage.setItem('studio_update_source', updateSource);
            refreshProjectUpdateModalText();
        }

        function sourceConnectivityStats(source, results = []) {
            const sourceItems = (results || []).filter(item => item.source === source);
            const required = sourceItems.filter(item => item.required);
            const okRequired = required.length ? required.every(item => item.ok) : false;
            const okItems = sourceItems.filter(item => item.ok);
            const avg = okItems.length
                ? Math.round(okItems.reduce((sum, item) => sum + Number(item.elapsed_ms || 0), 0) / okItems.length)
                : 999999;
            return {source, ok:okRequired, avg, okItems:okItems.length, total:sourceItems.length};
        }

        function bestUpdateSourceFromConnectivity(data) {
            const results = data?.results || [];
            const github = sourceConnectivityStats('github', results);
            const ms = sourceConnectivityStats('modelscope', results);
            if(github.ok && ms.ok) return ms.avg < github.avg ? 'modelscope' : 'github';
            if(ms.ok) return 'modelscope';
            if(github.ok) return 'github';
            return updateSource;
        }

        function updateTargetLabel(name) {
            const labels = {
                'GitHub 更新列表': ['GitHub 更新列表', 'GitHub update API'],
                'GitHub 版本文件': ['GitHub 版本文件', 'GitHub version file'],
                'GitHub 主页': ['GitHub 主页', 'GitHub home page'],
                'ModelScope 更新列表': ['ModelScope 更新列表', 'ModelScope update list'],
                'ModelScope 版本文件': ['ModelScope 版本文件', 'ModelScope version file'],
                'ModelScope 空间页面': ['ModelScope 空间页面', 'ModelScope space page'],
                'ModelScope 主页': ['ModelScope 主页', 'ModelScope home page'],
                'Google 连通性': ['Google 连通性', 'Google connectivity'],
            };
            const item = labels[name] || [name, name];
            return window.StudioI18n?.lang?.() === 'en' ? item[1] : item[0];
        }

        function updateStatusLabel(item) {
            if(item.pending) return updateUiText('检测中...', 'Testing...');
            if(item.ok) return `${updateUiText('正常', 'OK')} · ${item.elapsed_ms || 0}ms`;
            if(item.timed_out) return updateUiText('失败 · 超时', 'Failed · timeout');
            if(item.status) return `HTTP ${item.status}`;
            return updateUiText('失败', 'Failed');
        }

        function setUpdateSummary(kind, title, text) {
            const box = document.getElementById('project-update-summary');
            const titleEl = document.getElementById('project-update-summary-title');
            const textEl = document.getElementById('project-update-summary-text');
            if(box) {
                box.classList.remove('ok', 'warn', 'fail');
                box.classList.add(kind || 'warn');
            }
            if(titleEl) titleEl.textContent = title;
            if(textEl) textEl.textContent = text;
        }

        function updateConnectivityTargets() {
            const sources = appInfo.sources || {};
            const github = sources.github || {};
            const ms = sources.modelscope || {};
            return [
                { name:'GitHub 更新列表', url:github.tree_url || appInfo.tree_url || 'https://api.github.com/repos/zhoushimiaov/MeansCanvas/git/trees/main?recursive=1', source:'github', required:true },
                { name:'GitHub 版本文件', url:github.version_url || appInfo.version_url || 'https://raw.githubusercontent.com/zhoushimiaov/MeansCanvas/main/VERSION', source:'github', required:true },
                { name:'GitHub 主页', url:'https://github.com/', source:'github' },
                { name:'ModelScope 版本文件', url:ms.version_url || 'https://www.modelscope.cn/api/v1/studio/Daniel8152/Infinite-Canvas/repo?Revision=master&FilePath=VERSION', source:'modelscope', required:true },
                { name:'ModelScope 空间页面', url:ms.repo_url || 'https://modelscope.cn/studios/Daniel8152/Infinite-Canvas', source:'modelscope' },
                { name:'ModelScope 主页', url:'https://modelscope.cn/', source:'modelscope' },
                { name:'Google 连通性', url:'https://www.google.com/generate_204', source:'reference' },
            ];
        }

        function renderConnectivityList(results = []) {
            const allItems = results.length ? results : updateConnectivityTargets().map(item => ({...item, pending:false, untouched:true}));
            const renderInto = (list, source) => {
                if(!list) return;
                list.replaceChildren();
                const items = allItems.filter(item => item.source === source || (source === 'github' && item.source === 'reference'));
                items.forEach(item => {
                const row = document.createElement('div');
                row.className = `connectivity-row ${item.pending ? 'pending' : item.untouched ? '' : item.ok ? 'ok' : 'fail'}`;
                const indicator = document.createElement('span');
                indicator.className = 'connectivity-indicator';
                const meta = document.createElement('div');
                const name = document.createElement('div');
                name.className = 'connectivity-name';
                name.textContent = updateTargetLabel(item.name);
                const url = document.createElement('div');
                url.className = 'connectivity-url';
                url.textContent = item.url || '';
                meta.append(name, url);
                const status = document.createElement('div');
                status.className = 'connectivity-status';
                status.textContent = item.untouched ? updateUiText('待测试', 'Not tested') : updateStatusLabel(item);
                row.append(indicator, meta, status);
                if(item.error && !item.timed_out) {
                    const error = document.createElement('div');
                    error.className = 'connectivity-error';
                    error.textContent = String(item.error).slice(0, 220);
                    row.append(error);
                }
                list.append(row);
            });
            };
            renderInto(document.querySelector('[data-connectivity-source="github"]'), 'github');
            renderInto(document.querySelector('[data-connectivity-source="modelscope"]'), 'modelscope');
        }

        function refreshProjectUpdateModalText() {
            const gitBtn = document.getElementById('github-entry-btn');
            const remoteVersion = gitBtn?.dataset.remoteVersion || '';
            const localVersion = gitBtn?.dataset.localVersion || appInfo.version || '';
            const sourceName = updateSourceLabel();
            const title = remoteVersion
                ? updateUiText(`更新到 ${versionLabel(remoteVersion)}`, `Update to ${versionLabel(remoteVersion)}`)
                : updateUiText('一键更新', 'One-click update');
            const titleEl = document.getElementById('project-update-title');
            const copyEl = document.getElementById('project-update-copy');
            const testText = document.getElementById('connectivity-test-text');
            const cancelText = document.getElementById('project-update-cancel-text');
            const confirmText = document.getElementById('project-update-confirm-text');
            const closeBtn = document.querySelector('#project-update-modal .studio-modal-close');
            if(titleEl) titleEl.textContent = title;
            renderProjectUpdateNotes();
            document.querySelectorAll('[data-update-source]').forEach(card => {
                const source = card.dataset.updateSource || 'github';
                const active = source === updateSource;
                card.classList.toggle('active', active);
                card.setAttribute('aria-pressed', active ? 'true' : 'false');
                const badge = card.querySelector('.update-source-badge');
                if(badge) {
                    if(!updateConnectivityResult) {
                        setSourceBadge(badge, '', updateUiText('待测试', 'Not tested'));
                    } else {
                        const stats = sourceConnectivityStats(source, updateConnectivityResult.results || []);
                        setSourceBadge(badge, stats.ok ? 'ok' : 'bad',
                            stats.ok ? updateUiText('可用', 'Available') : updateUiText('不可用', 'Unavailable'));
                    }
                }
            });
            if(copyEl) copyEl.textContent = updateUiText(
                `将从 ${sourceName} 更新 main.py、VERSION 和 static 文件。更新前会自动备份，更新完成后后端会自动重启。当前 ${versionLabel(localVersion)}，最新 ${versionLabel(remoteVersion || localVersion)}。`,
                `This updates main.py, VERSION, and static files from ${sourceName}. A backup is created first, then the backend restarts automatically. Current ${versionLabel(localVersion)}, latest ${versionLabel(remoteVersion || localVersion)}.`
            );
            if(testText) testText.textContent = updateConnectivityResult ? updateUiText('重新测试', 'Retest') : updateUiText('测试连通性', 'Test connectivity');
            if(cancelText) cancelText.textContent = updateUiText('取消', 'Cancel');
            if(confirmText && !projectUpdateRunning) confirmText.textContent = updateUiText('开始更新', 'Start update');
            if(closeBtn) {
                closeBtn.title = updateUiText('关闭', 'Close');
                closeBtn.setAttribute('aria-label', closeBtn.title);
            }
            if(!updateConnectivityResult) {
                setUpdateSummary(
                    'warn',
                    updateUiText('建议先测试连通性', 'Connectivity test recommended'),
                    updateUiText(
                        '测试会同时测速 GitHub 和 ModelScope。你可以根据结果切换下载源。',
                        'The test checks both GitHub and ModelScope. Choose the faster reachable source before updating.'
                    )
                );
            } else if(updateConnectivityResult.backend_missing) {
                setUpdateSummary(
                    'fail',
                    updateUiText('需要重启后端', 'Backend restart required'),
                    updateUiText(
                        '当前页面已经更新，但后端仍是旧版本，所以找不到连通性测试接口。请重启服务后再试。',
                        'The page is updated, but the backend is still the old version and cannot find the connectivity-test API. Restart the service and try again.'
                    )
                );
            } else if((updateConnectivityResult.sources || {})[updateSource]?.ok || (updateSource === 'github' && updateConnectivityResult.ok)) {
                const google = (updateConnectivityResult.results || []).find(item => item.name === 'Google 连通性');
                const sourceResults = (updateConnectivityResult.results || []).filter(item => item.source === updateSource);
                const fastest = sourceResults.filter(item => item.ok).sort((a, b) => (a.elapsed_ms || 999999) - (b.elapsed_ms || 999999))[0];
                setUpdateSummary(
                    google?.ok ? 'ok' : 'warn',
                    updateUiText(`${sourceName} 下载源可用`, `${sourceName} source reachable`),
                    fastest
                        ? updateUiText(`${sourceName} 可访问，最快节点约 ${fastest.elapsed_ms || 0}ms，可以开始更新。`, `${sourceName} is reachable; fastest endpoint is about ${fastest.elapsed_ms || 0}ms.`)
                        : updateUiText(`${sourceName} 更新节点可用，可以开始更新。`, `${sourceName} update endpoints are reachable.`)
                );
            } else {
                setUpdateSummary(
                    'fail',
                    updateUiText(`${sourceName} 下载源不可用`, `${sourceName} source unreachable`),
                    updateUiText(
                        `当前网络无法访问 ${sourceName} 必需节点。请切换下载源，或检查代理、DNS 后重试。`,
                        `This network cannot reach required ${sourceName} endpoints. Switch source, or check proxy/DNS and try again.`
                    )
                );
            }
            renderConnectivityList(updateConnectivityResult?.results || []);
        }

        function openProjectUpdateModal() {
            const modal = document.getElementById('project-update-modal');
            if(!modal) return;
            updateConnectivityResult = null;
            refreshProjectUpdateModalText();
            modal.hidden = false;
            document.getElementById('connectivity-test-btn')?.focus?.();
        }

        function closeProjectUpdateModal() {
            // 更新进行中允许关闭：中止在途请求并恢复 UI，避免「卡在更新中、无法关闭」
            if(projectUpdateRunning) {
                try { projectUpdateAbort?.abort(); } catch(e) {}
            }
            const modal = document.getElementById('project-update-modal');
            if(modal) modal.hidden = true;
        }

        document.getElementById('project-update-modal')?.addEventListener('click', event => {
            if(event.target?.id === 'project-update-modal') closeProjectUpdateModal();
        });

        window.addEventListener('keydown', event => {
            if(event.key === 'Escape') closeProjectUpdateModal();
        });

        async function runProjectUpdate() {
            openProjectUpdateModal();
        }

        function computeConnectivitySources(results) {
            const out = {};
            for(const source of ['github', 'modelscope']) {
                const reqAll = (results || []).filter(it => it.source === source && it.required);
                out[source] = {
                    ok: reqAll.length > 0 && reqAll.every(it => it.ok),
                    required: reqAll.map(it => it.name),
                };
            }
            return out;
        }

        function setSourceBadge(badge, state, text) {
            if(!badge) return;
            badge.classList.remove('ok', 'bad');
            if(state) badge.classList.add(state);
            badge.textContent = text;
        }

        function renderSourceBadgesLive(results) {
            document.querySelectorAll('[data-update-source]').forEach(card => {
                const source = card.dataset.updateSource || 'github';
                const badge = card.querySelector('.update-source-badge');
                if(!badge) return;
                const items = (results || []).filter(it => it.source === source);
                if(!items.length) return;
                const done = items.filter(it => !it.pending && !it.untouched);
                if(done.length < items.length) {
                    setSourceBadge(badge, '', updateUiText(`检测中 ${done.length}/${items.length}`, `${done.length}/${items.length}`));
                    return;
                }
                const stats = sourceConnectivityStats(source, results);
                setSourceBadge(badge, stats.ok ? 'ok' : 'bad',
                    stats.ok ? updateUiText('可用', 'Available') : updateUiText('不可用', 'Unavailable'));
            });
        }

        let connectivityTesting = false;
        async function runUpdateConnectivityTest() {
            if(connectivityTesting) return; // 防止重复点击导致状态错乱
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const btn = document.getElementById('connectivity-test-btn');
            const text = document.getElementById('connectivity-test-text');
            connectivityTesting = true;
            if(btn) btn.disabled = true;
            if(text) text.textContent = isEn ? 'Testing...' : '检测中...';
            updateConnectivityResult = null;

            const targets = updateConnectivityTargets();
            // 实时状态数组：先全部置为「检测中」，每条探测完成立即刷新对应行
            const live = targets.map(item => ({...item, pending:true, untouched:false}));
            let backendMissing = false;
            const applyResult = (name, patch) => {
                const i = live.findIndex(x => x.name === name);
                if(i < 0) return;
                live[i] = {...live[i], pending:false, untouched:false, ...patch};
                renderConnectivityList(live);
                renderSourceBadgesLive(live);
            };

            const probeOne = async (t) => {
                // 客户端兜底超时：5s 探测 + 1s 网络余量，超时即报「超时」，不会永远卡在「检测中」
                const ac = new AbortController();
                const killer = setTimeout(() => ac.abort(), 6000);
                try {
                    const res = await fetch(`/api/update-connectivity/probe?name=${encodeURIComponent(t.name)}`, { cache:'no-store', signal:ac.signal });
                    const data = await res.json().catch(() => ({}));
                    // 旧后端没有单条探测接口 → 404 Not Found，标记后回退到整体接口
                    if(res.status === 404 && (data.detail === 'Not Found' || data.detail === undefined)) {
                        backendMissing = true;
                        return;
                    }
                    if(res.ok) {
                        applyResult(t.name, { ok:!!data.ok, status:data.status || 0, elapsed_ms:data.elapsed_ms || 0, error:data.error || '', timed_out:!!data.timed_out });
                    } else {
                        applyResult(t.name, { ok:false, error:data.detail || (isEn ? 'Failed' : '失败') });
                    }
                } catch(e) {
                    if(e && e.name === 'AbortError') {
                        applyResult(t.name, { ok:false, timed_out:true, error:isEn ? 'Timed out (over 5s)' : '连接超时（超过 5s）' });
                    } else {
                        applyResult(t.name, { ok:false, error:describeNetworkError(e, isEn) });
                    }
                } finally {
                    clearTimeout(killer);
                }
            };

            try {
                setUpdateSummary('warn', isEn ? 'Testing connectivity' : '正在测试连通性', isEn ? 'Probing each endpoint — results stream in live.' : '正在逐条检测各节点，结果实时显示。');
                renderConnectivityList(live);
                renderSourceBadgesLive(live);
                await Promise.all(targets.map(probeOne));

                if(backendMissing) {
                    // 兜底：尝试旧的整体接口
                    try {
                        const res = await fetch('/api/update-connectivity', { cache:'no-store' });
                        const data = await res.json().catch(() => ({}));
                        if(res.ok && Array.isArray(data.results)) {
                            updateConnectivityResult = data;
                            setUpdateSource(bestUpdateSourceFromConnectivity(data));
                            return;
                        }
                    } catch(e) {}
                    const message = isEn
                        ? 'The backend has not loaded the new connectivity-test API yet. Restart the backend service, then test again.'
                        : '后端还没有加载新的连通性测试接口。请重启服务后再测试。';
                    updateConnectivityResult = {
                        ok:false,
                        backend_missing:true,
                        results:targets.map(item => ({...item, ok:false, elapsed_ms:0, error:message })),
                    };
                    return;
                }

                const results = live.map(({pending, untouched, ...rest}) => rest);
                const sources = computeConnectivitySources(results);
                updateConnectivityResult = { results, sources, ok:sources.github.ok };
                setUpdateSource(bestUpdateSourceFromConnectivity(updateConnectivityResult));
            } finally {
                connectivityTesting = false;
                if(btn) btn.disabled = false;
                refreshProjectUpdateModalText();
            }
        }

        async function confirmProjectUpdate() {
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const btn = document.getElementById('update-now-btn');
            const text = document.getElementById('update-now-text');
            const confirmBtn = document.getElementById('project-update-confirm-btn');
            const confirmText = document.getElementById('project-update-confirm-text');
            const testBtn = document.getElementById('connectivity-test-btn');
            const oldText = text?.textContent || '';
            projectUpdateRunning = true;
            if(btn) btn.disabled = true;
            if(confirmBtn) confirmBtn.disabled = true;
            if(testBtn) testBtn.disabled = true;
            if(text) text.textContent = isEn ? 'Updating...' : '更新中...';
            if(confirmText) confirmText.textContent = isEn ? 'Updating...' : '更新中...';
            const sourceName = updateSourceLabel();
            setUpdateSummary('warn', isEn ? 'Updating' : '正在更新', isEn ? `Downloading files from ${sourceName} and creating a local backup.` : `正在从 ${sourceName} 下载文件，并创建本地备份。`);
            // 客户端兜底超时：即使后端异常挂起，UI 也能恢复，不会永远停在「更新中」
            const ac = new AbortController();
            const killer = setTimeout(() => ac.abort(), 300000);
            try {
                const res = await fetch('/api/update-from-github', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({ auto_restart:true, restart_delay:3, source:updateSource, fallback:true }),
                    signal:ac.signal
                });
                const data = await res.json().catch(() => ({}));
                if(!res.ok) throw new Error(data.detail || (isEn ? 'Update failed' : '更新失败'));
                if(data.update_notes) setProjectUpdateNotes(data.update_notes);
                const restarting = data.restart_scheduled;
                const usedLabel = data.source_label || (data.source === 'modelscope' ? 'ModelScope' : 'GitHub');
                const fallbackNote = data.fallback_used
                    ? (isEn
                        ? ` (${sourceName} was unreachable, so it fell back to ${usedLabel})`
                        : `（${sourceName} 不可用，已自动兜底切换到 ${usedLabel}）`)
                    : '';
                setUpdateSummary(
                    'ok',
                    isEn ? 'Update complete' : '更新完成',
                    (restarting
                        ? (isEn
                            ? `Updated ${data.count || 0} files. The backend will restart in about 3 seconds; this page will reload when it returns.`
                            : `已更新 ${data.count || 0} 个文件。后端将在约 3 秒后自动重启，本页面会在恢复后自动刷新。`)
                        : (isEn
                            ? `Updated ${data.count || 0} files. Please restart the backend, then refresh this page.`
                            : `已更新 ${data.count || 0} 个文件。请重启后端，然后刷新页面。`)) + fallbackNote
                );
                document.getElementById('github-entry-btn')?.classList.remove('update-available');
                btn?.classList.remove('show');
                setProjectVersionBadge(data.version || document.getElementById('github-entry-btn')?.dataset.remoteVersion || appInfo.version);
                if(restarting) waitForBackendAndReload();
            } catch(e) {
                const msg = (e && e.name === 'AbortError')
                    ? (isEn ? 'Update timed out. Switch source or check your network, then retry.' : '更新超时。请切换下载源或检查网络后重试。')
                    : describeNetworkError(e, isEn);
                setUpdateSummary('fail', isEn ? 'Update failed' : '更新失败', msg);
            } finally {
                clearTimeout(killer);
                projectUpdateRunning = false;
                if(btn) btn.disabled = false;
                if(confirmBtn) confirmBtn.disabled = false;
                if(testBtn) testBtn.disabled = false;
                if(text) text.textContent = oldText || (isEn ? 'Update' : '一键更新');
                if(confirmText) confirmText.textContent = isEn ? 'Start update' : '开始更新';
                refreshUpdateButtonText();
            }
        }
        async function waitForBackendAndReload() {
            const deadline = Date.now() + 90 * 1000;
            await new Promise(r => setTimeout(r, 4000));
            while(Date.now() < deadline) {
                try {
                    const r = await fetch('/api/app-info', { cache:'no-store' });
                    if(r.ok) { location.reload(); return; }
                } catch {}
                await new Promise(r => setTimeout(r, 1500));
            }
        }
        async function rollbackProjectUpdate() {
            const isEn = window.StudioI18n?.lang?.() === 'en';
            try {
                const list = await fetch('/api/update-backups').then(r => r.json());
                const backups = list.backups || [];
                if(!backups.length){ alert(isEn ? 'No backups available.' : '没有可用的备份'); return; }
                const lines = backups.slice(0, 10).map((b, i) => {
                    const d = new Date((b.created_at || 0) * 1000);
                    const ts = d.toLocaleString();
                    const versions = b.from_version
                        ? `  [${b.from_version}${b.target_version ? ` -> ${b.target_version}` : ''}]`
                        : '';
                    const notes = Array.isArray(b.update_notes?.items)
                        ? b.update_notes.items.map(item => String(item?.text || '').trim()).filter(Boolean).slice(0, 3)
                        : [];
                    const changeText = notes.length
                        ? `\n   更新内容：${notes.join('；')}`
                        : (b.affected_file_count ? `\n   影响文件：${b.affected_file_count} 个` : '');
                    return `${i + 1}. ${b.name}${versions}  (${b.file_count} files, ${ts})${changeText}`;
                });
                const promptMsg = (isEn
                    ? 'Select a backup to restore (enter the number):\n'
                    : '选择要还原的备份（输入序号）：\n') + lines.join('\n');
                const answer = prompt(promptMsg, '1');
                const idx = Number(answer) - 1;
                if(!(idx >= 0 && idx < backups.length)) return;
                const target = backups[idx];
                if(!confirm(isEn ? `Restore "${target.name}"? Backend will restart.` : `要还原 "${target.name}" 吗？后端会自动重启。`)) return;
                const res = await fetch('/api/update-rollback', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({ name:target.name, auto_restart:true, restart_delay:3 })
                });
                const data = await res.json().catch(() => ({}));
                if(!res.ok) throw new Error(data.detail || (isEn ? 'Rollback failed' : '回滚失败'));
                alert(isEn
                    ? `Restored ${data.count || 0} files. A safety restore point was created, and the backend is restarting.`
                    : `已还原 ${data.count || 0} 个文件，当前版本已自动保存为新的恢复点。后端正在重启。`);
                if(data.restart_scheduled) waitForBackendAndReload();
            } catch(e) {
                alert((isEn ? 'Rollback failed: ' : '回滚失败：') + describeNetworkError(e, isEn));
            }
        }
        window.rollbackProjectUpdate = rollbackProjectUpdate;

        async function checkForUpdates(manual = false) {
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const badge = document.getElementById('project-version-badge');
            if(manual && badge) badge.classList.add('checking');
            try {
                const info = await fetch('/api/app-info', { cache:'no-store' }).then(r => r.json()).catch(() => ({}));
                appInfo = {...appInfo, ...info};
                let current = String(appInfo.version || '').trim();
                setProjectVersionBadge(current);
                let best = null;
                let reachable = false;
                let serverChecked = false;
                // 优先走后端检测：服务端用系统代理同时检测 GitHub 和 ModelScope，避免浏览器跨域/被墙
                try {
                    const r = await fetch('/api/check-update', { cache:'no-store' });
                    if(r.ok) {
                        const d = await r.json();
                        serverChecked = true;
                        reachable = !!d.reachable;
                        if(d.current) { current = String(d.current).trim(); setProjectVersionBadge(current); }
                        if(d.latest?.version) best = {source:d.latest.source, version:d.latest.version, update_notes:d.latest.update_notes || d.update_notes || null};
                    }
                } catch(e) {}
                // 兜底：旧后端无 /api/check-update 时，浏览器直接拉取双源 VERSION
                if(!serverChecked) {
                    const sources = appInfo.sources || {};
                    const candidates = [
                        {source:'github', url:sources.github?.version_url || appInfo.version_url || ''},
                        {source:'modelscope', url:sources.modelscope?.version_url || ''},
                    ].filter(item => item.url);
                    for(const item of candidates) {
                        try {
                            const remoteText = await fetch(`${item.url}${item.url.includes('?') ? '&' : '?'}t=${Date.now()}`, { cache:'no-store' }).then(r => r.ok ? r.text() : '');
                            const remote = String(remoteText || '').trim().split(/\r?\n/)[0].trim();
                            if(remote){ reachable = true; if(!best || compareVersions(remote, best.version) > 0) best = {source:item.source, version:remote}; }
                        } catch(e) {}
                    }
                }
                const hasUpdate = !!(current && best?.version && compareVersions(best.version, current) > 0);
                if(hasUpdate) {
                    if(best.source === 'modelscope') setUpdateSource('modelscope');
                    setProjectUpdateNotes(best.update_notes || null);
                    showUpdateNotice(current, best.version);
                }
                if(manual) {
                    if(hasUpdate) {
                        openProjectUpdateModal();
                    } else if(reachable) {
                        alert(isEn ? `You are on the latest version (${versionLabel(current)}).` : `已是最新版本（${versionLabel(current)}）。`);
                    } else {
                        alert(isEn ? 'Could not reach GitHub or ModelScope. Check your network/proxy and try again.' : '无法连接 GitHub 或 ModelScope 更新源，请检查网络或代理后重试。');
                    }
                }
            } catch(e) {
                // 离线包里没有网络时保持安静，不影响本地使用。
                if(manual) alert(isEn ? 'Update check failed.' : '检测更新失败。');
            } finally {
                if(badge) badge.classList.remove('checking');
            }
        }
