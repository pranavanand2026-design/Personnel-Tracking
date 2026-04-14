// Layout editor: snap-to-grid plan on the left, zone list and go-live checks on the right.
// Select a block to edit it in a popover beside it (name, role, camera, source).
// The saved layout is the configuration. Undo/redo and autosave.
import { api, $, $$, h, esc } from './api.js';
import { CELL, mk, px, pathD, drawDoor, roleOf, isOutside, isDoor } from './plan.js';

const DEFAULT_SIZE = { in_out: [8, 5], present: [10, 6], arrivals: [7, 7] };
const MIN = 3, EDGE = 0.45;  // minimum zone size and edge grab width, in cells
const icon = (role) => (isDoor(role) ? 'entry' : isOutside(role) ? 'muster' : 'general');

export async function mountEditor(root, ctx) {
  const [layout, cameras, demo] = await Promise.all([api('/api/layout'), api('/api/cameras'), api('/api/demo-feeds')]);
  const roles = ctx.roles;
  const G = layout.grid;
  let L = { outline: layout.outline, zones: layout.zones, paths: layout.paths };
  let problems = layout.problems;
  let sel = null;            // {type:'zone', id} | {type:'path', i}
  const past = [], future = [];
  let saveTimer = null, saveState = 'Saved';

  root.append(h(`<div class="live editor2">
    <section>
      <div class="toolbar">
        <button class="ib" id="undo" title="Undo (⌘Z)" aria-label="Undo">↶</button>
        <button class="ib" id="redo" title="Redo (⇧⌘Z)" aria-label="Redo">↷</button>
        <span class="save" id="save"></span>
      </div>
      <div class="plan-wrap canvas-wrap" id="wrap">
        <svg class="plan canvas" id="cv" viewBox="0 0 ${G.w * CELL} ${G.h * CELL}" role="application" aria-label="Site layout editor"></svg>
        <button class="start" id="start" hidden>+ Add zone</button>
        <button class="fab" id="fab" hidden>+ Add zone</button>
        <div class="addmenu" id="menu" hidden>
          ${roles.map((r) => `<button class="mi" data-role="${r.key}"><i class="${icon(r)}"></i><span>${esc(r.label)}<small>${esc(r.description)}</small></span></button>`).join('')}
        </div>
        <div class="pop" id="pop" hidden></div>
      </div>
    </section>
    <aside class="rail">
      <h2>Zones</h2>
      <ul id="zlist"></ul>
      <h2 class="sub">Before going live</h2>
      <ul class="checks" id="checks"></ul>
      <div class="row-btns">
        <button class="btn go" id="golive">Go live</button>
        <button class="link" id="stoplive" hidden>Stop monitoring</button>
      </div>
    </aside></div>`));

  const svg = $('#cv'), wrap = $('#wrap'), pop = $('#pop'), menu = $('#menu');
  const zoneById = (id) => L.zones.find((z) => z.id === id);
  const camById = (id) => cameras.find((c) => c.id === id);
  const snapshot = () => JSON.stringify(L);
  const issuesOf = (id) => problems.filter((p) => p.zone === id);

  // ---------- history + autosave ----------
  function commit(before) {
    if (before === snapshot()) { render(); return; }
    past.push(before); future.length = 0;
    if (past.length > 100) past.shift();
    saveSoon(); render();
  }
  function undo() { if (!past.length) return; future.push(snapshot()); L = JSON.parse(past.pop()); fixSel(); saveSoon(); render(); }
  function redo() { if (!future.length) return; past.push(snapshot()); L = JSON.parse(future.pop()); fixSel(); saveSoon(); render(); }
  function fixSel() {
    if (sel?.type === 'zone' && !zoneById(sel.id)) sel = null;
    if (sel?.type === 'path' && !L.paths[sel.i]) sel = null;
  }
  function saveSoon() {
    saveState = 'Saving…'; renderToolbar();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 400);
  }
  async function save() {
    try {
      const r = await api('/api/layout', { method: 'PUT', body: L });
      problems = r.problems; saveState = 'Saved';
    } catch (e) { saveState = 'Not saved: ' + e.message; }
    renderToolbar(); renderChecks(); renderList(); renderPlan();
  }

  // ---------- coordinates ----------
  function cellAt(ev) {
    const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse());
    return { x: q.x / CELL, y: q.y / CELL };
  }
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  function zoneAt(c) {
    return [...L.zones].reverse().find((z) => c.x >= z.x && c.x <= z.x + z.w && c.y >= z.y && c.y <= z.y + z.h);
  }
  // SVG user units -> pixels inside #wrap
  function toWrap(x, y) {
    const m = svg.getScreenCTM(), b = wrap.getBoundingClientRect();
    return { x: m.a * x + m.e - b.left, y: m.d * y + m.f - b.top };
  }

  // ---------- render ----------
  function render() { renderPlan(); renderList(); renderChecks(); renderToolbar(); renderPop(); }

  function renderToolbar() {
    $('#undo').disabled = !past.length; $('#redo').disabled = !future.length;
    const s = $('#save'); s.textContent = saveState; s.classList.toggle('err', saveState.startsWith('Not'));
    $('#start').hidden = L.zones.length > 0; $('#fab').hidden = !L.zones.length;
  }

  function renderPlan() {
    svg.innerHTML = '';
    const defs = mk('defs', {}, svg), pat = mk('pattern', { id: 'grid', width: CELL, height: CELL, patternUnits: 'userSpaceOnUse' }, defs);
    mk('path', { d: `M${CELL} 0H0V${CELL}`, class: 'gl' }, pat);
    mk('rect', { width: G.w * CELL, height: G.h * CELL, fill: 'url(#grid)' }, svg);

    if (L.outline) {
      const O = px(L.outline);
      mk('rect', { x: O.x, y: O.y, width: O.w, height: O.h, class: 'bldg' }, svg);
      edges(L.outline, svg, 'bldg-edge', { act: 'outline' });
    }
    for (const z of L.zones) if (isDoor(roleOf(roles, z.role))) drawDoor(z, L.outline, svg);

    L.paths.forEach((p, i) => {
      const a = zoneById(p.from_zone), b = zoneById(p.to_zone);
      if (!a || !b) return;
      const d = pathD(a, b);
      mk('path', { d, class: 'path' + (sel?.type === 'path' && sel.i === i ? ' sel' : '') }, svg);
      mk('path', { d, class: 'path-hit', 'data-act': 'path', 'data-i': i }, svg);
    });

    for (const z of L.zones) {
      const role = roleOf(roles, z.role), R = px(z), cam = camById(z.camera_id), on = sel?.type === 'zone' && sel.id === z.id;
      const g = mk('g', { class: 'zone' + (isOutside(role) ? ' outside' : '') + (on ? ' sel' : ''), 'data-act': 'move', 'data-id': z.id }, svg);
      mk('rect', { x: R.x, y: R.y, width: R.w, height: R.h, rx: isOutside(role) ? 12 : 3, class: 'r', 'data-act': 'move', 'data-id': z.id }, g);
      mk('text', { x: R.x + 12, y: R.y + 27, class: 'zname', 'pointer-events': 'none' }, g, z.name);
      mk('text', { x: R.x + 12, y: R.y + 45, class: 'zkick', 'pointer-events': 'none' }, g, role.label.toUpperCase());
      mk('text', { x: R.x + 12, y: R.y + 64, class: 'zcam' + (cam ? '' : ' warn'), 'pointer-events': 'none' }, g, cam ? cam.name : 'No camera');
      if (issuesOf(z.id).length) mk('circle', { cx: R.x + R.w - 13, cy: R.y + 13, r: 5.5, class: 'wd', 'pointer-events': 'none' }, g);
      edges(z, g, 'edge', { act: 'resize', id: z.id });
      if (on) {
        mk('rect', { x: R.x + R.w - 8, y: R.y + R.h - 8, width: 16, height: 16, rx: 2, class: 'rs', 'data-act': 'resize', 'data-edge': 'se', 'data-id': z.id }, g);
      }
      for (const [kx, ky] of [[R.x + R.w / 2, R.y], [R.x + R.w / 2, R.y + R.h], [R.x, R.y + R.h / 2], [R.x + R.w, R.y + R.h / 2]])
        mk('circle', { cx: kx, cy: ky, r: 7, class: 'knob', 'data-act': 'link', 'data-id': z.id }, g);
    }
  }

  function edges(r, parent, cls, data) {
    const R = px(r), e = EDGE * CELL;
    for (const [edge, x, y, w, hgt, dir] of [
      ['n', R.x, R.y - e, R.w, 2 * e, 'ns'], ['s', R.x, R.y + R.h - e, R.w, 2 * e, 'ns'],
      ['w', R.x - e, R.y, 2 * e, R.h, 'ew'], ['e', R.x + R.w - e, R.y, 2 * e, R.h, 'ew']]) {
      const attrs = { x, y, width: w, height: hgt, class: `${cls} ${dir}`, 'data-act': data.act, 'data-edge': edge };
      if (data.id) attrs['data-id'] = data.id;
      mk('rect', attrs, parent);
    }
  }

  function renderList() {
    const ul = $('#zlist');
    ul.innerHTML = L.zones.length ? '' : '<li class="muted empty">No zones yet</li>';
    for (const z of L.zones) {
      const role = roleOf(roles, z.role), cam = camById(z.camera_id), on = sel?.type === 'zone' && sel.id === z.id, bad = issuesOf(z.id).length;
      const li = h(`<li><button class="ri ${isOutside(role) ? 'outside' : ''} ${bad ? 'unknown' : ''} ${on ? 'sel' : ''}">
        <span class="nm">${esc(z.name)}</span><span class="cm">${esc(role.label)} · ${esc(cam ? cam.name : 'no camera')}</span></button></li>`);
      $('button', li).onclick = () => { sel = on ? null : { type: 'zone', id: z.id }; render(); };
      ul.append(li);
    }
  }

  // Go-live checks, phrased as a short list rather than raw problems
  function renderChecks() {
    const n = (codes) => problems.filter((p) => codes.includes(p.code)).length;
    const zoneCount = L.zones.length;
    const items = [
      { ok: !n(['no_entry']) && zoneCount > 0, t: 'An entry zone' },
      { ok: zoneCount > 0 && !n(['no_camera', 'missing_camera', 'camera_twice']), t: n(['no_camera', 'missing_camera']) ? `${n(['no_camera', 'missing_camera'])} zone(s) without a camera` : n(['camera_twice']) ? 'A camera is used twice' : 'Every zone has a camera' },
      { ok: zoneCount > 0 && !n(['camera_no_source']), t: n(['camera_no_source']) ? `${n(['camera_no_source'])} camera(s) without a source` : 'Every camera has a source' },
      { ok: zoneCount > 0 && !n(['unreachable']), t: n(['unreachable']) ? `${n(['unreachable'])} zone(s) not connected to an entry` : 'All zones connected' },
    ];
    const placed = n(['inside_outside', 'outside_overlaps', 'unknown_role']);
    if (placed) items.push({ ok: false, t: `${placed} zone(s) on the wrong side of the building outline` });
    $('#checks').innerHTML = items.map((c) => `<li class="${c.ok ? 'ok' : ''}"><i></i>${esc(c.t)}</li>`).join('');
    $('#golive').disabled = problems.length > 0 || !zoneCount || saveState !== 'Saved';
    $('#golive').textContent = ctx.live ? 'Apply changes' : 'Go live';
    $('#stoplive').hidden = !ctx.live;
  }

  // ---------- popover beside the selection ----------
  function place(el, r) {
    const bw = wrap.clientWidth, bh = wrap.clientHeight, w = el.offsetWidth, hh = el.offsetHeight, g = 12;
    let x = r.x2 + g, y = r.y1;
    if (x + w > bw - 8) x = r.x1 - w - g;
    if (x < 8) { x = clamp(r.x1, 8, bw - w - 8); y = r.y2 + g; if (y + hh > bh - 8) y = r.y1 - hh - g; }
    el.style.left = clamp(x, 8, Math.max(8, bw - w - 8)) + 'px';
    el.style.top = clamp(y, 8, Math.max(8, bh - hh - 8)) + 'px';
  }

  function sourceValue(c) {
    if (!c || c.source_type === 'none' || !c.source) return c?.source_type === 'file' ? 'file:' : '';
    return `${c.source_type}:${c.source}`;
  }

  function renderPop() {
    if (drag || !sel) { pop.hidden = true; return; }
    if (sel.type === 'path') {
      const p = L.paths[sel.i], a = zoneById(p?.from_zone), b = zoneById(p?.to_zone);
      if (!a || !b) { pop.hidden = true; return; }
      pop.innerHTML = `<p class="ptitle">${esc(a.name)} ↔ ${esc(b.name)}</p><div class="pfoot"><span></span><button class="plink danger" id="pDel">Delete path</button></div>`;
      pop.hidden = false;
      const d = svg.querySelector(`.path-hit[data-i="${sel.i}"]`).getBBox(), m = toWrap(d.x + d.width / 2, d.y + d.height / 2);
      place(pop, { x1: m.x, y1: m.y, x2: m.x, y2: m.y });
      $('#pDel').onclick = removeSelection;
      return;
    }
    const z = zoneById(sel.id);
    if (!z) { pop.hidden = true; return; }
    const cam = camById(z.camera_id), sv = sourceValue(cam);
    const usedBy = Object.fromEntries(L.zones.filter((o) => o.camera_id && o.id !== z.id).map((o) => [o.camera_id, o.name]));
    pop.innerHTML = `
      <input class="pname" id="pName" value="${esc(z.name)}" aria-label="Zone name">
      <div class="chips">${roles.map((r) => `<button data-role-set="${r.key}" class="${z.role === r.key ? 'on' : ''}">${esc(r.label.replace(' zone', ''))}</button>`).join('')}</div>
      <label class="pr"><span>Camera</span><select id="pCam"><option value="">None</option>
        ${cameras.map((c) => `<option value="${c.id}" ${c.id === z.camera_id ? 'selected' : ''}>${esc(c.name)}${usedBy[c.id] ? ` (${esc(usedBy[c.id])})` : ''}</option>`).join('')}
        <option value="__new">+ New camera</option></select></label>
      ${cam ? `<label class="pr"><span>Source</span><select id="pSrc"><option value="">Not set</option>
          <optgroup label="Demo cameras">${demo.feeds.map((f) => `<option value="demo:${f.id}" ${sv === 'demo:' + f.id ? 'selected' : ''}>${esc(f.name)}${f.ready ? '' : ' (not prepared)'}</option>`).join('')}</optgroup>
          <option value="file:" ${sv.startsWith('file:') ? 'selected' : ''}>Video file…</option></select></label>
        ${cam.source_type === 'file' ? `<label class="pr"><span>File</span><input id="pFile" placeholder="footage/…/clip.mp4" value="${esc(cam.source)}"></label>` : ''}
        <div class="snap" id="pSnap" hidden></div>` : ''}
      <div class="pfoot">${cam && cam.source ? '<button class="plink" id="pPic">Show picture</button>' : '<span></span>'}
        <button class="plink danger" id="pDel">Delete zone</button></div>`;
    pop.hidden = false;
    const g = svg.querySelector(`g.zone[data-id="${z.id}"] .r`).getBBox();
    const a = toWrap(g.x, g.y), b = toWrap(g.x + g.width, g.y + g.height);
    place(pop, { x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    bindPop(z, cam);
  }

  function bindPop(z, cam) {
    const n = $('#pName'); let before = null;
    n.addEventListener('focus', () => (before = snapshot()));
    n.addEventListener('input', () => { z.name = n.value || 'Zone'; renderPlan(); renderList(); });
    n.addEventListener('change', () => { z.name = n.value.trim() || 'Zone'; commit(before || snapshot()); });
    n.addEventListener('keydown', (e) => { if (e.key === 'Enter') n.blur(); e.stopPropagation(); });
    $$('[data-role-set]', pop).forEach((b) => (b.onclick = () => { const s = snapshot(); z.role = b.dataset.roleSet; commit(s); }));
    $('#pCam').onchange = async (e) => {
      const s = snapshot();
      let id = e.target.value;
      if (id === '__new') {
        try { const c = await api('/api/cameras', { method: 'POST', body: {} }); cameras.push(c); id = c.id; }
        catch (err) { alert(err.message); renderPop(); return; }
      }
      for (const o of L.zones) if (id && o.camera_id === id) o.camera_id = null;  // a camera watches one zone
      z.camera_id = id || null;
      commit(s);
      if (camById(id) && !camById(id).source) $('#pSrc')?.focus();
    };
    const src = $('#pSrc');
    if (src) src.onchange = async () => {
      const [type, value] = src.value ? [src.value.split(':')[0], src.value.slice(src.value.indexOf(':') + 1)] : ['none', ''];
      await patchCamera(cam, { source_type: type, source: value });
      if (type === 'file') $('#pFile')?.focus();
    };
    const file = $('#pFile');
    if (file) {
      file.addEventListener('keydown', (e) => e.stopPropagation());
      file.addEventListener('change', () => patchCamera(cam, { source_type: 'file', source: file.value.trim() }));
    }
    const pic = $('#pPic');
    if (pic) pic.onclick = () => showPicture(cam);
    $('#pDel').onclick = removeSelection;
  }

  async function patchCamera(cam, body) {
    try {
      const c = await api(`/api/cameras/${cam.id}`, { method: 'PATCH', body });
      Object.assign(cam, c);
      await save();  // re-check problems with the new source
    } catch (err) { alert(err.message); }
    renderPop();
  }

  async function showPicture(cam) {
    const box = $('#pSnap');
    box.hidden = false; box.textContent = 'Connecting…';
    renderPopPosition();
    try {
      const res = await fetch(`/api/cameras/${cam.id}/snapshot?t=${Date.now()}`);
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || res.statusText); }
      const url = URL.createObjectURL(await res.blob());
      box.innerHTML = ''; box.append(h(`<img alt="Picture from ${esc(cam.name)}" src="${url}">`));
    } catch (e) { box.textContent = e.message; }
    renderPopPosition();
  }
  function renderPopPosition() {
    if (pop.hidden || sel?.type !== 'zone') return;
    const g = svg.querySelector(`g.zone[data-id="${sel.id}"] .r`)?.getBBox();
    if (!g) return;
    const a = toWrap(g.x, g.y), b = toWrap(g.x + g.width, g.y + g.height);
    place(pop, { x1: a.x, y1: a.y, x2: b.x, y2: b.y });
  }

  // ---------- edits ----------
  function freeSpot(w, hgt, area) {
    const hits = (x, y) => L.zones.some((z) => x < z.x + z.w && x + w > z.x && y < z.y + z.h && y + hgt > z.y);
    for (let y = area.y + 1; y + hgt <= area.y + area.h - 1; y++)
      for (let x = area.x + 1; x + w <= area.x + area.w - 1; x++)
        if (!hits(x, y)) return { x, y };
    return { x: area.x + 1, y: area.y + 1 };
  }

  function addZone(roleKey) {
    const role = roleOf(roles, roleKey), [w, hgt] = DEFAULT_SIZE[role.behaviour.counts] || [8, 6];
    const n = L.zones.filter((z) => z.role === roleKey).length + 1;
    const o = L.outline || { x: 1, y: 1, w: 28, h: 22 };
    const { x, y } = freeSpot(w, hgt, isOutside(role) ? { x: o.x + o.w + 1, y: 0, w: G.w - o.x - o.w - 1, h: G.h } : o);
    const z = { id: 'zone-' + Math.random().toString(36).slice(2, 8), name: n > 1 ? `${role.label} ${n}` : role.label,
      role: roleKey, x: clamp(x, 0, G.w - w), y: clamp(y, 0, G.h - hgt), w, h: hgt, camera_id: null,
      capacity: role.behaviour.counts === 'arrivals' ? 200 : 20 };
    const before = snapshot();
    L.zones.push(z); sel = { type: 'zone', id: z.id };
    closeMenu(); commit(before);
    $('#pName')?.focus(); $('#pName')?.select();
  }

  function removeSelection() {
    if (!sel) return;
    const before = snapshot();
    if (sel.type === 'zone') {
      L.zones = L.zones.filter((z) => z.id !== sel.id);
      L.paths = L.paths.filter((p) => p.from_zone !== sel.id && p.to_zone !== sel.id);
    } else L.paths.splice(sel.i, 1);
    sel = null; commit(before);
  }

  // ---------- pointer interaction on the plan ----------
  let drag = null;
  svg.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    closeMenu();
    const t = ev.target.closest('[data-act]'), c = cellAt(ev);
    if (!t) { sel = null; render(); return; }
    const act = t.dataset.act, before = snapshot();
    if (act === 'path') { sel = { type: 'path', i: +t.dataset.i }; render(); return; }
    if (act === 'outline') { drag = { act, edge: t.dataset.edge, start: c, orig: { ...L.outline }, before }; pop.hidden = true; }
    else {
      const z = zoneById(t.dataset.id);
      sel = { type: 'zone', id: z.id };
      if (act === 'link') { drag = { act, from: z, before }; svg.classList.add('linking'); }
      else drag = { act, edge: t.dataset.edge, start: c, z, orig: { ...z }, before, moved: false };
      renderList(); renderPlan();
    }
    svg.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });

  svg.addEventListener('pointermove', (ev) => {
    if (!drag) return;
    const c = cellAt(ev);
    if (drag.act === 'link') {
      svg.querySelector('.draft')?.remove();
      const R = px(drag.from);
      mk('line', { x1: R.x + R.w / 2, y1: R.y + R.h / 2, x2: c.x * CELL, y2: c.y * CELL, class: 'draft' }, svg);
      pop.hidden = true;
      return;
    }
    const dx = Math.round(c.x - drag.start.x), dy = Math.round(c.y - drag.start.y), o = drag.orig;
    const target = drag.act === 'outline' ? L.outline : drag.z;
    if (dx || dy) { drag.moved = true; pop.hidden = true; }
    if (drag.act === 'move') {
      target.x = clamp(o.x + dx, 0, G.w - o.w); target.y = clamp(o.y + dy, 0, G.h - o.h);
    } else {
      const e = drag.edge;
      if (e === 'n') { const y = clamp(o.y + dy, 0, o.y + o.h - MIN); target.y = y; target.h = o.h + o.y - y; }
      if (e === 's' || e === 'se') target.h = clamp(o.h + dy, MIN, G.h - o.y);
      if (e === 'w') { const x = clamp(o.x + dx, 0, o.x + o.w - MIN); target.x = x; target.w = o.w + o.x - x; }
      if (e === 'e' || e === 'se') target.w = clamp(o.w + dx, MIN, G.w - o.x);
    }
    renderPlan();
  });

  function endDrag(ev) {
    if (!drag) return;
    const d = drag; drag = null;
    svg.classList.remove('linking');
    if (d.act === 'link') {
      svg.querySelector('.draft')?.remove();
      const to = zoneAt(cellAt(ev));
      if (to && to.id !== d.from.id && !L.paths.some((p) => (p.from_zone === d.from.id && p.to_zone === to.id) || (p.from_zone === to.id && p.to_zone === d.from.id))) {
        L.paths.push({ from_zone: d.from.id, to_zone: to.id });
        sel = { type: 'path', i: L.paths.length - 1 };
      }
    }
    commit(d.before);
  }
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);
  svg.addEventListener('dblclick', () => { $('#pName')?.focus(); $('#pName')?.select(); });

  // ---------- Add zone menu ----------
  function openMenu(anchor) {
    if (!menu.hidden) return;
    sel = null; render();
    menu.hidden = false;
    const a = anchor.getBoundingClientRect(), b = wrap.getBoundingClientRect();
    const fab = anchor.id === 'fab';
    menu.style.left = clamp(fab ? a.right - b.left - menu.offsetWidth : a.left - b.left + a.width / 2 - menu.offsetWidth / 2, 8, wrap.clientWidth - menu.offsetWidth - 8) + 'px';
    menu.style.top = (fab ? a.top - b.top - menu.offsetHeight - 8 : a.bottom - b.top + 8) + 'px';
    $('button', menu)?.focus();
  }
  function closeMenu() { menu.hidden = true; }
  $('#start').onclick = (e) => openMenu(e.currentTarget);
  $('#fab').onclick = (e) => openMenu(e.currentTarget);
  $$('[data-role]', menu).forEach((b) => (b.onclick = () => addZone(b.dataset.role)));
  const outside = (e) => { if (!menu.hidden && !e.target.closest('#menu,#start,#fab')) closeMenu(); };
  document.addEventListener('pointerdown', outside);

  // ---------- keyboard ----------
  function onKey(e) {
    const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName);
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if (mod && e.key.toLowerCase() === 'y' && !typing) { e.preventDefault(); redo(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && !typing && sel) { e.preventDefault(); removeSelection(); }
    else if (e.key === 'Escape') { if (typing) document.activeElement.blur(); else if (!menu.hidden) closeMenu(); else { sel = null; render(); } }
  }
  addEventListener('keydown', onKey);
  const onResize = () => renderPop();
  addEventListener('resize', onResize);

  $('#undo').onclick = undo; $('#redo').onclick = redo;
  $('#golive').onclick = async () => {
    $('#golive').disabled = true; $('#golive').textContent = 'Starting cameras…';
    try { await api('/api/live/start', { method: 'POST' }); location.hash = '#/live'; }
    catch (e) { if (e.data?.problems) problems = e.data.problems; render(); }
  };
  $('#stoplive').onclick = async () => {
    await api('/api/live/stop', { method: 'POST' });
    ctx.live = false; await ctx.refreshShell(); renderChecks();
  };

  render();
  return () => {
    removeEventListener('keydown', onKey);
    removeEventListener('resize', onResize);
    document.removeEventListener('pointerdown', outside);
    clearTimeout(saveTimer);
    if (saveState === 'Saving…') api('/api/layout', { method: 'PUT', body: L }).catch(() => {});
  };
}
