/* Skill 库管理页（Phase 4）。对应后端 /api/skills*（main.py 尾部 section）。
   Skill 是指令文档包：仅读取/展示/导入/升级，脚本永不执行。 */

const grid = document.getElementById('skillGrid');
const statusEl = document.getElementById('skillStatus');
const toastEl = document.getElementById('skillToast');
const zipInput = document.getElementById('skillZipInput');
const tabsEl = document.getElementById('skillTabs');

let allSkills = [];
let activeSource = 'custom';
let editingId = '';
let editBaseSha = '';
let ghPreview = null;

const SOURCE_LABELS = { custom: '我的', builtin: '内置', codex: 'Codex' };

function toast(message, duration = 3200) {
    toastEl.textContent = message;
    toastEl.classList.add('show');
    clearTimeout(toastEl._timer);
    toastEl._timer = setTimeout(() => toastEl.classList.remove('show'), duration);
}
function setStatus(text) { statusEl.textContent = text; }
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}
function formatBytes(bytes) {
    const n = Number(bytes || 0);
    if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    if (n >= 1024) return Math.round(n / 1024) + ' KB';
    return n + ' B';
}
function openOverlay(id) { document.getElementById(id).hidden = false; refreshIcons(); }
function closeOverlay(id) { document.getElementById(id).hidden = true; }
function refreshIcons() { try { window.lucide?.createIcons(); } catch (e) {} }

async function api(path, options = {}) {
    const response = await fetch(path, options);
    const data = await response.json().catch(async () => ({ detail: await response.text().catch(() => '') }));
    if (!response.ok) {
        const detail = typeof data?.detail === 'object' ? JSON.stringify(data.detail) : (data?.detail || `HTTP ${response.status}`);
        const error = new Error(String(detail).slice(0, 300));
        error.statusCode = response.status;
        throw error;
    }
    return data;
}

async function loadSkills() {
    setStatus('加载中…');
    try {
        const data = await api('/api/skills');
        allSkills = Array.isArray(data.skills) ? data.skills : [];
        renderGrid();
        setStatus(`共 ${allSkills.length} 个 Skill`);
    } catch (error) {
        setStatus('加载失败');
        toast(error.message || '加载失败');
    }
}

function renderGrid() {
    const items = allSkills.filter(item => item.source === activeSource);
    if (!items.length) {
        grid.innerHTML = `<div class="skill-empty">${activeSource === 'custom' ? '还没有自建或导入的 Skill。点击右上角「GitHub 导入」或「新建」开始。' : '该来源暂无 Skill。'}</div>`;
        return;
    }
    grid.innerHTML = items.map(item => {
        const badges = [
            `<span class="skill-badge src-${item.source}">${SOURCE_LABELS[item.source] || item.source}</span>`,
            item.version ? `<span class="skill-badge src-codex">v${escapeHtml(item.version)}</span>` : '',
            item.has_scripts ? '<span class="skill-badge warn">含脚本·不执行</span>' : '',
            item.has_skill_md ? '' : '<span class="skill-badge err">缺 SKILL.md</span>',
        ].filter(Boolean).join('');
        const install = item.install || {};
        const actions = [];
        actions.push(`<button class="skill-mini-btn" type="button" data-act="detail" data-id="${escapeHtml(item.id)}"><i data-lucide="eye"></i>详情</button>`);
        if (item.source === 'custom') {
            actions.push(`<button class="skill-mini-btn" type="button" data-act="edit" data-id="${escapeHtml(item.id)}"><i data-lucide="pencil"></i>编辑</button>`);
            if (install.source === 'github' && install.repo_url) {
                actions.push(`<button class="skill-mini-btn" type="button" data-act="update" data-id="${escapeHtml(item.id)}"><i data-lucide="arrow-up-circle"></i>检查更新</button>`);
            }
            actions.push(`<button class="skill-mini-btn danger" type="button" data-act="delete" data-id="${escapeHtml(item.id)}"><i data-lucide="trash-2"></i>删除</button>`);
        }
        const updated = item.updated_at ? new Date(item.updated_at).toLocaleString('zh-CN', { hour12: false }) : '';
        return `<div class="skill-card">
            <div class="skill-card-head">
                <div class="skill-card-name">${escapeHtml(item.name)}</div>
                <div class="skill-card-badges">${badges}</div>
            </div>
            <div class="skill-card-desc">${escapeHtml(item.description || item.summary || '（无描述）')}</div>
            <div class="skill-card-meta">
                <span>${escapeHtml(item.id)}</span>
                <span>${item.files} 个文件 · ${formatBytes(item.total_bytes)}</span>
                ${item.references_count ? `<span>参考 ${item.references_count}</span>` : ''}
                ${item.assets_count ? `<span>素材 ${item.assets_count}</span>` : ''}
                ${install.commit_sha ? `<span title="${escapeHtml(install.repo_url)}">SHA ${escapeHtml(String(install.commit_sha).slice(0, 7))}</span>` : ''}
                ${updated ? `<span>${updated}</span>` : ''}
            </div>
            <div class="skill-card-actions">${actions.join('')}</div>
        </div>`;
    }).join('');
    refreshIcons();
}

