(() => {
  const tbody = document.getElementById('runs-tbody');
  const reloadBtn = document.getElementById('reload-btn');
  const runIdsInput = document.getElementById('run-ids');
  const useSelectedBtn = document.getElementById('use-selected');
  const compareSelectedBtn = document.getElementById('compare-selected');
  const deleteSelectedBtn = document.getElementById('delete-selected');
  const prevBtn = document.getElementById('prev-page');
  const nextBtn = document.getElementById('next-page');
  const firstBtn = document.getElementById('first-page');
  const lastBtn = document.getElementById('last-page');
  const limitSel = document.getElementById('limit-select');
  const pagerInfo = document.getElementById('pager-info');
  const sortSel = document.getElementById('sort-select');
  const orderSel = document.getElementById('order-select');
  const thSortStarted = document.getElementById('th-sort-started');
  const thSortDur = document.getElementById('th-sort-dur');
  const thSortSchema = document.getElementById('th-sort-schema');
  const schemaInput = document.getElementById('schema-filter');
  const configInput = document.getElementById('config-filter');
  const applyBtn = document.getElementById('apply-filter');
  const clearBtn = document.getElementById('clear-filter');
  const pageNumInput = document.getElementById('page-number');
  const pageTotalSpan = document.getElementById('page-total');

  let state = { offset: 0, limit: 20, total: 0, sort: 'started_at', order: 'desc', schema_version: '', config_id: '', scenario_id: '' };

  function loadPrefs() {
    try {
      const raw = localStorage.getItem('runs_prefs');
      if (!raw) return;
      const p = JSON.parse(raw);
      if (p && typeof p === 'object') {
        if (p.limit) state.limit = Number(p.limit) || state.limit;
        if (p.sort) state.sort = String(p.sort);
        if (p.order) state.order = String(p.order);
        if (p.schema_version !== undefined) state.schema_version = String(p.schema_version || '');
        if (p.config_id !== undefined) state.config_id = String(p.config_id || '');
        if (p.scenario_id !== undefined) state.scenario_id = String(p.scenario_id || '');
      }
    } catch {}
  }

  function savePrefs() {
    try {
      const p = {
        limit: state.limit,
        sort: state.sort,
        order: state.order,
        schema_version: state.schema_version,
        config_id: state.config_id,
        scenario_id: state.scenario_id,
      };
      localStorage.setItem('runs_prefs', JSON.stringify(p));
    } catch {}
  }

  function syncFromUrl() {
    const sp = new URLSearchParams(location.search);
    state.offset = Number(sp.get('offset') || state.offset) || 0;
    state.limit = Number(sp.get('limit') || state.limit) || state.limit;
    state.sort = sp.get('sort') || state.sort;
    state.order = sp.get('order') || state.order;
    state.schema_version = sp.get('schema_version') || '';
    state.config_id = sp.get('config_id') || '';
    state.scenario_id = sp.get('scenario_id') || '';
    // URLに指定がなければローカル保存のプリファレンスを適用
    if (!sp.has('limit') && !sp.has('sort') && !sp.has('order') && !sp.has('schema_version') && !sp.has('config_id')) {
      loadPrefs();
    }
  }

  function syncToUrl() {
    const sp = new URLSearchParams();
    sp.set('offset', String(state.offset));
    sp.set('limit', String(state.limit));
    if (state.sort) sp.set('sort', state.sort);
    if (state.order) sp.set('order', state.order);
    if (state.schema_version) sp.set('schema_version', state.schema_version);
    if (state.config_id) sp.set('config_id', state.config_id);
    if (state.scenario_id) sp.set('scenario_id', state.scenario_id);
    const url = location.pathname + '?' + sp.toString();
    history.replaceState(null, '', url);
  }

  function fmt(v, digits = 3) {
    if (v === null || v === undefined) return '';
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    return n.toFixed(digits);
  }

  function updateSortIndicators() {
    const arrow = state.order === 'asc' ? '↑' : '↓';
    // reset classes
    [thSortStarted, thSortDur, thSortSchema].forEach(el => { if (el) el.classList.remove('active-sort'); });
    if (thSortStarted) {
      thSortStarted.textContent = 'started_at' + (state.sort === 'started_at' ? ' ' + arrow : '');
      if (state.sort === 'started_at') thSortStarted.classList.add('active-sort');
    }
    if (thSortDur) {
      thSortDur.textContent = 'dur(ms)' + (state.sort === 'duration_ms' ? ' ' + arrow : '');
      if (state.sort === 'duration_ms') thSortDur.classList.add('active-sort');
    }
    if (thSortSchema) {
      thSortSchema.textContent = 'schema' + (state.sort === 'schema_version' ? ' ' + arrow : '');
      if (state.sort === 'schema_version') thSortSchema.classList.add('active-sort');
    }
  }

  function fmtJst(ms) {
    if (ms === null || ms === undefined) return '';
    const n = Number(ms);
    if (!Number.isFinite(n)) return '';
    const t = new Date(n + 9 * 3600 * 1000); // shift to JST
    const y = t.getUTCFullYear();
    const mo = String(t.getUTCMonth() + 1).padStart(2, '0');
    const d = String(t.getUTCDate()).padStart(2, '0');
    const h = String(t.getUTCHours()).padStart(2, '0');
    const mi = String(t.getUTCMinutes()).padStart(2, '0');
    const s = String(t.getUTCSeconds()).padStart(2, '0');
    return `${y}/${mo}/${d} ${h}:${mi}:${s}`;
  }

  function rowHtml(r) {
    return `
      <tr>
        <td><input class="pick" type="checkbox" value="${r.run_id}" /></td>
        <td class="mono truncate" title="${r.run_id}">${r.run_id}</td>
        <td>${fmtJst(r.started_at)}</td>
        <td>${r.duration_ms ?? ''}</td>
        <td>${r.schema_version ?? ''}</td>
        <td>${r.config_id ?? ''}</td>
        <td>${r.scenario_id ?? ''}</td>
        <td>${fmt(r.summary?.fill_rate, 3)}</td>
        <td>${fmt(r.summary?.profit_total, 2)}</td>
        <td>
          <a role="button" href="/ui/runs/${r.run_id}">Detail</a>
          <span class="mono" style="margin-left:6px; white-space:nowrap;">
            <a href="#" class="download-csv" data-url="/runs/${r.run_id}/results.csv" title="results.csv">res</a>
            <a href="#" class="download-csv" data-url="/runs/${r.run_id}/pl.csv" title="pl.csv">pl</a>
            <a href="#" class="download-csv" data-url="/runs/${r.run_id}/summary.csv" title="summary.csv">sum</a>
            <a href="#" class="download-csv" data-url="/runs/${r.run_id}/trace.csv" title="trace.csv">trace</a>
          </span>
        </td>
      </tr>
    `;
  }

  function getHeaders(){
    const h = {};
    try { const k = localStorage.getItem('api_key') || ''; if (k) h['X-API-Key'] = k; } catch {}
    return h;
  }

  async function reloadRuns() {
    try {
      const q = new URLSearchParams({ offset: String(state.offset), limit: String(state.limit) });
      if (state.sort) q.set('sort', state.sort);
      if (state.order) q.set('order', state.order);
      if (state.schema_version) q.set('schema_version', state.schema_version);
      if (state.config_id) q.set('config_id', state.config_id);
      if (state.scenario_id) q.set('scenario_id', state.scenario_id);
      const res = await fetch(`/runs?${q.toString()}`, { headers: getHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rows = (data.runs || []);
      state.total = Number(data.total || rows.length || 0);
      state.offset = Number(data.offset || state.offset);
      state.limit = Number(data.limit || state.limit);
      if (tbody) {
        tbody.innerHTML = rows.map(rowHtml).join('');
        // 直近の選択を復元
        try {
          const saved = JSON.parse(localStorage.getItem('runs_selected') || '[]');
          if (Array.isArray(saved) && saved.length) {
            const set = new Set(saved);
            Array.from(tbody.querySelectorAll('input.pick')).forEach(el => {
              if (set.has(el.value)) el.checked = true;
            });
            if (runIdsInput) runIdsInput.value = saved.join(',');
          }
        } catch {}
      }
      // update pager
      const start = state.total ? (state.offset + 1) : 0;
      const end = Math.min(state.offset + state.limit, state.total);
      if (pagerInfo) pagerInfo.textContent = `${start}-${end} / ${state.total}`;
      if (prevBtn) prevBtn.disabled = (state.offset <= 0);
      if (nextBtn) nextBtn.disabled = (state.offset + state.limit >= state.total);
      if (firstBtn) firstBtn.disabled = (state.offset <= 0);
      if (lastBtn) lastBtn.disabled = (state.offset + state.limit >= state.total);
      // page number display
      const pages = state.limit > 0 ? Math.ceil((state.total || 0) / state.limit) : 1;
      if (pageTotalSpan) pageTotalSpan.textContent = String(Math.max(1, pages));
      if (pageNumInput) pageNumInput.value = String(Math.floor((state.offset / state.limit) + 1));
      if (limitSel && String(state.limit) !== limitSel.value) {
        // sync select without triggering change
        limitSel.value = String(state.limit);
      }
      if (sortSel && state.sort !== sortSel.value) sortSel.value = state.sort;
      if (orderSel && state.order !== orderSel.value) orderSel.value = state.order;
      if (schemaInput && schemaInput.value !== (state.schema_version || '')) schemaInput.value = state.schema_version || '';
      if (configInput && configInput.value !== (state.config_id || '')) configInput.value = state.config_id || '';
      const scenarioInput = document.getElementById('scenario-filter');
      if (scenarioInput && scenarioInput.value !== (state.scenario_id || '')) scenarioInput.value = state.scenario_id || '';
      // URL更新
      syncToUrl();
      // ソート矢印表示
      updateSortIndicators();
    } catch (e) {
      console.error('Failed to reload runs', e);
      alert('Failed to load runs from API.');
    }
  }

  function useSelected() {
    if (!tbody || !runIdsInput) return;
    const ids = Array.from(tbody.querySelectorAll('input.pick:checked')).map(el => el.value);
    if (!ids.length) {
      alert('No runs selected.');
      return;
    }
    runIdsInput.value = ids.join(',');
    try { localStorage.setItem('runs_selected', JSON.stringify(ids)); } catch {}
  }

  async function deleteSelected() {
    if (!tbody) return;
    const ids = Array.from(tbody.querySelectorAll('input.pick:checked')).map(el => el.value);
    if (!ids.length) { alert('No runs selected.'); return; }
    if (!confirm(`Delete ${ids.length} selected run(s)? This cannot be undone.`)) return;
    let ok = 0, ng = 0;
    for (const id of ids) {
      try {
        const res = await fetch(`/runs/${id}`, { method: 'DELETE', headers: getHeaders() });
        if (res.ok) ok++; else ng++;
      } catch (e) { console.error(e); ng++; }
    }
    alert(`Deleted: ${ok}, Failed: ${ng}`);
    reloadRuns();
  }

  if (reloadBtn) reloadBtn.addEventListener('click', reloadRuns);
  if (useSelectedBtn) useSelectedBtn.addEventListener('click', useSelected);
  if (deleteSelectedBtn) deleteSelectedBtn.addEventListener('click', deleteSelected);
  if (compareSelectedBtn) compareSelectedBtn.addEventListener('click', () => {
    useSelected();
    const form = document.getElementById('compare-form');
    if (form) form.submit();
  });
  const compareForm = document.getElementById('compare-form');
  if (compareForm) compareForm.addEventListener('submit', () => {
    try {
      const ids = (runIdsInput && runIdsInput.value) ? runIdsInput.value.split(',').map(s => s.trim()).filter(Boolean) : [];
      localStorage.setItem('runs_selected', JSON.stringify(ids));
    } catch {}
  });
  if (prevBtn) prevBtn.addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); reloadRuns(); });
  if (nextBtn) nextBtn.addEventListener('click', () => { state.offset = state.offset + state.limit; reloadRuns(); });
  if (firstBtn) firstBtn.addEventListener('click', () => { state.offset = 0; reloadRuns(); });
  if (lastBtn) lastBtn.addEventListener('click', () => {
    const pages = state.limit > 0 ? Math.floor(Math.max(0, state.total - 1) / state.limit) : 0;
    state.offset = pages * state.limit;
    reloadRuns();
  });
  if (limitSel) limitSel.addEventListener('change', () => {
    const v = Number(limitSel.value);
    if (!Number.isFinite(v) || v <= 0) return;
    state.limit = v;
    state.offset = 0; // reset to first page
    savePrefs();
    reloadRuns();
  });
  if (sortSel) sortSel.addEventListener('change', () => { state.sort = sortSel.value; state.offset = 0; savePrefs(); reloadRuns(); });
  if (orderSel) orderSel.addEventListener('change', () => { state.order = orderSel.value; state.offset = 0; savePrefs(); reloadRuns(); });
  function toggleSort(key){
    if (state.sort === key) {
      state.order = (state.order === 'asc') ? 'desc' : 'asc';
    } else {
      state.sort = key;
      state.order = 'desc';
    }
    state.offset = 0;
    savePrefs();
    reloadRuns();
  }
  if (thSortStarted) thSortStarted.addEventListener('click', () => toggleSort('started_at'));
  if (thSortDur) thSortDur.addEventListener('click', () => toggleSort('duration_ms'));
  if (thSortSchema) thSortSchema.addEventListener('click', () => toggleSort('schema_version'));
  if (pageNumInput) pageNumInput.addEventListener('change', () => {
    const v = Number(pageNumInput.value);
    const pages = state.limit > 0 ? Math.ceil((state.total || 0) / state.limit) : 1;
    if (!Number.isFinite(v) || v < 1) { pageNumInput.value = '1'; return; }
    const p = Math.min(Math.max(1, Math.floor(v)), Math.max(1, pages));
    state.offset = (p - 1) * state.limit;
    reloadRuns();
  });
  if (applyBtn) applyBtn.addEventListener('click', () => {
    state.schema_version = (schemaInput && schemaInput.value || '').trim();
    const cid = (configInput && configInput.value || '').trim();
    const sidEl = document.getElementById('scenario-filter');
    const sid = (sidEl && sidEl.value || '').trim();
    state.config_id = cid;
    state.scenario_id = sid;
    state.offset = 0;
    savePrefs();
    reloadRuns();
  });
  if (clearBtn) clearBtn.addEventListener('click', () => {
    if (schemaInput) schemaInput.value = '';
    if (configInput) configInput.value = '';
    state.schema_version = '';
    state.config_id = '';
    const sidEl = document.getElementById('scenario-filter'); if (sidEl) sidEl.value = '';
    state.scenario_id = '';
    state.offset = 0;
    savePrefs();
    reloadRuns();
  });

  // 初期ロード: URL→state同期の上で読込
  function init() { syncFromUrl(); updateSortIndicators(); reloadRuns(); }
  // expose for inline script to trigger initial load
  window.RunsUI = { reloadRuns, init };

  function downloadCsv(ev) {
    ev.preventDefault();
    const el = ev.currentTarget;
    const url = el.getAttribute('data-url');
    if (!url) return;
    const headers = getHeaders();
    fetch(url, { headers })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const disposition = res.headers.get('content-disposition');
        let filename = url.split('/').pop();
        if (disposition && disposition.includes('attachment')) {
          const m = disposition.match(/filename="?([^;"]+)"?/);
          if (m && m[1]) filename = m[1];
        }
        return res.blob().then(blob => ({ blob, filename }));
      })
      .then(({ blob, filename }) => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
      })
      .catch(e => {
        console.error('Download failed', e);
        alert('Download failed. Check API key or server status.');
      });
  }

  document.body.addEventListener('click', ev => {
    if (ev.target.classList.contains('download-csv')) {
      downloadCsv(ev);
    }
  });

})();
