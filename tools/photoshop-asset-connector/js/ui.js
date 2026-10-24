/* 下拉组件助手：统一用 UXP 原生 <sp-picker>（原生 <select> 不吃 CSS height，会留白/错位）。
 * 用 selectedIndex 作为取值真源（比 .value 在 UXP 里可靠），选项数组缓存在元素上。 */
window.DX = window.DX || {};
DX.ui = (function () {
  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // options: [{value,label}] 或 [string]；selectedValue 可选
  function fillPicker(picker, options, selectedValue) {
    const opts = (options || []).map((o) => (typeof o === 'object' ? { value: String(o.value), label: o.label } : { value: String(o), label: String(o) }));
    picker._options = opts;
    let idx = selectedValue != null ? opts.findIndex((o) => o.value === String(selectedValue)) : 0;
    if (idx < 0) idx = 0;
    // 关键：程序填充会让 sp-picker 触发 change 事件；这里上锁，避免 change 处理再次填充形成无限循环（→ 图片请求洪水把后端打挂）
    picker._suppress = true;
    const menu = picker.querySelector('sp-menu') || picker;
    menu.innerHTML = opts.map((o, i) =>
      `<sp-menu-item value="${esc(o.value)}"${i === idx && opts.length ? ' selected' : ''}>${esc(o.label)}</sp-menu-item>`).join('');
    const apply = () => { try { picker.selectedIndex = opts.length ? idx : -1; } catch (e) {} };
    apply();
    Promise.resolve().then(apply);          // 菜单项升级后再补一次选中态
    setTimeout(() => { picker._suppress = false; }, 80);  // 程序触发的 change 都落在这窗口内，统一忽略
  }

  function pickerValue(picker) {
    const opts = picker._options || [];
    const idx = picker.selectedIndex;
    if (idx != null && idx >= 0 && opts[idx]) return opts[idx].value;
    return opts[0] ? opts[0].value : '';
  }

  // 只在「用户真实选择」时回调；程序填充期间（_suppress）触发的 change 一律忽略
  function onPick(picker, cb) {
    picker.addEventListener('change', (e) => { if (picker._suppress) return; cb(e); });
  }

  // 生成页的参考图、工作流图片字段和结果共用资产页已验证的 JPEG/Base64 管线。
  function loadImagePreviews(root) {
    const net = DX.net;
    const base = net.httpBase();
    const token = {};
    root._imagePreviewToken = token;
    const images = Array.prototype.slice.call(root.querySelectorAll('img[data-preview-url]'));
    let next = 0;
    const current = () => root._imagePreviewToken === token && net.httpBase() === base;

    async function worker() {
      while (current() && next < images.length) {
        const img = images[next++];
        const url = img.getAttribute('data-preview-url');
        let failed = false;
        const fail = (message) => {
          if (failed || !current() || !img.parentElement) return;
          failed = true;
          const placeholder = document.createElement('div');
          placeholder.className = 'thumb-ph';
          placeholder.textContent = '无预览';
          placeholder.setAttribute('title', String(message || '缩略图加载失败'));
          img.style.display = 'none';
          // 只插入占位，不覆盖父节点，保留删除、调序和下载按钮及事件。
          img.parentElement.insertBefore(placeholder, img);
        };
        img.addEventListener('error', () => fail('无法解码缩略图'));
        const attempt = async (fn) => { const d = await fn(); if (current()) img.src = d; };
        try {
          try { await attempt(() => net.thumbnailDataUrl(url, 256)); }
          catch (firstErr) {
            if (!current()) return;
            try { await attempt(async () => {
              const res = await fetch(`${net.httpBase()}/api/media-preview?url=${encodeURIComponent(url)}&w=256`, { cache: 'no-store' });
              if (!res.ok) throw new Error(`HTTP ${res.status}`);
              return `data:image/png;base64,${net.toBase64(await res.arrayBuffer())}`;
            }); }
            catch (secondErr) { fail((firstErr && firstErr.message) || String(firstErr)); }
          }
        } catch (err) { fail(err.message || String(err)); }
      }
    }

    const workers = [];
    for (let i = 0; i < Math.min(6, images.length); i += 1) workers.push(worker());
    return Promise.all(workers);
  }

  // 自定义细滚动条：scrollEl 是实际滚动容器（原生条被外层裁掉），thumbEl 是叠加的细滑块。
  // 返回 sync()，内容变化后调用以刷新滑块尺寸/位置。
  function thinScroll(scrollEl, thumbEl) {
    function sync() {
      const sh = scrollEl.scrollHeight, ch = scrollEl.clientHeight;
      if (sh <= ch + 1) { thumbEl.style.display = 'none'; return; }
      thumbEl.style.display = 'block';
      const trackH = ch - 8;
      const thumbH = Math.max(24, Math.round(trackH * ch / sh));
      const maxTop = Math.max(1, trackH - thumbH);
      const top = Math.round((scrollEl.scrollTop / (sh - ch)) * maxTop);
      thumbEl.style.height = `${thumbH}px`;
      thumbEl.style.top = `${4 + top}px`;
    }
    scrollEl.addEventListener('scroll', sync);
    let dragging = false; let startY = 0; let startScroll = 0;
    thumbEl.addEventListener('mousedown', (e) => { dragging = true; startY = e.clientY; startScroll = scrollEl.scrollTop; e.preventDefault(); });
    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const sh = scrollEl.scrollHeight, ch = scrollEl.clientHeight;
      const trackH = ch - 8;
      const thumbH = Math.max(24, trackH * ch / sh);
      const maxTop = Math.max(1, trackH - thumbH);
      scrollEl.scrollTop = startScroll + ((e.clientY - startY) / maxTop) * (sh - ch);
    });
    document.addEventListener('mouseup', () => { dragging = false; });
    scrollEl._thinSync = sync;
    sync();
    return sync;
  }

  return { esc, fillPicker, pickerValue, onPick, loadImagePreviews, thinScroll };
})();