grid.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-act]');
    if (!button) return;
    const id = button.dataset.id;
    const item = allSkills.find(s => s.source === activeSource && s.id === id);
    if (!item) return;
    const action = button.dataset.act;
    if (action === 'detail') await showDetail(item);
    if (action === 'edit') openEditor(item);
    if (action === 'delete') await deleteSkill(item);
    if (action === 'update') await checkUpdate(item);
});

async function showDetail(item) {
    document.getElementById('skillDetailTitle').textContent = item.name || item.id;
    const body = document.getElementById('skillDetailBody');
    try {
        const detail = await api(`/api/skills/${item.source}/${encodeURIComponent(item.id)}`);
        const install = detail.install || {};
        const warnings = (detail.warnings || []).map(w => `<div class="row"><span class="v warnline">⚠ ${escapeHtml(w)}</span></div>`).join('');
        const files = (detail.file_list || []).slice(0, 60).map(f => escapeHtml(f)).join('<br>');
        body.innerHTML = `
            ${warnings}
            <div class="gh-confirm-box">
                <div class="row"><span class="k">ID</span><span class="v">${escapeHtml(detail.id)}</span></div>
                <div class="row"><span class="k">描述</span><span class="v">${escapeHtml(detail.description || '（无）')}</span></div>
                <div class="row"><span class="k">版本</span><span class="v">${escapeHtml(detail.version || '（未标注）')}</span></div>
                <div class="row"><span class="k">许可证</span><span class="v">${escapeHtml(detail.license || '（未标注）')}</span></div>
                ${install.repo_url ? `<div class="row"><span class="k">来源</span><span class="v"><a href="${escapeHtml(install.repo_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(install.repo_url)}</a></span></div>
                <div class="row"><span class="k">提交</span><span class="v"><code>${escapeHtml(String(install.commit_sha).slice(0, 12))}</code>（${new Date(install.installed_at || 0).toLocaleString('zh-CN', { hour12: false })} 安装）</span></div>` : ''}
                ${Object.entries(detail.metadata || {}).slice(0, 8).map(([key, value]) => `<div class="row"><span class="k">${escapeHtml(key)}</span><span class="v">${escapeHtml(String(value))}</span></div>`).join('')}
            </div>
            <div class="skill-form-label" style="margin-top:12px;">SKILL.md 正文</div>
            <pre class="skill-detail-pre">${escapeHtml(detail.body || '（空）')}</pre>
            <div class="skill-filelist">${(detail.file_list || []).length} 个文件：<br>${files || '（无）'}</div>`;
    } catch (error) {
        body.innerHTML = `<div class="gh-confirm-box">加载失败：${escapeHtml(error.message)}</div>`;
    }
    openOverlay('skillDetailOverlay');
}

