'use strict';
const $ = id => document.getElementById(id);
// Keep tokens in this tab's memory; never persist new tokens in localStorage.
localStorage.removeItem('jit.token');
const state = {
  baseUrl: localStorage.getItem('jit.baseUrl') || window.location.origin,
  token: '', rules: [], busy: new Set(), connected: false, editing: null,
};
$('baseUrl').value = state.baseUrl;
$('connectBtn').addEventListener('click', () => loadRules(true));
$('addApp').addEventListener('click', () => openEditor());
$('cancelApp').addEventListener('click', () => { $('appForm').hidden = true; });
$('appForm').addEventListener('submit', saveApp);

function saveSettings() {
  const next = $('baseUrl').value.trim().replace(/\/+$/, '') || window.location.origin;
  const url = new URL(next);
  if (!['http:', 'https:'].includes(url.protocol) || url.search || url.hash || url.username || url.password) {
    throw new Error('Enter an HTTP(S) API URL without credentials, query or fragment');
  }
  state.baseUrl = next;
  state.token = $('token').value.trim();
  localStorage.setItem('jit.baseUrl', state.baseUrl);
}
async function api(path, options = {}) {
  saveSettings();
  const res = await fetch(state.baseUrl + path, {
    method: options.method || 'GET',
    headers: {Authorization: `Bearer ${state.token}`, 'Content-Type': 'application/json'},
    body: options.body ? JSON.stringify(options.body) : undefined,
    redirect: 'error',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok !== true) throw new Error(data.error || `API returned ${res.status}`);
  return data;
}
async function loadRules(showSuccess = false) {
  setConnected(null, 'Connecting…');
  try {
    state.rules = (await api('/rules')).rules;
    state.connected = true;
    setConnected(true, 'Connected');
    if (showSuccess) toast('Rules loaded');
  } catch (error) {
    state.connected = false;
    state.rules = [];
    $('appForm').hidden = true;
    setConnected(false, 'Connection failed');
    toast(error.message, true);
  }
  render();
}
async function act(rule, action) {
  let body;
  if (action === 'edit') { openEditor(rule); return; }
  if (action === 'delete' && !confirm(`Remove ${rule.name}? Its port will remain blocked.`)) return;
  if (action === 'allow-temporary') {
    const value = prompt('Allow for how many minutes? (1–240)', '30');
    if (value === null) return;
    const minutes = Number(value);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 240) {
      toast('Enter a whole number from 1 to 240', true); return;
    }
    body = {minutes};
  }
  state.busy.add(rule.id); render();
  try {
    const path = `/rules/${encodeURIComponent(rule.id)}` + (action === 'delete' ? '' : `/${action}`);
    await api(path, {method: action === 'delete' ? 'DELETE' : 'POST', body});
    await loadRules();
    toast(action === 'delete' ? 'App removed; port remains blocked' : 'Access updated');
  } catch (error) { toast(error.message, true); }
  finally { state.busy.delete(rule.id); render(); }
}
function openEditor(rule = null) {
  state.editing = rule;
  $('appForm').reset();
  $('formError').textContent = '';
  $('formTitle').textContent = rule ? 'Edit app' : 'Add app';
  for (const [id, key] of [['appId','id'], ['appName','name'], ['appPort','port'], ['appProto','proto'], ['appDescription','description']]) {
    $(id).value = rule ? rule[key] : (key === 'proto' ? 'tcp' : '');
    $(id).disabled = !!rule && ['id', 'port', 'proto'].includes(key);
  }
  $('appForm').hidden = false;
  $('appName').focus();
}
async function saveApp(event) {
  event.preventDefault();
  const data = {name: $('appName').value.trim(), description: $('appDescription').value.trim()};
  if (!state.editing) Object.assign(data, {id: $('appId').value.trim(), port: Number($('appPort').value), proto: $('appProto').value});
  $('saveApp').disabled = true;
  $('cancelApp').disabled = true;
  $('addApp').disabled = true;
  try {
    await api(state.editing ? `/rules/${encodeURIComponent(state.editing.id)}` : '/rules', {
      method: state.editing ? 'PATCH' : 'POST', body: data,
    });
    $('appForm').hidden = true;
    await loadRules();
    toast(state.editing ? 'App updated' : 'App added and blocked');
  } catch (error) { $('formError').textContent = error.message; }
  finally {
    $('saveApp').disabled = false;
    $('cancelApp').disabled = false;
    $('addApp').disabled = !state.connected;
  }
}
function button(text, className, disabled, onClick) {
  const el = document.createElement('button');
  el.className = `btn ${className}`; el.textContent = text;
  el.disabled = disabled; el.addEventListener('click', onClick);
  return el;
}
function render() {
  $('addApp').disabled = !state.connected || $('saveApp').disabled;
  $('rulesGrid').replaceChildren();
  $('emptyState').hidden = state.rules.length > 0;
  $('emptyState').textContent = state.connected ? 'No apps yet. Add your first app.' : 'Connect to the API to load firewall rules.';
  for (const rule of state.rules) {
    const card = document.createElement('article');
    card.className = 'panel rule-card';
    // All API text is assigned through textContent, never inline handlers or HTML.
    const title = document.createElement('h2'); title.className = 'rule-name'; title.textContent = rule.name;
    const desc = document.createElement('p'); desc.className = 'rule-desc'; desc.textContent = rule.description || 'No description';
    const status = document.createElement('span'); status.className = `pill ${rule.blocked ? 'bad' : 'ok'}`;
    status.textContent = rule.blocked ? 'Blocked' : 'Allowed';
    const meta = document.createElement('div'); meta.className = 'rule-meta';
    meta.textContent = `${rule.id} · ${rule.proto.toUpperCase()} · Port ${rule.port}`;
    if (rule.expires_at) meta.textContent += ` · Reblocks ${new Date(rule.expires_at * 1000).toLocaleString()}`;
    const actions = document.createElement('div'); actions.className = 'rule-actions';
    const busy = state.busy.has(rule.id) || !state.connected;
    for (const [text, action, cls, disabled] of [
      ['Allow', 'allow', 'green', busy || (rule.allowed && !rule.expires_at)],
      ['Block', 'block', 'red', busy || (rule.blocked && !rule.expires_at)],
      ['Allow temporarily', 'allow-temporary', 'ghost wide', busy],
      ['Edit', 'edit', 'ghost', busy], ['Remove', 'delete', 'red', busy],
    ]) actions.append(button(text, cls, disabled, () => act(rule, action)));
    card.append(title, desc, status, meta, actions); $('rulesGrid').append(card);
  }
}
function setConnected(ok, text) {
  $('connectionPill').className = 'pill' + (ok === true ? ' ok' : ok === false ? ' bad' : '');
  $('connectionPill').textContent = text;
}
let toastTimer;
function toast(message, error = false) {
  $('toast').textContent = message;
  $('toast').className = `toast show${error ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').className = 'toast'; }, 4000);
}
render();
setInterval(() => { if (state.connected && !state.busy.size && $('appForm').hidden) loadRules(); }, 15000);
