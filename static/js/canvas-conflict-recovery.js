(function(global){
'use strict';
const PREFIX = 'canvas_conflict_draft_';
const META_PREFIX = 'canvas_meta_conflict_';
function canvasFromDraft(record){
    if(!record || typeof record !== 'object') throw new Error('Missing conflict draft');
    const source = record.canvas && typeof record.canvas === 'object' ? record.canvas : record;
    if(!Array.isArray(source.nodes)) throw new Error('Conflict draft has no nodes');
    return source;
}
function copyPayload(record, kind){
    const source = canvasFromDraft(record);
    return {
        title: String(source.title || '未命名画布') + '（冲突恢复副本）',
        icon: source.icon || (kind === 'smart' ? 'sparkles' : 'layers'),
        kind: kind === 'smart' ? 'smart' : 'classic',
        project: source.project || record.project || 'default'
    };
}
async function createIndependentCopy(record, kind, request=global.fetch.bind(global)){
    const source = canvasFromDraft(record);
    const meta = copyPayload(record, kind);
    const createdResponse = await request('/api/canvases', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(meta)
    });
    if(!createdResponse.ok) throw new Error('创建恢复副本失败');
    const created = (await createdResponse.json()).canvas;
    if(!created || !created.id) throw new Error('恢复副本未返回有效 ID');
    // A new canvas has its own ID and revision; the conflicted original is never PUT.
    const body = {
        title:meta.title, icon:meta.icon,
        nodes:source.nodes, connections:source.connections || [],
        viewport:source.viewport || {x:0,y:0,scale:1},
        logs:source.logs || [], settings:source.settings || {},
        base_revision:Number(created.revision || 0)
    };
    const savedResponse = await request('/api/canvases/' + encodeURIComponent(created.id), {
        method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    if(!savedResponse.ok) {
        throw new Error('副本已创建，但写入内容失败；原草稿仍保留，请勿删除');
    }
    return {id:created.id, kind:meta.kind};
}
async function applyMetadataAfterConfirmation(id, patch, request=global.fetch.bind(global)){
    if(!id || !patch || typeof patch !== 'object') throw new Error('Invalid metadata recovery');
    const latest = await request('/api/canvases/' + encodeURIComponent(id));
    if(!latest.ok) throw new Error('无法读取服务器最新版本');
    const remote = (await latest.json()).canvas;
    if(!remote || remote.revision == null) throw new Error('服务器缺少 revision，拒绝覆盖');
    const response = await request('/api/canvases/' + encodeURIComponent(id) + '/meta', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...patch, base_revision:Number(remote.revision)})
    });
    if(response.status === 409) throw new Error('再次发生版本冲突，修改仍保留在本地');
    if(!response.ok) throw new Error('保存修改失败，本地草稿仍保留');
    return (await response.json()).canvas;
}
function button(text, handler){
    const el = document.createElement('button');
    el.type = 'button'; el.textContent = text;
    el.style.cssText = 'padding:7px 11px;border:1px solid #999;border-radius:7px;background:#fff;color:#222;cursor:pointer;font-size:13px';
    el.addEventListener('click', handler);
    return el;
}
function show({id,kind='classic',record,storageKey}){
    if(!id || !record || !global.document) return false;
    const key = storageKey || PREFIX + id;
    const previous = document.getElementById('canvas-conflict-recovery');
    if(previous) previous.remove();
    const panel = document.createElement('section');
    panel.id = 'canvas-conflict-recovery';
    panel.setAttribute('role','region');
    panel.setAttribute('aria-label','画布冲突恢复');
    panel.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:2147483000;max-width:min(460px,calc(100vw - 40px));box-sizing:border-box;padding:16px;border:2px solid #e2a24b;border-radius:12px;background:#fff9ec;color:#29251f;box-shadow:0 8px 32px #0004;font:14px/1.5 sans-serif';
    const title = document.createElement('strong');
    title.textContent = '画布保存冲突：未覆盖服务器内容';
    const description = document.createElement('p');
    description.textContent = '可导出本地草稿，或保存为新的独立画布；原画布不会被自动覆盖。请核对两份内容后再整理。';
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px';
    const status = document.createElement('p');
    status.setAttribute('aria-live','polite');
    status.style.cssText = 'margin:8px 0 0;word-break:break-word';
    actions.append(button('导出本地草稿 JSON', () => {
        try {
            const blob = new Blob([JSON.stringify(record,null,2)], {type:'application/json'});
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url; link.download = 'canvas-conflict-' + String(id).replace(/[^a-zA-Z0-9_-]/g,'_') + '.json';
            document.body.append(link); link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 30000);
            status.textContent = '本地草稿已导出；请妥善保存文件。';
        } catch(err) { status.textContent = '导出失败：' + err.message; }
    }));
    const saveButton = button('保存为独立副本', async () => {
        saveButton.disabled = true;
        status.textContent = '正在创建独立副本…';
        try {
            const copy = await createIndependentCopy(record, kind);
            const link = document.createElement('a');
            link.href = '/static/' + (copy.kind === 'smart' ? 'smart-canvas' : 'canvas') + '.html?id=' + encodeURIComponent(copy.id);
            link.target = '_blank'; link.rel = 'noopener noreferrer';
            link.textContent = '打开已保存的恢复副本';
            status.textContent = '副本保存成功。原画布与本地草稿均未删除。 ';
            status.append(link);
        } catch(err) { status.textContent = err.message; }
        finally { saveButton.disabled = false; }
    });
    actions.append(saveButton);
    const remoteLink = document.createElement('a');
    remoteLink.href = '/static/' + (kind === 'smart' ? 'smart-canvas' : 'canvas') + '.html?id=' + encodeURIComponent(id);
    remoteLink.target = '_blank'; remoteLink.rel = 'noopener noreferrer';
    remoteLink.textContent = '在新标签页查看服务器版本';
    remoteLink.style.cssText = 'display:inline-block;padding:7px 0';
    actions.append(remoteLink);
    actions.append(button('收起', () => { description.hidden = true; actions.hidden = true; status.hidden = true; title.style.cursor = 'pointer'; title.textContent = '有未处理的画布冲突 · 点击展开'; title.onclick = () => {description.hidden = false;actions.hidden = false;status.hidden = false;title.textContent = '画布保存冲突：未覆盖服务器内容';};}));
    panel.append(title,description,actions,status);
    document.body.append(panel);
    return true;
}
function showSaved(id,kind){
    let record;
    try { record = JSON.parse(global.localStorage.getItem(PREFIX + id) || 'null'); }
    catch(_) { return false; }
    return record ? show({id,kind,record}) : false;
}
function showMetadata({id,patch}){
    if(!id || !patch || !global.document) return false;
    const previous = document.getElementById('canvas-meta-recovery');
    if(previous) previous.remove();
    const panel = document.createElement('section');
    panel.id = 'canvas-meta-recovery';
    panel.style.cssText = 'position:fixed;bottom:20px;left:20px;z-index:2147483000;max-width:min(420px,calc(100vw - 40px));padding:14px;background:#fff9ec;color:#29251f;border:2px solid #e2a24b;border-radius:10px;box-shadow:0 8px 32px #0004;font:14px sans-serif';
    const title = document.createElement('strong');
    title.textContent = '画布属性修改冲突';
    const info = document.createElement('p');
    info.textContent = '本地修改：' + JSON.stringify(patch) + '。可明确选择在最新版本上重试；其他字段不会修改。';
    const status = document.createElement('p');
    status.setAttribute('aria-live','polite');
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap';
    const retry = button('确认应用此修改',async () => {
        retry.disabled = true;
        try {
            await applyMetadataAfterConfirmation(id,patch);
            try { global.localStorage.removeItem(META_PREFIX + id); } catch(_) {}
            status.textContent = '已应用修改，请刷新画布列表。';
        } catch(err) { status.textContent = err.message; }
        finally { retry.disabled = false; }
    });
    actions.append(retry,button('稍后处理',()=>panel.remove()));
    panel.append(title,info,actions,status);
    document.body.append(panel);
    return true;
}
function showSavedMetadata(id){
    try { const record=JSON.parse(global.localStorage.getItem(META_PREFIX + id) || 'null');return record?.patch ? showMetadata({id,patch:record.patch}) : false; }
    catch(_) { return false; }
}
global.CanvasConflictRecovery = {createIndependentCopy,applyMetadataAfterConfirmation,show,showSaved,showMetadata,showSavedMetadata,copyPayload};
})(window);