function openEditor(item) {
    editingId = item ? item.id : '';
    editBaseSha = '';
    const saveBtn = document.getElementById('skillEditSave');
    // Never allow a save while GET detail is still in flight: it could write
    // an empty editor over an existing SKILL.md.
    saveBtn.disabled = Boolean(item);
    document.getElementById('skillEditTitle').textContent = item ? `编辑：${item.name}` : '新建 Skill';
    document.getElementById('skillEditNameRow').style.display = item ? 'none' : '';
    document.getElementById('skillEditDescRow').style.display = item ? 'none' : '';
    document.getElementById('skillEditNameHint').style.display = item ? 'none' : '';
    document.getElementById('skillEditContentHint').textContent = item ? '保存会整体替换 SKILL.md 正文（frontmatter 之后的全部内容）。' : '';
    document.getElementById('skillEditName').value = '';
    document.getElementById('skillEditDesc').value = '';
    document.getElementById('skillEditContent').value = '';
    document.getElementById('skillVariantsList').innerHTML = '';
    openOverlay('skillEditOverlay');
    if (item) {
        const openingId = editingId;
        api(`/api/skills/custom/${encodeURIComponent(item.id)}`).then(detail => {
            if (editingId !== openingId) return;
            editBaseSha = detail.content_sha256 || '';
            if (!/^[0-9a-f]{64}$/.test(editBaseSha)) throw new Error('未取得 Skill 内容版本，无法安全保存');
            document.getElementById('skillEditContent').value = detail.body || '';
            (detail.variants || []).forEach(v => addVariantRow(v.label || '', v.prompt || '', v.id || ''));
            saveBtn.disabled = false;
        }).catch(error => toast(error.message));
    }
}
function addVariantRow(label = '', prompt = '', id = '') {
    const list = document.getElementById('skillVariantsList');
    const row = document.createElement('div');
    row.className = 'skill-variant-row';
    // Keep the immutable ID even when the visible label changes.
    row.dataset.variantId = String(id || '');
    row.innerHTML = `
        <input class="skill-input v-label" type="text" maxlength="80" placeholder="样板名（如：单墨 · 钴蓝）" value="${escapeHtml(label)}">
        <input class="skill-input v-prompt" type="text" maxlength="2000" placeholder="该样板的追加指令（墨色/纹理/构图约束）" value="${escapeHtml(prompt)}">
        <button class="skill-mini-btn danger v-del" type="button">删</button>`;
    row.querySelector('.v-del').onclick = () => row.remove();
    list.appendChild(row);
}
function collectVariants() {
    return [...document.querySelectorAll('#skillVariantsList .skill-variant-row')].map(row => ({
        id: row.dataset.variantId || '',
        label: row.querySelector('.v-label').value.trim(),
        prompt: row.querySelector('.v-prompt').value.trim(),
    })).filter(v => v.label);
}

