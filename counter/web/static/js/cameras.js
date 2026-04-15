// Camera slots: name, source (demo feed / video file), status, Offline toggle, test snapshot.
import { api, $, $$, h, esc } from './api.js';

const TYPES = [['none', 'Not connected'], ['demo', 'Demo feed'], ['file', 'Video file']];

export async function mountCameras(root, ctx) {
  const [cams, demo] = await Promise.all([api('/api/cameras'), api('/api/demo-feeds')]);
  const feeds = Object.fromEntries(demo.feeds.map((f) => [f.id, f]));
  let timer = null;

  root.append(h(`<section>
    <h1 style="font-size:30px;margin-bottom:4px">Cameras</h1>
    <p class="muted" style="margin:0 0 16px">Cameras are added from the layout. Here you can rename them, test them, or take one offline.</p>
    <table class="cams"><thead><tr><th>ID</th><th>Name</th><th>Source</th><th>Zone</th><th>Status</th><th>Offline</th><th></th></tr></thead>
    <tbody id="rows"></tbody></table>
    <p class="muted" id="none" hidden>No cameras yet. <a href="#/layout">Add a zone</a> and choose “+ New camera”.</p></section>`));

  function sourceField(c) {
    if (c.source_type === 'demo') {
      return `<select data-f="source" aria-label="Demo feed"><option value="">Choose a feed</option>
        <optgroup label="Demo cameras">${demo.feeds.map((f) => `<option value="${f.id}" ${f.id === c.source ? 'selected' : ''}>${esc(f.name)}${f.ready ? '' : ' (not prepared)'}</option>`).join('')}</optgroup></select>`;
    }
    if (c.source_type === 'file') return `<input data-f="source" placeholder="footage/…/clip.mp4" value="${esc(c.source)}" aria-label="File path">`;
    return '';
  }

  function statusOf(c) {
    if (c.offline) return ['unknown', 'Offline'];
    if (c.live_status) return c.live_status === 'ok' ? ['ok', 'Live'] : ['unknown', 'Unknown (no data)'];
    if (c.status === 'ok') return ['ok', 'Tested OK' + (c.status_detail ? ` · ${c.status_detail}` : '')];
    if (c.status === 'error') return ['error', c.status_detail || 'Error'];
    return ['', c.source_type === 'none' ? 'Not connected' : 'Not tested'];
  }

  function render() {
    const tb = $('#rows');
    tb.innerHTML = '';
    $('#none').hidden = cams.length > 0;
    $('table.cams').hidden = !cams.length;
    for (const c of cams) {
      const [cls, text] = statusOf(c);
      const feed = c.source_type === 'demo' && feeds[c.source];
      const tr = h(`<tr data-id="${c.id}">
        <td class="id">${esc(c.id)}</td>
        <td><input data-f="name" value="${esc(c.name)}" aria-label="Camera name"></td>
        <td><div class="src"><select data-f="source_type" aria-label="Source type">${TYPES.map(([k, l]) => `<option value="${k}" ${k === c.source_type ? 'selected' : ''}>${l}</option>`).join('')}</select>${sourceField(c)}</div>
          ${feed && !feed.ready ? '<div class="muted" style="font-size:13px;margin-top:4px">Not prepared: run scripts/prepare_demo_feeds.py</div>' : ''}</td>
        <td>${c.zone ? `<a href="#/layout">${esc(c.zone.name)}</a>` : '<span class="muted">Not assigned</span>'}</td>
        <td><span class="status ${cls}">${esc(text)}</span></td>
        <td>${c.source_type === 'demo' ? `<label class="toggle"><input type="checkbox" data-f="offline" ${c.offline ? 'checked' : ''}> Offline</label>` : '<span class="muted">–</span>'}</td>
        <td><button class="btn small" data-test ${c.source_type === 'none' || !c.source ? 'disabled' : ''}>Test</button><div class="snap" hidden></div></td>
      </tr>`);
      tb.append(tr);
    }
  }

  async function patch(id, body) {
    const updated = await api(`/api/cameras/${id}`, { method: 'PATCH', body });
    const i = cams.findIndex((c) => c.id === id);
    cams[i] = { ...cams[i], ...updated };
    render();
  }

  root.addEventListener('change', async (e) => {
    const tr = e.target.closest('tr[data-id]'), f = e.target.dataset.f;
    if (!tr || !f) return;
    const id = tr.dataset.id;
    try {
      if (f === 'offline') await patch(id, { offline: e.target.checked });
      else if (f === 'source_type') await patch(id, { source_type: e.target.value, source: '' });
      else await patch(id, { [f]: e.target.value });
    } catch (err) { alert(err.message); render(); }
  });

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-test]');
    if (!btn) return;
    const tr = btn.closest('tr'), box = $('.snap', tr), id = tr.dataset.id;
    box.hidden = false; box.textContent = 'Connecting…';
    try {
      const res = await fetch(`/api/cameras/${id}/snapshot?t=${Date.now()}`);
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || res.statusText); }
      const url = URL.createObjectURL(await res.blob());
      box.innerHTML = ''; box.append(h(`<img alt="Snapshot from ${esc(id)}" src="${url}">`));
      const fresh = await api('/api/cameras');
      const c = fresh.find((x) => x.id === id);
      Object.assign(cams.find((x) => x.id === id), c);
      $('.status', tr).className = 'status ' + statusOf(c)[0];
      $('.status', tr).textContent = statusOf(c)[1];
    } catch (err) { box.textContent = err.message; }
  });

  render();
  // Keep live status current while the site is live
  timer = setInterval(async () => {
    if (!ctx.live || document.activeElement?.closest?.('tr')) return;
    const fresh = await api('/api/cameras').catch(() => null);
    if (fresh) { fresh.forEach((c) => Object.assign(cams.find((x) => x.id === c.id) || {}, c)); render(); }
  }, 3000);
  return () => clearInterval(timer);
}
