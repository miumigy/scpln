(() => {
  const tbody = document.getElementById('runs-tbody');
  const reloadBtn = document.getElementById('reload-btn');
  const runIdsInput = document.getElementById('run-ids');
  const useSelectedBtn = document.getElementById('use-selected');

  function fmt(v, digits = 3) {
    if (v === null || v === undefined) return '';
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    return n.toFixed(digits);
  }

  function rowHtml(r) {
    return `
      <tr>
        <td><input class="pick" type="checkbox" value="${r.run_id}" /></td>
        <td class="mono truncate" title="${r.run_id}">${r.run_id}</td>
        <td>${r.started_at ?? ''}</td>
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
      const res = await fetch('/runs');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rows = (data.runs || []);
      if (tbody) {
        tbody.innerHTML = rows.map(rowHtml).join('');
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
})();