async function saveEditor() {
    const content = document.getElementById('skillEditContent').value;
    const saveBtn = document.getElementById('skillEditSave');
    saveBtn.disabled = true;
    try {
        const variants = collectVariants();
        if (editingId) {
            if (!/^[0-9a-f]{64}$/.test(editBaseSha)) throw new Error('缺少内容版本，请重新打开编辑器');
            await api(`/api/skills/custom/${encodeURIComponent(editingId)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content, variants, content_format: 'body', base_sha256: editBaseSha }) });
            toast('已保存');
        } else {
            const name = document.getElementById('skillEditName').value.trim();
            const description = document.getElementById('skillEditDesc').value.trim();
            if (!name) { toast('请填写名称'); return; }
            const created = await api('/api/skills/custom', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, description, content, variants }) });
            editingId = created.id;
            toast(`已创建：${created.id}`);
        }
        closeOverlay('skillEditOverlay');
        await loadSkills();
    } catch (error) {
        toast(error.message || '保存失败');
    } finally {
        saveBtn.disabled = false;
    }
}

async function deleteSkill(item) {
    if (!confirm(`确定删除 Skill「${item.name}」（${item.id}）？该操作不可恢复。`)) return;
    try {
        await api(`/api/skills/custom/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
        toast('已删除');
        await loadSkills();
    } catch (error) {
        toast(error.message || '删除失败');
    }
}

function resetGithubOverlay() {
    ghPreview = null;
    document.getElementById('ghStepUrl').hidden = false;
    document.getElementById('ghStepConfirm').hidden = true;
    document.getElementById('ghOverwriteRow').hidden = true;
    document.getElementById('ghOverwrite').checked = false;
    document.getElementById('ghConfirmBox').innerHTML = '';
    document.getElementById('ghInstallName').value = '';
}

async function githubPreview() {
    const url = document.getElementById('ghUrl').value.trim();
    if (!url) { toast('请填写仓库地址'); return; }
    const ref = document.getElementById('ghRef').value.trim();
    const subdir = document.getElementById('ghSubdir').value.trim();
    const previewBtn = document.getElementById('ghPreviewBtn');
    previewBtn.disabled = true;
    setStatus('正在获取仓库预览…');
    try {
        ghPreview = await api('/api/skills/github/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, ref, subdir }) });
        const skill = ghPreview.skill || {};
        const repo = ghPreview.repo || {};
        const warnings = (skill.warnings || []).map(w => `<div class="row"><span class="v warnline">⚠ ${escapeHtml(w)}</span></div>`).join('');
        document.getElementById('ghConfirmBox').innerHTML = `
            <div class="row"><span class="k">Skill</span><span class="v"><b>${escapeHtml(skill.name || '')}</b>（将安装为 <code>${escapeHtml(skill.id || '')}</code>）</span></div>
            <div class="row"><span class="k">描述</span><span class="v">${escapeHtml(skill.description || '（无）')}</span></div>
            <div class="row"><span class="k">版本 / 许可</span><span class="v">${escapeHtml(skill.version || '未标注')} / ${escapeHtml(skill.license || '未标注')}</span></div>
            <div class="row"><span class="k">仓库</span><span class="v">${escapeHtml(repo.owner || '')}/${escapeHtml(repo.repo || '')} · 分支 <code>${escapeHtml(repo.ref || '')}</code></span></div>
            <div class="row"><span class="k">固定提交</span><span class="v"><code>${escapeHtml(String(repo.sha || '').slice(0, 12))}</code> ${escapeHtml(repo.commit_message || '')}</span></div>
            <div class="row"><span class="k">内容</span><span class="v">${skill.files || 0} 个文件 · ${formatBytes(skill.total_bytes)} · 参考 ${skill.references_count || 0} · 素材 ${skill.assets_count || 0}</span></div>
            ${skill_root_row()}
            ${warnings}`;
        function skill_root_row() {
            return ghPreview.skill_root ? `<div class="row"><span class="k">子目录</span><span class="v">${escapeHtml(ghPreview.skill_root)}</span></div>` : '';
        }
        document.getElementById('ghInstallName').value = skill.id || '';
        document.getElementById('ghStepUrl').hidden = true;
        document.getElementById('ghStepConfirm').hidden = false;
        setStatus('请确认后安装');
    } catch (error) {
        setStatus('获取失败');
        toast(error.message || '获取预览失败');
    } finally {
        previewBtn.disabled = false;
    }
}

async function githubInstall() {
    if (!ghPreview) return;
    const url = document.getElementById('ghUrl').value.trim();
    const name = document.getElementById('ghInstallName').value.trim();
    const overwrite = document.getElementById('ghOverwrite').checked;
    const installBtn = document.getElementById('ghInstallBtn');
    installBtn.disabled = true;
    setStatus('正在安装…');
    try {
        const result = await api('/api/skills/github/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url, sha: ghPreview.repo.sha,
                tracking_ref: ghPreview.repo.ref || document.getElementById('ghRef').value.trim(),
                name, overwrite, subdir: document.getElementById('ghSubdir').value.trim()
            }),
        });
        const warnings = result.warnings || [];
        toast(`安装成功：${result.id}` + (warnings.length ? `（${warnings[0]}）` : ''), 4200);
        closeOverlay('skillGithubOverlay');
        activeSource = 'custom';
        syncTabs();
        await loadSkills();
    } catch (error) {
        if (error.statusCode === 409) {
            document.getElementById('ghOverwriteRow').hidden = false;
            toast(error.message, 4600);
        } else {
            toast(error.message || '安装失败', 4600);
        }
        setStatus('安装失败');
    } finally {
        installBtn.disabled = false;
    }
}

async function checkUpdate(item) {
    setStatus('正在检查更新…');
    openOverlay('skillUpdateOverlay');
    const box = document.getElementById('skillUpdateBox');
    const upgradeBtn = document.getElementById('skillUpgradeBtn');
    upgradeBtn.hidden = true;
    try {
        const data = await api(`/api/skills/custom/${encodeURIComponent(item.id)}/check-update`);
        const install = item.install || {};
        box.innerHTML = `
            <div class="row"><span class="k">当前版本</span><span class="v"><code>${escapeHtml(String(data.current_sha).slice(0, 12))}</code></span></div>
            <div class="row"><span class="k">远端最新</span><span class="v"><code>${escapeHtml(String(data.latest_sha).slice(0, 12))}</code> ${escapeHtml(data.latest_commit_message || '')}</span></div>
            <div class="row"><span class="k">状态</span><span class="v">${data.up_to_date ? '✅ 已是最新' : '⬆️ 有可用更新'}</span></div>
            <div class="row"><span class="k">仓库</span><span class="v"><a href="${escapeHtml(data.repo_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(data.repo_url)}</a></span></div>`;
        upgradeBtn.hidden = data.up_to_date;
        upgradeBtn.dataset.id = item.id;
        setStatus(data.up_to_date ? '已是最新' : '有可用更新');
    } catch (error) {
        box.innerHTML = `<div class="row"><span class="v">检查失败：${escapeHtml(error.message)}</span></div>`;
        setStatus('检查失败');
    }
}

