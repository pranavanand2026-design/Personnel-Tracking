// Live view: the saved layout, read-only, with live counts from the zone workers.
// Unknown is never zero: no camera, offline or stale data all show "Unknown".
// People are anonymous IDs (P-0001) linked across zones by appearance; click one
// (in the lists or on the video) for their sightings and last known location.
import { api, $, $$, h, esc } from './api.js';
import { CELL, mk, px, pathD, drawDoor, roleOf, isOutside, isDoor } from './plan.js';

const LOW_RELIABILITY = 0.30;

export async function mountLive(root, ctx) {
  const [layout, cameras] = await Promise.all([api('/api/layout'), api('/api/cameras')]);
  const roles = ctx.roles, G = layout.grid, W = G.w * CELL, H = G.h * CELL;
  const cams = Object.fromEntries(cameras.map((c) => [c.id, c]));
  const zones = layout.zones.map((z) => ({ ...z, role: roleOf(roles, z.role), live: null }));
  const Z = Object.fromEntries(zones.map((z) => [z.id, z]));
  let selected = null, ws = null, closed = false, live = ctx.live, people = {}, openPerson = null, logTimer = null;

  root.append(h(`<section>
    <div class="live-top">
      <div class="figures" aria-live="polite">
        <div class="fig"><span class="n" id="f-in">–</span><span class="l" id="f-in-l">In the building</span></div>
        <div class="fig"><span class="n" id="f-mu">–</span><span class="l" id="f-mu-l">At muster point</span></div>
      </div>
    </div>
    <p class="site-status" id="status"></p>
    <div class="live">
      <section class="plan-wrap" id="planWrap" aria-label="Site plan">
        <svg class="plan" id="lplan" viewBox="0 0 ${W} ${H}" role="img" aria-label="Site plan with live counts"><g id="world"></g></svg>
        <svg id="mini" viewBox="0 0 ${W} ${H}" aria-hidden="true"></svg>
        <div class="zcard" id="card" hidden>
          <div class="zcard-head">
            <div><h2 id="c-name"></h2><span id="c-cam"></span></div>
            <button class="btn" id="back">Back to site</button>
          </div>
          <div class="feed" id="feed-box"><img id="feed" alt="Live camera view with detection boxes"></div>
          <dl class="kpis">
            <div><dt>Present now</dt><dd id="s-n">–</dd></div>
            <div><dt>Mean confidence</dt><dd id="s-conf">–</dd></div>
            <div><dt>Frame rate</dt><dd id="s-fps">–</dd></div>
            <div><dt>Detection time</dt><dd id="s-ms">–</dd></div>
          </dl>
          <div class="people" id="people">
            <div><h3>In view</h3><ul class="plist" id="p-in"></ul></div>
            <div><h3>Last seen here</h3><ul class="plist" id="p-last"></ul></div>
          </div>
          <div class="plog" id="plog" hidden>
            <button class="back" id="pl-close">← Back</button>
            <div class="pid-row"><span class="pid" id="pl-name"></span><span class="chip" id="pl-chip"></span></div>
            <p class="where" id="pl-where"></p>
            <ol class="timeline" id="pl-list"></ol>
          </div>
        </div>
        <div class="legend">
          <span><i></i>General zone</span><span><i class="d"></i>Entry door</span>
          <span><i class="o"></i>Muster point</span><span><i class="u"></i>Unknown</span><span><i class="p"></i>Path</span>
        </div>
      </section>
      <aside class="rail"><h2>Zones</h2><ul id="rail"></ul></aside>
    </div></section>`));

  const world = $('#world'), mini = $('#mini');

  // ---------- state per zone ----------
  function state(z) {
    const cam = cams[z.camera_id], s = z.live;
    if (!cam) return { kind: 'unknown', text: 'Unknown: no camera' };
    if (!live) return { kind: 'unknown', text: 'Unknown: site not live' };
    if (cam.offline) return { kind: 'unknown', text: 'Unknown: camera offline' };
    if (!s || s.error) return { kind: 'unknown', text: s?.error ? 'Unknown: camera error' : 'Unknown: no data yet' };
    if (s.status === 'offline') return { kind: 'unknown', text: 'Unknown: camera offline' };
    if (s.status === 'stale') return { kind: 'unknown', text: `Unknown: data delayed ${Math.round(s.age_s)} s` };
    if (s.low_confidence_share > LOW_RELIABILITY)
      return { kind: 'low', text: `Low reliability: ${Math.round(s.low_confidence_share * 100)}% under 0.4` };
    return { kind: 'ok', text: 'OK' };
  }
  const count = (z) => (state(z).kind === 'unknown' ? null : z.live.people_in_view);

  // ---------- build plan ----------
  function build() {
    const o = layout.outline;
    if (o) { const O = px(o); mk('rect', { x: O.x, y: O.y, width: O.w, height: O.h, class: 'bldg' }, world); }
    for (const p of layout.paths) {
      const a = Z[p.from_zone], b = Z[p.to_zone];
      if (a && b) mk('path', { d: pathD(a, b), class: 'path' }, world);
    }
    for (const z of zones) if (isDoor(z.role)) drawDoor(z, o, world);
    for (const z of zones) {
      const R = px(z), out = isOutside(z.role), cam = cams[z.camera_id];
      const g = mk('g', { class: 'zone' + (out ? ' outside' : ''), tabindex: 0, role: 'button', 'aria-label': 'Open ' + z.name }, world);
      mk('rect', { x: R.x, y: R.y, width: R.w, height: R.h, rx: out ? 12 : 3, class: 'r' }, g);
      mk('text', { x: R.x + 12, y: R.y + 27, class: 'zname' }, g, z.name);
      mk('text', { x: R.x + 12, y: R.y + 45, class: 'zkick' }, g, z.role.label.toUpperCase());
      // Tag bottom-right, clear of the name; top-right only when the zone is too short
      const tw = 120, short = R.h < 100;
      const tx = Math.max(R.x + 8, R.x + R.w - tw - 12), ty = short ? R.y + 12 : R.y + R.h - 42;
      const t = mk('g', { class: 'tag' }, g);
      mk('rect', { x: tx, y: ty, width: tw, height: 30, rx: 3 }, t);
      z.tagText = mk('text', { x: tx + tw / 2, y: ty + 21, 'text-anchor': 'middle' }, t, '');
      z.g = g;
      g.addEventListener('click', () => open(z.id));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(z.id); } });
      z.m = mk('rect', { x: R.x, y: R.y, width: R.w, height: R.h, rx: out ? 20 : 0 }, mini);
      z.mt = mk('text', { x: R.x + R.w / 2, y: R.y + R.h / 2 + 24, 'text-anchor': 'middle' }, mini, '');

      const li = document.createElement('li');
      const b = h(`<button class="ri ${out ? 'outside' : ''}"><span class="nm">${esc(z.name)}</span><span class="ct">–</span>
        <span class="cm">${esc(cam ? cam.name : 'No camera')}</span><span class="st"></span></button>`);
      b.addEventListener('click', () => open(z.id));
      li.append(b); $('#rail').append(li);
      z.ri = b; z.riCt = $('.ct', b); z.riSt = $('.st', b);
    }
    if (!zones.length) $('#rail').append(h('<li class="muted">No zones yet. Add them in Layout.</li>'));
  }

  // ---------- render ----------
  function figure(id, list, label) {
    const known = list.filter((z) => count(z) !== null), unknown = list.length - known.length;
    const n = known.reduce((a, z) => a + count(z), 0), el = $('#' + id);
    el.classList.toggle('unknown', list.length > 0 && !known.length);
    el.textContent = !list.length ? '–' : !known.length ? 'Unknown' : unknown ? `${n}+?` : n;
    $('#' + id + '-l').textContent = unknown && known.length ? `${label}, ${unknown} zone${unknown > 1 ? 's' : ''} unknown` : label;
  }

  function render() {
    figure('f-in', zones.filter((z) => !isOutside(z.role)), `In ${ctx.org?.site_name || 'the building'}`);
    const muster = zones.filter((z) => z.role.behaviour.counts === 'arrivals');
    $('#f-mu').parentElement.hidden = !muster.length;  // a muster point is optional
    figure('f-mu', muster, 'At muster point');

    const st = $('#status');
    const critical = zones.filter((z) => ['in_out', 'arrivals'].includes(z.role.behaviour.counts) && state(z).kind === 'unknown');
    const other = zones.filter((z) => state(z).kind === 'unknown' && !critical.includes(z));
    st.hidden = live && !critical.length && !other.length;
    if (!live) { st.className = 'site-status alarm-t'; st.innerHTML = 'Not live. <a href="#/layout">Go live from Layout</a>.'; }
    else if (critical.length) { st.className = 'site-status alarm-t'; st.textContent = `Unknown: ${critical.map((z) => z.name).join(', ')}. Totals can't be confirmed.`; }
    else if (other.length) { st.className = 'site-status warn-t'; st.textContent = `Unknown: ${other.map((z) => z.name).join(', ')}.`; }

    for (const z of zones) {
      const s = state(z), n = count(z);
      for (const el of [z.g, z.ri]) {
        el.classList.toggle('unknown', s.kind === 'unknown');
        el.classList.toggle('low', s.kind === 'low');
      }
      z.ri.classList.toggle('sel', selected === z.id);
      z.tagText.textContent = n === null ? 'Unknown' : 'Present: ' + n;
      z.riCt.textContent = n === null ? '?' : n;
      z.riSt.textContent = s.text;
      z.riSt.className = 'st ' + (s.kind === 'unknown' ? 'alarm' : s.kind === 'low' ? 'warn' : '');
      z.m.setAttribute('class', (selected === z.id ? 'sel ' : '') + (s.kind === 'unknown' ? 'unknown' : ''));
      z.mt.textContent = n === null ? '?' : n;
    }
    if (selected) renderCard(Z[selected]);
  }

  function renderCard(z) {
    const s = z.live || {}, n = count(z);
    $('#s-n').textContent = n === null ? 'Unknown' : n;
    const conf = $('#s-conf');
    conf.textContent = n && s.mean_confidence != null ? (+s.mean_confidence).toFixed(2) : '–';
    conf.className = s.low_confidence_share > LOW_RELIABILITY ? 'warn' : '';
    $('#s-fps').textContent = s.fps != null && n !== null ? s.fps.toFixed(0) + ' fps' : '–';
    $('#s-ms').textContent = s.inference_ms != null && n !== null ? Math.round(s.inference_ms) + ' ms' : '–';
    renderPeople(z, n);
  }

  // ---------- people ----------
  const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
  const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 60 ? `${Math.round(s)} s ago` : `${Math.round(s / 60)} min ago`; };
  const personBtn = (p, note) => `<li><button class="pbtn" data-p="${esc(p)}"><b>${esc(p)}</b><span>${esc(note)}</span></button></li>`;

  function renderPeople(z, n) {
    const pz = people[z.id] || { in_view: [], last_seen: [] };
    const waiting = n == null ? 0 : Math.max(0, n - pz.in_view.length);
    $('#p-in').innerHTML = pz.in_view.map((x) => personBtn(x.person, `here ${ago(x.since).replace(' ago', '')}`)).join('')
      + (waiting ? `<li class="muted">${waiting} not identified yet</li>` : '')
      + (!pz.in_view.length && !waiting ? '<li class="muted">Nobody</li>' : '');
    const SHOW = 8, more = pz.last_seen.length - SHOW;
    $('#p-last').innerHTML = pz.last_seen.slice(0, SHOW).map((x) => personBtn(x.person, ago(x.at))).join('')
      + (more > 0 ? `<li class="muted">+${more} more</li>` : '')
      || '<li class="muted">Nobody in the last 10 minutes</li>';
  }

  async function showPerson(name) {
    openPerson = name;
    clearTimeout(logTimer);
    let p;
    try { p = await api('/api/people/' + encodeURIComponent(name)); }
    catch (err) { p = null; $('#pl-name').textContent = name; $('#pl-chip').textContent = ''; $('#pl-where').textContent = err.message; $('#pl-list').innerHTML = ''; }
    if (openPerson !== name) return;
    $('#people').hidden = true; $('#plog').hidden = false;
    if (p) {
      $('#pl-name').textContent = p.person;
      const chip = $('#pl-chip');
      chip.textContent = p.in_view ? 'In view' : `Last seen ${ago(p.last_seen)}`;
      chip.className = 'chip ' + (p.in_view ? 'on' : '');
      $('#pl-where').innerHTML = `${p.in_view ? 'Now in' : 'Last known location'} <b>${esc(p.zone)}</b>`;
      $('#pl-list').innerHTML = [...p.log].reverse().map((e, i) => {
        const dur = e.end ? `${Math.max(1, Math.round(e.end - e.start))} s` : 'now';
        const how = e.new ? 'First seen'
          : e.from_zone && e.from_zone !== e.zone ? `From ${e.from_zone} · ${Math.max(0, Math.round(e.gap))} s walk`
          : 'Back in view';
        return `<li class="${i === 0 ? 'cur' : ''} ${e.uncertain ? 'unc' : ''}">
          <span class="t">${clock(e.start)}</span>
          <div><b>${esc(e.zone)}</b> <span class="dur">${dur}</span>
          <span class="how">${esc(how)}${e.uncertain ? ' · <em>uncertain link</em>' : ''}</span></div></li>`;
      }).join('');
      logTimer = setTimeout(() => openPerson === name && showPerson(name), 2000);
    }
  }
  function closePerson() {
    openPerson = null; clearTimeout(logTimer);
    $('#plog').hidden = true; $('#people').hidden = false;
  }
  $('#pl-close').addEventListener('click', closePerson);
  $('#card').addEventListener('click', (e) => { const b = e.target.closest('[data-p]'); if (b) showPerson(b.dataset.p); });
  // click a person on the video: find their box in the latest state
  $('#feed').addEventListener('click', (e) => {
    const z = Z[selected], img = e.currentTarget, tracks = z?.live?.tracks || [];
    const r = img.getBoundingClientRect(), ar = (img.naturalWidth / img.naturalHeight) || 16 / 9;
    const w = Math.min(r.width, r.height * ar), hgt = w / ar;  // object-fit: contain
    const x = (e.clientX - r.left - (r.width - w) / 2) / w, y = (e.clientY - r.top - (r.height - hgt) / 2) / hgt;
    const hit = tracks.filter((t) => t.person && x >= t.box[0] && x <= t.box[2] && y >= t.box[1] && y <= t.box[3])
      .sort((a, b) => (a.box[2] - a.box[0]) * (a.box[3] - a.box[1]) - (b.box[2] - b.box[0]) * (b.box[3] - b.box[1]))[0];
    if (hit) showPerson(hit.person);
  });

  // ---------- zoom + stream ----------
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  function open(id) {
    if (selected === id) return;
    closePerson();
    const z = Z[id], R = px(z), cam = cams[z.camera_id];
    selected = id;
    const s = Math.min(3, Math.min(W / R.w, H / R.h) * 0.8);
    world.style.transform = `translate(${W / 2 - s * (R.x + R.w / 2)}px,${H / 2 - s * (R.y + R.h / 2)}px) scale(${s})`;
    $('#planWrap').classList.add('zoomed');
    $('#c-name').textContent = z.name;
    $('#c-cam').textContent = cam ? cam.name : 'No camera';
    const img = $('#feed'); img.removeAttribute('src');
    setTimeout(() => {
      if (selected !== id) return;
      $('#card').hidden = false;
      const st = state(z);
      img.hidden = st.kind === 'unknown';
      $('#feed-box').firstChild.nodeType === 3 && $('#feed-box').firstChild.remove();
      if (st.kind === 'unknown') $('#feed-box').prepend(document.createTextNode(st.text));
      else img.src = `/zones/${id}/stream?t=${Date.now()}`;  // opening the stream starts encoding
    }, reduced() ? 0 : 420);
    render();
  }
  function close() {
    closePerson();
    selected = null;
    world.style.transform = '';
    $('#planWrap').classList.remove('zoomed');
    $('#card').hidden = true;
    $('#feed').removeAttribute('src');  // closes the MJPEG connection
    render();
  }
  $('#back').addEventListener('click', close);
  const onKey = (e) => { if (e.key === 'Escape' && selected) close(); };
  addEventListener('keydown', onKey);

  // ---------- live data ----------
  function connect() {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      live = msg.live;
      const by = Object.fromEntries(msg.zones.map((s) => [s.zone_id, s]));
      for (const z of zones) z.live = by[z.id] || null;
      people = msg.people || {};
      render();
    };
    ws.onclose = () => {
      if (closed) return;  // view was left
      for (const z of zones) z.live = null;  // never keep showing old numbers
      people = {};
      render();
      setTimeout(connect, 1500);
    };
  }

  build(); render(); connect();
  return () => {
    closed = true; ws?.close(); clearTimeout(logTimer);
    removeEventListener('keydown', onKey);
    $('#feed')?.removeAttribute('src');
  };
}
