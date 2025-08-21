(() => {
  const tbody = document.getElementById('runs-tbody');
  const reloadBtn = document.getElementById('reload-btn');
  const runIdsInput = document.getElementById('run-ids');
  const useSelectedBtn = document.getElementById('use-selected');
  const prevBtn = document.getElementById('prev-page');
  const nextBtn = document.getElementById('next-page');
  const limitSel = document.getElementById('limit-select');
  const pagerInfo = document.getElementById('pager-info');

  let state = { offset: 0, limit: 20, total: 0 };

  function fmt(v, digits = 3) {
    if (v === null || v === undefined) return '';
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    return n.toFixed(digits);
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
        <td>${fmt(r.summary?.fill_rate, 3)}</td>
        <td>${fmt(r.summary?.profit_total, 2)}</td>
        <td>
          <a role="button" href="/ui/runs/${r.run_id}">Detail</a>
        </td>
      </tr>
    `;
  }

  async function reloadRuns() {
    try {
      const q = new URLSearchParams({ offset: String(state.offset), limit: String(state.limit) });
      const res = await fetch(`/runs?${q.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rows = (data.runs || []);
      state.total = Number(data.total || rows.length || 0);
      state.offset = Number(data.offset || state.offset);
      state.limit = Number(data.limit || state.limit);
      if (tbody) {
        tbody.innerHTML = rows.map(rowHtml).join('');
      }
      // update pager
      const start = state.total ? (state.offset + 1) : 0;
      const end = Math.min(state.offset + state.limit, state.total);
      if (pagerInfo) pagerInfo.textContent = `${start}-${end} / ${state.total}`;
      if (prevBtn) prevBtn.disabled = (state.offset <= 0);
      if (nextBtn) nextBtn.disabled = (state.offset + state.limit >= state.total);
      if (limitSel && String(state.limit) !== limitSel.value) {
        // sync select without triggering change
        limitSel.value = String(state.limit);
      }
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
  }

  if (reloadBtn) reloadBtn.addEventListener('click', reloadRuns);
  if (useSelectedBtn) useSelectedBtn.addEventListener('click', useSelected);
  if (prevBtn) prevBtn.addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); reloadRuns(); });
  if (nextBtn) nextBtn.addEventListener('click', () => { state.offset = state.offset + state.limit; reloadRuns(); });
  if (limitSel) limitSel.addEventListener('change', () => {
    const v = Number(limitSel.value);
    if (!Number.isFinite(v) || v <= 0) return;
    state.limit = v;
    state.offset = 0; // reset to first page
    reloadRuns();
  });

  // expose for inline script to trigger initial load
  window.RunsUI = { reloadRuns };
})();