async function upgradeSkill(id) {
    const upgradeBtn = document.getElementById('skillUpgradeBtn');
    upgradeBtn.disabled = true;
    setStatus('正在升级…');
    try {
        const result = await api(`/api/skills/custom/${encodeURIComponent(id)}/upgrade`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
        const warnings = result.warnings || [];
        toast(`已升级到 ${String(result.sha).slice(0, 10)}` + (warnings.length ? `（${warnings[0]}）` : ''), 4600);
        closeOverlay('skillUpdateOverlay');
        await loadSkills();
    } catch (error) {
        toast(error.message || '升级失败', 4600);
        setStatus('升级失败');
    } finally {
        upgradeBtn.disabled = false;
    }
}

async function installZip(file, overwrite) {
    setStatus('正在上传安装…');
    const form = new FormData();
    form.append('file', file);
    if (overwrite) form.append('overwrite', 'true');
    try {
        const result = await api('/api/skills/zip/install', { method: 'POST', body: form });
        toast(`安装成功：${result.id}` + ((result.warnings || []).length ? `（${result.warnings[0]}）` : ''));
        activeSource = 'custom';
        syncTabs();
        await loadSkills();
    } catch (error) {
        if (error.statusCode === 409 && !overwrite && confirm(`${error.message}\n\n是否覆盖安装？`)) {
            return installZip(file, true);
        }
        toast(error.message || '导入失败', 4600);
        setStatus('导入失败');
    }
}

function syncTabs() {
    tabsEl.querySelectorAll('button').forEach(btn => btn.classList.toggle('active', btn.dataset.source === activeSource));
}

tabsEl.addEventListener('click', (event) => {
    const button = event.target.closest('[data-source]');
    if (!button) return;
    activeSource = button.dataset.source;
    syncTabs();
    renderGrid();
});

document.getElementById('skillRefreshBtn').addEventListener('click', loadSkills);
document.getElementById('skillCreateBtn').addEventListener('click', () => openEditor(null));
document.getElementById('skillGithubBtn').addEventListener('click', () => { resetGithubOverlay(); openOverlay('skillGithubOverlay'); });
document.getElementById('skillZipBtn').addEventListener('click', () => zipInput.click());
document.getElementById('skillEditSave').addEventListener('click', saveEditor);
document.getElementById('skillVariantAdd').addEventListener('click', () => addVariantRow());
document.getElementById('skillVariantAi').addEventListener('click', async () => {
    if (!editingId) { toast('请先保存 Skill 再使用 AI 识别'); return; }
    const btn = document.getElementById('skillVariantAi');
    const hint = document.getElementById('skillVariantAiHint');
    btn.disabled = true;
    hint.textContent = 'AI 正在分析该 Skill 的可用样式（免费 LLM 通道，约 10-30 秒）…';
    try {
        const data = await api(`/api/skills/custom/${encodeURIComponent(editingId)}/suggest-variants`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: 'custom', id: editingId, provider: 'codex' }) });
        const suggestions = data.suggestions || [];
        if (!suggestions.length) { hint.textContent = 'AI 未识别到可枚举的样式样板。'; return; }
        const existing = new Set([...document.querySelectorAll('#skillVariantsList .v-label')].map(i => i.value.trim()));
        suggestions.forEach(v => { if (!existing.has(v.label)) addVariantRow(v.label, v.prompt); });
        hint.textContent = `AI 识别到 ${suggestions.length} 个样板，已填入（可删改后保存）`;
    } catch (error) {
        hint.textContent = '识别失败：' + (error.message || '').slice(0, 120);
    } finally {
        btn.disabled = false;
    }
});
document.getElementById('ghPreviewBtn').addEventListener('click', githubPreview);
document.getElementById('ghInstallBtn').addEventListener('click', githubInstall);
document.getElementById('ghBackBtn').addEventListener('click', () => { document.getElementById('ghStepUrl').hidden = false; document.getElementById('ghStepConfirm').hidden = true; });
document.getElementById('skillUpgradeBtn').addEventListener('click', () => upgradeSkill(document.getElementById('skillUpgradeBtn').dataset.id));
zipInput.addEventListener('change', () => {
    const file = zipInput.files && zipInput.files[0];
    zipInput.value = '';
    if (file) installZip(file, false);
});
document.querySelectorAll('[data-close]').forEach(btn => btn.addEventListener('click', () => closeOverlay(btn.dataset.close)));
document.querySelectorAll('.skill-overlay').forEach(overlay => overlay.addEventListener('mousedown', (event) => {
    if (event.target === overlay) overlay.hidden = true;
}));

loadSkills();
refreshIcons();
