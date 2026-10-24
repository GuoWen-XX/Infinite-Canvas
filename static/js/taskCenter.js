/* Task Center panel: recent generation tasks + cost summary. */
(function(){
  let panel = null;
  let open = false;

  function getLang() {
    try {
      return localStorage.getItem('studio_lang') || 'zh';
    } catch(e) {
      return 'zh';
    }
  }

  function t(zh, en) {
    return getLang() === 'en' ? en : zh;
  }

  function fmtTime(ts){
    const d = new Date(Number(ts)||0);
    const locale = getLang() === 'en' ? 'en-US' : 'zh-CN';
    return d.toLocaleString(locale, {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
  }

  function fmtMs(ms){
    const s = Math.round((Number(ms)||0)/1000);
    return s >= 60 ? Math.floor(s/60)+'m '+(s%60)+'s' : s+'s';
  }

  function fmtDuration(ms){
    const num = Number(ms) || 0;
    if(num <= 0) return '-';
    if(num < 1000) return num + 'ms';
    const s = (num / 1000).toFixed(1);
    return s + 's';
  }

  function esc(s){
    return String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  async function load(){
    if (!panel) return;
    const listEl = panel.querySelector('.tc-list');
    const statsEl = panel.querySelector('.tc-stats');
    listEl.innerHTML = '<div class="tc-loading">' + esc(t('加载中...', 'Loading...')) + '</div>';
    statsEl.innerHTML = '';
    try {
      const [hist, stats] = await Promise.all([
        fetch('/api/task-history?limit=100').then(r=>r.json()),
        fetch('/api/task-stats?days=7').then(r=>r.json())
      ]);
      // 端点响应时延列表
      const speedList = (stats.endpoint_speeds || []).filter(s => (s.latest_duration_ms || 0) > 0);
      let speedBlock = '';
      if(speedList.length > 0){
        const speedRows = speedList.map(s => {
          const ok = s.status === 'success';
          const durStr = fmtDuration(s.latest_duration_ms);
          return '<div class="tc-speed-row">' +
            '<div class="tc-speed-info">' +
              '<span class="tc-badge ' + (ok ? 'tc-badge-ok' : 'tc-badge-err') + '">' + (ok ? 'OK' : 'ERR') + '</span>' +
              '<span class="tc-speed-prov">' + esc(s.provider) + '</span>' +
              (s.model ? '<span class="tc-speed-model" title="' + esc(s.model) + '">' + esc(s.model) + '</span>' : '') +
            '</div>' +
            '<div class="tc-speed-metrics">' +
              '<span class="tc-speed-val">' + durStr + '</span>' +
            '</div>' +
          '</div>';
        }).join('');
        speedBlock = '<div class="tc-speed-section">' +
          '<div class="tc-speed-title">' + esc(t('端点响应速度 (最近测试/生成):', 'Endpoint Speeds (Recent):')) + '</div>' +
          '<div class="tc-speed-grid">' + speedRows + '</div>' +
        '</div>';
      }

      // stats
      const total = Number(stats.total_cost)||0;
      const countSuffix = t(' 次', ' runs');
      const provLines = (stats.providers||[]).map(p =>
        '<div class="tc-stat-row"><span>'+esc(p.provider)+'</span><span>'+p.count+countSuffix+'</span><span>'+(p.cost?('\u00a5'+Number(p.cost).toFixed(2)):'-')+'</span></div>').join('');
      statsEl.innerHTML =
        speedBlock +
        '<div class="tc-stat-total">'+esc(t('7 天合计花费: ', '7-Day Total: '))+'<b>'+(total>0?('\u00a5'+total.toFixed(2)):'\u2248\u00a50')+'</b></div>' +
        (provLines ? '<div class="tc-stat-provs">'+provLines+'</div>' : '');
      // tasks
      const outLabel = t('查看结果', 'View Output');
      const rows = (hist.tasks||[]).map(t => {
        const ok = t.status === 'success';
        const rawUrl = (t.outputs && t.outputs.length) ? String(t.outputs[0] || '').trim() : '';
        const isSafeUrl = /^(https?:\/\/|\/assets\/|\/output\/)/i.test(rawUrl);
        const out = isSafeUrl ? ('<a class="tc-out" href="'+esc(rawUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(outLabel)+'</a>') : '';
        const costStr = (t.cost !== null && t.cost !== undefined && !isNaN(Number(t.cost))) ? ('\u00a5' + Number(t.cost).toFixed(2)) : '-';
        return '<div class="tc-row '+(ok?'ok':'fail')+'">'+
          '<div class="tc-row-main">'+
            '<span class="tc-badge '+(ok?'tc-badge-ok':'tc-badge-err')+'">'+(ok?'OK':'ERR')+'</span>'+
            '<span class="tc-provider">'+esc(t.provider)+'</span>'+
            '<span class="tc-model" title="'+esc(t.model)+'">'+esc(t.model)+'</span>'+
          '</div>'+
          '<div class="tc-row-sub">'+
            '<span>'+fmtTime(t.ts)+'</span><span>'+fmtMs(t.duration_ms)+'</span><span>'+esc(costStr)+'</span>'+
            (t.task_id?('<span class="tc-tid" title="'+esc(t.task_id)+'">ID:'+esc(String(t.task_id).slice(-8))+'</span>'):'')+
            out+
          '</div>'+
          (t.error?('<div class="tc-err" title="'+esc(t.error)+'">'+esc(t.error)+'</div>'):'')+
        '</div>';
      }).join('');
      listEl.innerHTML = rows || '<div class="tc-empty">'+esc(t('还没有生成任务记录', 'No task history yet'))+'</div>';
    } catch (e) {
      listEl.innerHTML = '<div class="tc-empty">'+esc(t('加载失败: ', 'Failed to load: '))+esc(e.message||e)+'</div>';
    }
  }

  function ensureStyles(){
    if(document.getElementById('tc-panel-styles')) return;
    const style = document.createElement('style');
    style.id = 'tc-panel-styles';
    style.textContent = `
      .tc-panel {
        position: fixed; top: 60px; right: 16px; width: 440px; max-height: calc(100vh - 84px);
        display: none; flex-direction: column; z-index: 99999;
        background: #fffdf9;
        border: 1px solid rgba(60, 50, 40, 0.12); border-radius: 16px;
        box-shadow: 0 16px 48px rgba(60, 50, 40, 0.14); color: #2a2520;
        font-family: "Montserrat", "Space Grotesk", "Source Han Sans SC", "思源黑体 Medium", "思源黑体", -apple-system, sans-serif;
        font-size: 12px; letter-spacing: 0.01em; overflow: hidden;
      }
      .tc-panel.open { display: flex; }
      .tc-head { display: flex; align-items: center; gap: 8px; padding: 13px 18px; border-bottom: 1px solid rgba(60, 50, 40, 0.08); background: #f5f1ea; }
      .tc-title { font-weight: 700; font-size: 14px; color: #2a2520; letter-spacing: 0.02em; }
      .tc-sub { color: #8a8278; font-size: 11px; flex: 1; }
      .tc-refresh, .tc-close { background: none; border: none; color: #8a8278; cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 8px; transition: background 0.15s, color 0.15s; }
      .tc-refresh:hover, .tc-close:hover { color: #2a2520; background: rgba(60, 50, 40, 0.07); }
      .tc-stats { padding: 12px 18px; border-bottom: 1px solid rgba(60, 50, 40, 0.08); background: #f5f1ea; }
      .tc-speed-section { margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px dashed rgba(60, 50, 40, 0.12); }
      .tc-speed-title { font-size: 11px; font-weight: 700; color: #73695f; margin-bottom: 6px; letter-spacing: 0.02em; }
      .tc-speed-grid { display: flex; flex-direction: column; gap: 4px; }
      .tc-speed-row { display: flex; align-items: center; justify-content: space-between; padding: 2px 0; font-size: 11px; }
      .tc-speed-info { display: flex; align-items: center; gap: 6px; min-width: 0; flex: 1; }
      .tc-speed-prov { font-weight: 600; color: #c97b5a; white-space: nowrap; }
      .tc-speed-model { color: #8a8278; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 140px; }
      .tc-speed-metrics { display: flex; align-items: center; gap: 6px; }
      .tc-speed-val { font-family: monospace; font-weight: 700; color: #2a2520; font-size: 11px; }
      .tc-stat-total { margin-bottom: 6px; font-size: 12px; color: #2a2520; }
      .tc-stat-total b { color: #c97b5a; font-size: 15px; margin-left: 4px; font-weight: 700; }
      .tc-stat-provs { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
      .tc-stat-row { display: flex; justify-content: space-between; color: #73695f; padding: 3px 0; font-size: 11px; border-bottom: 1px solid rgba(60, 50, 40, 0.05); }
      .tc-list { overflow-y: auto; padding: 10px 18px 18px; max-height: calc(100vh - 240px); }
      .tc-row { padding: 10px 0; border-bottom: 1px dashed rgba(60, 50, 40, 0.12); }
      .tc-row-main { display: flex; align-items: center; gap: 8px; }
      .tc-badge { display: inline-flex; align-items: center; justify-content: center; font-size: 9.5px; font-weight: 700; letter-spacing: 0.04em; padding: 1px 5px; border-radius: 4px; font-family: monospace; }
      .tc-badge-ok { background: rgba(201, 123, 90, 0.12); color: #c97b5a; border: 1px solid rgba(201, 123, 90, 0.25); }
      .tc-badge-err { background: rgba(220, 38, 38, 0.1); color: #dc2626; border: 1px solid rgba(220, 38, 38, 0.2); }
      .tc-provider { color: #c97b5a; font-weight: 600; font-size: 12px; }
      .tc-model { color: #2a2520; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; font-size: 11px; }
      .tc-row-sub { display: flex; gap: 12px; color: #8a8278; margin-top: 4px; font-size: 11px; }
      .tc-tid { color: #a89f93; font-family: monospace; }
      .tc-out { color: #059669; text-decoration: none; font-weight: 600; }
      .tc-out:hover { text-decoration: underline; }
      .tc-err { margin-top: 4px; color: #dc2626; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .tc-empty, .tc-loading { color: #8a8278; text-align: center; padding: 24px 0; font-size: 13px; }

      /* 暗色模式适配 */
      body.theme-dark .tc-panel,
      html.theme-dark .tc-panel,
      body.studio-theme-dark .tc-panel,
      html.studio-theme-dark .tc-panel {
        background: rgba(22, 24, 29, 0.96);
        border: 1px solid rgba(255, 255, 255, 0.12);
        box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
        color: #dfe3e8;
      }
      body.theme-dark .tc-head,
      html.theme-dark .tc-head,
      body.studio-theme-dark .tc-head,
      html.studio-theme-dark .tc-head {
        background: rgba(255, 255, 255, 0.02);
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      }
      body.theme-dark .tc-title,
      html.theme-dark .tc-title,
      body.studio-theme-dark .tc-title,
      html.studio-theme-dark .tc-title {
        color: #fff;
      }
      body.theme-dark .tc-sub,
      html.theme-dark .tc-sub,
      body.studio-theme-dark .tc-sub,
      html.studio-theme-dark .tc-sub {
        color: #8fa0b3;
      }
      body.theme-dark .tc-refresh,
      html.theme-dark .tc-refresh,
      body.theme-dark .tc-close,
      html.theme-dark .tc-close,
      body.studio-theme-dark .tc-refresh,
      html.studio-theme-dark .tc-refresh,
      body.studio-theme-dark .tc-close,
      html.studio-theme-dark .tc-close {
        color: #9aa5b1;
      }
      body.theme-dark .tc-refresh:hover,
      html.theme-dark .tc-refresh:hover,
      body.theme-dark .tc-close:hover,
      html.theme-dark .tc-close:hover,
      body.studio-theme-dark .tc-refresh:hover,
      html.studio-theme-dark .tc-refresh:hover,
      body.studio-theme-dark .tc-close:hover,
      html.studio-theme-dark .tc-close:hover {
        color: #fff;
        background: rgba(255, 255, 255, 0.1);
      }
      body.theme-dark .tc-stats,
      html.theme-dark .tc-stats,
      body.studio-theme-dark .tc-stats,
      html.studio-theme-dark .tc-stats {
        background: rgba(255, 255, 255, 0.01);
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      }
      body.theme-dark .tc-speed-section,
      html.theme-dark .tc-speed-section,
      body.studio-theme-dark .tc-speed-section,
      html.studio-theme-dark .tc-speed-section {
        border-bottom: 1px dashed rgba(255, 255, 255, 0.08);
      }
      body.theme-dark .tc-speed-title,
      html.theme-dark .tc-speed-title,
      body.studio-theme-dark .tc-speed-title,
      html.studio-theme-dark .tc-speed-title {
        color: #8fa0b3;
      }
      body.theme-dark .tc-speed-model,
      html.theme-dark .tc-speed-model,
      body.studio-theme-dark .tc-speed-model,
      html.studio-theme-dark .tc-speed-model {
        color: #8a94a0;
      }
      body.theme-dark .tc-speed-val,
      html.theme-dark .tc-speed-val,
      body.studio-theme-dark .tc-speed-val,
      html.studio-theme-dark .tc-speed-val {
        color: #dfe3e8;
      }
      body.theme-dark .tc-stat-total,
      html.theme-dark .tc-stat-total,
      body.studio-theme-dark .tc-stat-total,
      html.studio-theme-dark .tc-stat-total {
        color: #cfd6dd;
      }
      body.theme-dark .tc-stat-total b,
      html.theme-dark .tc-stat-total b,
      body.studio-theme-dark .tc-stat-total b,
      html.studio-theme-dark .tc-stat-total b {
        color: #7fd18a;
      }
      body.theme-dark .tc-stat-row,
      html.theme-dark .tc-stat-row,
      body.studio-theme-dark .tc-stat-row,
      html.studio-theme-dark .tc-stat-row {
        color: #aab4bf;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      }
      body.theme-dark .tc-row,
      html.theme-dark .tc-row,
      body.studio-theme-dark .tc-row,
      html.studio-theme-dark .tc-row {
        border-bottom: 1px dashed rgba(255, 255, 255, 0.08);
      }
      body.theme-dark .tc-provider,
      html.theme-dark .tc-provider,
      body.studio-theme-dark .tc-provider,
      html.studio-theme-dark .tc-provider {
        color: #7fb0e8;
      }
      body.theme-dark .tc-model,
      html.theme-dark .tc-model,
      body.studio-theme-dark .tc-model,
      html.studio-theme-dark .tc-model {
        color: #cfd6dd;
      }
      body.theme-dark .tc-row-sub,
      html.theme-dark .tc-row-sub,
      body.studio-theme-dark .tc-row-sub,
      html.studio-theme-dark .tc-row-sub {
        color: #8a94a0;
      }
      body.theme-dark .tc-tid,
      html.theme-dark .tc-tid,
      body.studio-theme-dark .tc-tid,
      html.studio-theme-dark .tc-tid {
        color: #6f7a86;
      }
      body.theme-dark .tc-out,
      html.theme-dark .tc-out,
      body.studio-theme-dark .tc-out,
      html.studio-theme-dark .tc-out {
        color: #7fd18a;
      }
      body.theme-dark .tc-err,
      html.theme-dark .tc-err,
      body.studio-theme-dark .tc-err,
      html.studio-theme-dark .tc-err {
        color: #e08585;
      }
      body.theme-dark .tc-empty,
      html.theme-dark .tc-empty,
      body.theme-dark .tc-loading,
      html.theme-dark .tc-loading,
      body.studio-theme-dark .tc-empty,
      html.studio-theme-dark .tc-empty,
      body.studio-theme-dark .tc-loading,
      html.studio-theme-dark .tc-loading {
        color: #8a94a0;
      }
    `;
    document.head.appendChild(style);
  }

  function updateTexts(){
    if(!panel) return;
    const titleEl = panel.querySelector('.tc-title');
    const subEl = panel.querySelector('.tc-sub');
    const refBtn = panel.querySelector('.tc-refresh');
    const clsBtn = panel.querySelector('.tc-close');
    if(titleEl) titleEl.textContent = t('任务中心', 'Task Center');
    if(subEl) subEl.textContent = t('生成记录 · 费用台账', 'Task History & Costs');
    if(refBtn) refBtn.title = t('刷新', 'Refresh');
    if(clsBtn) clsBtn.title = t('关闭', 'Close');
  }

  function build(){
    ensureStyles();
    panel = document.createElement('div');
    panel.className = 'tc-panel';
    panel.innerHTML =
      '<div class="tc-head">'+
        '<span class="tc-title">' + esc(t('任务中心', 'Task Center')) + '</span>'+
        '<span class="tc-sub">' + esc(t('生成记录 · 费用台账', 'Task History & Costs')) + '</span>'+
        '<button class="tc-refresh" title="' + esc(t('刷新', 'Refresh')) + '">\u21bb</button>'+
        '<button class="tc-close" title="' + esc(t('关闭', 'Close')) + '">\u00d7</button>'+
      '</div>'+
      '<div class="tc-stats"></div>'+
      '<div class="tc-list"></div>';
    document.body.appendChild(panel);
    panel.querySelector('.tc-close').onclick = () => toggle(false);
    panel.querySelector('.tc-refresh').onclick = load;
    panel.addEventListener('mousedown', e => e.stopPropagation());
  }

  function toggle(force){
    const next = typeof force === 'boolean' ? force : !open;
    if (next && !panel) build();
    open = next;
    if (panel) {
      panel.classList.toggle('open', open);
      updateTexts();
    }
    if (open) load();
  }

  window.addEventListener('studio-lang-change', () => {
    updateTexts();
    if (open) load();
  });

  window.toggleTaskCenter = toggle;
})();

