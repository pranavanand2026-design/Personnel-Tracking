// App shell: routing between login, setup, layout editor, cameras, live view, about.
import { api, $, $$, h, esc } from './api.js';
import { mountEditor } from './editor.js';
import { mountCameras } from './cameras.js';
import { mountLive } from './live.js';

const view = $('#view');
let unmount = null;
const ctx = { org: null, live: false, roles: [], user: null };

async function refreshShell() {
  const { org, live } = await api('/api/org');
  ctx.org = org; ctx.live = live;
  $('#bar').hidden = false;
  $('#brand-site').textContent = org ? org.site_name : 'New site';
  $('#brand-org').textContent = org ? org.name : '';
  $('#who').textContent = ctx.user || '';
  $('#live-dot').hidden = !live;
  document.title = (org ? org.site_name + ' · ' : '') + 'Site Monitor';
}
ctx.refreshShell = refreshShell;

async function route() {
  if (unmount) { unmount(); unmount = null; }
  view.innerHTML = '';
  const name = (location.hash.replace(/^#\//, '') || '').split('/')[0];

  const auth = await api('/api/auth/state');
  ctx.user = auth.user;
  if (!auth.user) { $('#bar').hidden = true; return loginView(auth.admin_exists); }
  if (!ctx.roles.length) ctx.roles = await api('/api/roles');
  await refreshShell();
  if (!ctx.org && name !== 'setup' && name !== 'about') { location.hash = '#/setup'; return; }
  if (!name || name === 'login') { location.hash = ctx.live ? '#/live' : '#/layout'; return; }

  $$('#nav a').forEach((a) => a.classList.toggle('on', a.dataset.r === name));
  if (name === 'setup') setupView();
  else if (name === 'layout') unmount = await mountEditor(view, ctx);
  else if (name === 'cameras') unmount = await mountCameras(view, ctx);
  else if (name === 'live') unmount = await mountLive(view, ctx);
  else if (name === 'about') aboutView();
  else location.hash = '#/layout';
}

// ---------- login ----------
function loginView(adminExists) {
  view.append(h(`<section class="narrow">
    <h1>Sign in</h1>
    <p class="muted">Site Monitor runs on this computer. Use the local admin account.</p>
    ${adminExists ? '' : `<p class="alarm-t">No admin account exists yet. In a terminal in the project folder, run<br>
      <code>.venv/bin/python -m counter.web.admin</code><br>then reload this page.</p>`}
    <form class="form" id="login">
      <label class="f"><span>Username</span><input name="username" autocomplete="username" required></label>
      <label class="f"><span>Password</span><input name="password" type="password" autocomplete="current-password" required></label>
      <p class="error" id="err"></p>
      <button class="btn" ${adminExists ? '' : 'disabled'}>Sign in</button>
    </form></section>`));
  $('#login').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api('/api/auth/login', { method: 'POST', body: { username: f.get('username'), password: f.get('password') } });
      if (location.hash === '#/') route(); else location.hash = '#/';
    } catch (err) { $('#err').textContent = err.message; }
  });
}

// ---------- organisation setup ----------
// First run: name the site, then draw zones in Layout (cameras are added there).
// Later: rename, or start over / load the demo site.
function setupView() {
  const org = ctx.org;
  view.append(h(`<section class="narrow">
    <ol class="steps"><li class="on">Name your site</li><li>Draw zones and add cameras</li><li>Go live</li></ol>
    <h1>${org ? 'Your site' : 'Set up your site'}</h1>
    <form class="form" id="org">
      <label class="f"><span>Organisation</span><input name="name" required value="${esc(org?.name || '')}" placeholder="e.g. Royal Hospital"></label>
      <label class="f"><span>Site</span><input name="site_name" required value="${esc(org?.site_name || '')}" placeholder="e.g. Building A, Level 1"></label>
      <p class="error" id="err"></p>
      <button class="btn go">${org ? 'Save' : 'Continue to layout'}</button>
    </form>
    <div class="or">or</div>
    <button class="btn" id="demo">Load the demo site</button>
    <p class="muted small">A hospital floor with four recorded cameras, ready to go live.</p>
    ${org ? '<button class="link danger" id="reset">Start a new site from scratch</button>' : ''}
    <p class="error" id="err2"></p></section>`));
  $('#org').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target), body = { name: f.get('name'), site_name: f.get('site_name') };
    try {
      if (org) { await api('/api/org', { method: 'PUT', body }); await refreshShell(); $('#err').textContent = 'Saved.'; }
      else { await api('/api/org', { method: 'POST', body }); location.hash = '#/layout'; }
    } catch (err) { $('#err').textContent = err.message; }
  });
  $('#demo').addEventListener('click', async () => {
    if (org && !confirm('Replace this site, its cameras and its layout with the demo site?')) return;
    try { await api('/api/demo/load', { method: 'POST' }); location.hash = '#/layout'; }
    catch (err) { $('#err2').textContent = err.message; }
  });
  $('#reset')?.addEventListener('click', async () => {
    if (!confirm('Delete this site’s zones and cameras and start again?')) return;
    try {
      await api('/api/org', { method: 'POST', body: { name: org.name, site_name: org.site_name } });
      location.hash = '#/layout';
    } catch (err) { $('#err2').textContent = err.message; }
  });
}

// ---------- about ----------
function aboutView() {
  view.append(h(`<section class="prose">
    <h1>About</h1>
    <p>Site Monitor counts people in each zone of a site from one camera per zone, for evacuation headcounts.
      Detection runs on this computer with YOLO11n; video stays local and is only streamed for the zone you open.</p>
    <h2>Demo footage</h2>
    <p>Demo cameras play four cameras from scene 081 of NVIDIA's PhysicalAI-SmartSpaces dataset (a synthetic hospital floor),
      synchronised to one clock so they behave like live cameras.</p>
    <p>NVIDIA PhysicalAI-SmartSpaces,
      <a href="https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces" target="_blank" rel="noopener">huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces</a>.
      Licensed under <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>. Videos unmodified.</p>
    <p class="muted">S. Wang et al., "The 8th AI City Challenge," CVPR Workshops 2024.</p>
    <h2>Software</h2>
    <p>Person detection: Ultralytics YOLO11n (AGPL-3.0). Typeface: Barlow (SIL Open Font License 1.1).</p>
  </section>`));
}

$('#logout').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' });
  location.hash = '#/login';
});
addEventListener('hashchange', route);
route();
