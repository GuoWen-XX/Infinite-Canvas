// Network & Port Management Controller
let networkViewOpen = false;

function escapeHtmlNet(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function openNetworkSettings() {
    networkViewOpen = true;
    if (typeof extToolsViewOpen !== 'undefined') extToolsViewOpen = false;
    if (typeof modulesViewOpen !== 'undefined') modulesViewOpen = false;
    if (typeof aboutViewOpen !== 'undefined') aboutViewOpen = false;
    if (typeof recommendInlineOpen !== 'undefined') recommendInlineOpen = false;
    syncNetworkView();
    loadNetworkSettings();
}

function closeNetworkSettings() {
    networkViewOpen = false;
    syncNetworkView();
    if (typeof renderEditor === 'function') renderEditor();
}

function syncNetworkView() {
    const netContent = document.getElementById('networkContent');
    const setContent = document.getElementById('settingsContent');
    const recContent = document.getElementById('recommendContent');
    const extContent = document.getElementById('extToolsContent');
    const modContent = document.getElementById('modulesContent');
    const abtContent = document.getElementById('aboutContent');
    const isOtherOpen = (typeof recommendInlineOpen !== 'undefined' && recommendInlineOpen) ||
                        (typeof extToolsViewOpen !== 'undefined' && extToolsViewOpen) ||
                        (typeof modulesViewOpen !== 'undefined' && modulesViewOpen) ||
                        (typeof aboutViewOpen !== 'undefined' && aboutViewOpen);

    if (setContent) setContent.hidden = networkViewOpen || isOtherOpen;
    if (recContent) recContent.hidden = !(typeof recommendInlineOpen !== 'undefined' && recommendInlineOpen);
    if (extContent) extContent.hidden = !(typeof extToolsViewOpen !== 'undefined' && extToolsViewOpen);
    if (modContent) modContent.hidden = !(typeof modulesViewOpen !== 'undefined' && modulesViewOpen);
    if (abtContent) abtContent.hidden = !(typeof aboutViewOpen !== 'undefined' && aboutViewOpen);
    if (netContent) netContent.hidden = !networkViewOpen;

    if (typeof syncSidebarNavState === 'function') syncSidebarNavState();
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

async function loadNetworkSettings() {
    try {
        const res = await fetch('/api/network/ports/status');
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();

        // Proxy settings
        const proxyCheck = document.getElementById('networkProxyEnabled');
        const proxyHost = document.getElementById('networkProxyHost');
        const proxyPort = document.getElementById('networkProxyPort');
        const proxy = data.proxy || {};
        if (proxyCheck) proxyCheck.checked = !!proxy.enabled;
        if (proxyHost) proxyHost.value = proxy.host || '127.0.0.1';
        if (proxyPort) proxyPort.value = proxy.port || 7897;

        // ComfyUI instances
        const comfy = data.comfy || data.comfyui || {};
        const rawInstances = comfy.instances || [];
        const parsedInstances = rawInstances.map(inst => {
            if (typeof inst === 'string') {
                const parts = inst.split(':');
                return { host: parts[0] || '127.0.0.1', port: parseInt(parts[1] || '8188', 10) };
            }
            return inst;
        });
        renderNetworkComfyInstances(parsedInstances);

        // Server Info
        const server = data.server || data.canvas_server || {};
        const srvActive = document.getElementById('serverActivePortText');
        const srvBind = document.getElementById('serverBindModeText');
        const srvInput = document.getElementById('serverPortInput');
        if (srvActive) srvActive.textContent = server.current_port || server.port || 3333;
        if (srvBind) {
            const isLan = !!server.is_lan;
            srvBind.textContent = isLan ? '0.0.0.0 (局域网开放)' : '127.0.0.1 (仅本机)';
        }
        if (srvInput) srvInput.value = server.configured_port || server.default_env_port || 3333;
    } catch (e) {
        if (typeof setStatus === 'function') setStatus('加载网络端口配置失败: ' + (e.message || e));
    }
}

function renderNetworkComfyInstances(instances) {
    const container = document.getElementById('comfyInstanceListContainer');
    if (!container) return;
    if (!instances || instances.length === 0) {
        instances = [{ host: '127.0.0.1', port: 8188, active: true }];
    }
    const probeLabel = (typeof tr === 'function' ? tr('api.probeInstance') : '') || '测活';
    container.innerHTML = instances.map((inst, idx) => `
        <div class="comfy-instance-row" data-index="${idx}">
            <span class="instance-label" style="min-width:64px;font-size:12px;font-weight:600;color:var(--text);">${idx === 0 ? '主实例' : '备用 #' + idx}</span>
            <input type="text" class="instance-host" value="${escapeHtmlNet(inst.host || '127.0.0.1')}" placeholder="127.0.0.1" style="flex:1;min-width:140px;padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-size:13px;">
            <span style="color:var(--text-muted);font-weight:600;">:</span>
            <input type="number" class="instance-port" value="${inst.port || 8188}" placeholder="8188" min="1" max="65535" style="width:84px;padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-size:13px;">
            <button type="button" class="action-btn probe-btn" onclick="probeComfyInstance(this)" style="padding:6px 12px;font-size:12px;">
                <i data-lucide="activity" class="w-3 h-3"></i><span>${probeLabel}</span>
            </button>
            <span class="network-status-badge comfy-probe-badge" style="display:none;"></span>
            ${instances.length > 1 ? `
            <button type="button" class="remove-btn" onclick="removeComfyInstanceRow(this)" title="删除" style="padding:6px;border:none;background:transparent;cursor:pointer;color:var(--text-muted);">
                <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>` : ''}
        </div>
    `).join('');
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

function addComfyInstanceRow() {
    const container = document.getElementById('comfyInstanceListContainer');
    if (!container) return;
    const count = container.children.length;
    const probeLabel = (typeof tr === 'function' ? tr('api.probeInstance') : '') || '测活';
    const row = document.createElement('div');
    row.className = 'comfy-instance-row';
    row.dataset.index = count;
    row.innerHTML = `
        <span class="instance-label" style="min-width:64px;font-size:12px;font-weight:600;color:var(--text);">备用 #${count}</span>
        <input type="text" class="instance-host" value="127.0.0.1" placeholder="127.0.0.1" style="flex:1;min-width:140px;padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-size:13px;">
        <span style="color:var(--text-muted);font-weight:600;">:</span>
        <input type="number" class="instance-port" value="${8188 + count}" placeholder="8189" min="1" max="65535" style="width:84px;padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-size:13px;">
        <button type="button" class="action-btn probe-btn" onclick="probeComfyInstance(this)" style="padding:6px 12px;font-size:12px;">
            <i data-lucide="activity" class="w-3 h-3"></i><span>${probeLabel}</span>
        </button>
        <span class="network-status-badge comfy-probe-badge" style="display:none;"></span>
        <button type="button" class="remove-btn" onclick="removeComfyInstanceRow(this)" title="删除" style="padding:6px;border:none;background:transparent;cursor:pointer;color:var(--text-muted);">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
        </button>
    `;
    container.appendChild(row);
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

function removeComfyInstanceRow(btn) {
    const row = btn.closest('.comfy-instance-row');
    if (row) {
        row.remove();
        const container = document.getElementById('comfyInstanceListContainer');
        if (container) {
            Array.from(container.children).forEach((r, idx) => {
                r.dataset.index = idx;
                const label = r.querySelector('.instance-label');
                if (label) label.textContent = idx === 0 ? '主实例' : '备用 #' + idx;
            });
        }
    }
}

async function probeComfyInstance(btn) {
    const row = btn.closest('.comfy-instance-row');
    if (!row) return;
    const host = (row.querySelector('.instance-host')?.value || '127.0.0.1').trim();
    const port = parseInt(row.querySelector('.instance-port')?.value || '8188', 10);
    const badge = row.querySelector('.comfy-probe-badge');
    if (badge) {
        badge.style.display = 'inline-flex';
        badge.className = 'network-status-badge badge-pending';
        badge.textContent = '探测中...';
    }
    try {
        const res = await fetch('/api/network/ports/test-comfy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instance: `${host}:${port}`, host, port })
        });
        const result = await res.json();
        if (badge) {
            if (result.ok) {
                badge.className = 'network-status-badge badge-active';
                badge.textContent = `在线 (${result.latency_ms}ms)`;
            } else {
                badge.className = 'network-status-badge badge-error';
                badge.textContent = `离线 (${result.error || '503'})`;
            }
        }
    } catch (e) {
        if (badge) {
            badge.className = 'network-status-badge badge-error';
            badge.textContent = '请求异常';
        }
    }
}

function setNetworkProxyPreset(port) {
    const portInput = document.getElementById('networkProxyPort');
    const enabledInput = document.getElementById('networkProxyEnabled');
    if (portInput) portInput.value = port;
    if (enabledInput) enabledInput.checked = true;
    onNetworkProxyToggle();
}

function onNetworkProxyToggle() {
    // Live update when toggle switch changed
}

async function testProxyConnection() {
    const host = (document.getElementById('networkProxyHost')?.value || '127.0.0.1').trim();
    const port = parseInt(document.getElementById('networkProxyPort')?.value || '7897', 10);
    const btn = document.getElementById('testProxyBtn');
    const badge = document.getElementById('proxyTestStatusBadge');

    if (badge) {
        badge.style.display = 'inline-flex';
        badge.className = 'network-status-badge badge-pending';
        badge.textContent = '测试中...';
    }
    if (btn) btn.disabled = true;

    try {
        const res = await fetch('/api/network/ports/test-proxy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host, port })
        });
        const result = await res.json();
        if (badge) {
            if (result.ok) {
                badge.className = 'network-status-badge badge-active';
                badge.textContent = `连通正常 (${result.latency_ms}ms)`;
            } else {
                badge.className = 'network-status-badge badge-error';
                badge.textContent = `连接失败: ${result.error || '超时'}`;
            }
        }
    } catch (e) {
        if (badge) {
            badge.className = 'network-status-badge badge-error';
            badge.textContent = '测试请求异常';
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function saveNetworkSettings() {
    const proxyEnabled = !!document.getElementById('networkProxyEnabled')?.checked;
    const proxyHost = (document.getElementById('networkProxyHost')?.value || '127.0.0.1').trim();
    const proxyPort = parseInt(document.getElementById('networkProxyPort')?.value || '7897', 10);
    const serverPort = parseInt(document.getElementById('serverPortInput')?.value || '3333', 10);

    const container = document.getElementById('comfyInstanceListContainer');
    const instances = [];
    if (container) {
        Array.from(container.children).forEach(row => {
            const h = (row.querySelector('.instance-host')?.value || '127.0.0.1').trim();
            const p = parseInt(row.querySelector('.instance-port')?.value || '8188', 10);
            if (h && p > 0 && p <= 65535) {
                instances.push(`${h}:${p}`);
            }
        });
    }

    const payload = {
        proxy_enabled: proxyEnabled,
        proxy_host: proxyHost,
        proxy_port: proxyPort,
        comfy_instances: instances.length > 0 ? instances : ['127.0.0.1:8188'],
        server_port: serverPort
    };

    try {
        const res = await fetch('/api/network/ports/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || '保存失败');
        }
        const data = await res.json();
        const msg = (typeof tr === 'function' ? tr('api.networkSaved') : '') || '网络与端口配置已保存并热生效';
        if (typeof setStatus === 'function') {
            setStatus(msg);
        }
        await loadNetworkSettings();
    } catch (e) {
        if (typeof setStatus === 'function') {
            setStatus('保存网络配置失败: ' + (e.message || e));
        }
    }
}
