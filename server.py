#!/usr/bin/env python3
"""Lightweight web terminal with mobile-friendly virtual keys."""

import base64
import fcntl
import json
import os
import pty
import re
import secrets
import signal
import struct
import subprocess
import termios
import uuid

import tornado.ioloop
import tornado.web
import tornado.websocket

SHELL = os.environ.get("SHELL", "/usr/bin/bash")
PORT = int(os.environ.get("WEBTERMINAL_PORT", "7700"))
AUTH = os.environ.get("WEBTERMINAL_AUTH", "")  # user:pass
TMUX = "/usr/bin/tmux"


def _valid_session_name(name: str) -> bool:
    """Restrict tmux session names to safe characters."""
    return bool(re.match(r'^[a-zA-Z0-9_-]{1,64}$', name))


def _auto_session_name() -> str:
    return "auto-" + uuid.uuid4().hex[:8]

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Terminal</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:#1e1e1e;overflow:hidden;touch-action:manipulation;
  display:flex;flex-direction:column}
#terminal{flex:1;min-height:0}

/* --- compact key bar (default mode) --- */
#keys{
  display:flex;flex-wrap:wrap;gap:2px;padding:3px 2px;
  background:#2d2d2d;border-top:1px solid #444;
  padding-bottom:calc(4px + env(safe-area-inset-bottom));
  align-items:center;flex-shrink:0;
}
.k{
  background:#3c3c3c;color:#ccc;border:1px solid #555;border-radius:4px;
  padding:4px 8px;font-size:13px;font-family:monospace;
  cursor:pointer;user-select:none;white-space:nowrap;
  -webkit-tap-highlight-color:transparent;
  min-width:32px;text-align:center;flex-shrink:0;
}
.k.held{background:#0078d4;color:#fff;border-color:#0078d4}
.k.mod{background:#4a3c2a;border-color:#7a6a4a;color:#e0c080}
.k.mod.held{background:#d4a017;color:#000;border-color:#d4a017}

/* --- full keyboard --- */
#fullkb{
  display:none;flex-shrink:0;
  background:#2d2d2d;border-top:1px solid #444;
  padding:3px 2px;
  padding-bottom:calc(4px + env(safe-area-inset-bottom));
}
#fullkb .kbrow{display:flex;gap:2px;margin-bottom:2px;justify-content:center}
#fullkb .kbrow:last-child{margin-bottom:0}
#fullkb .fk{
  background:#3c3c3c;color:#ccc;border:1px solid #555;border-radius:4px;
  padding:10px 0;font-size:14px;line-height:1;font-family:monospace;
  cursor:pointer;user-select:none;text-align:center;
  white-space:nowrap;overflow:hidden;
  -webkit-tap-highlight-color:transparent;
  flex:1;min-width:0;max-width:42px;
}
#fullkb .fk.mod{background:#4a3c2a;border-color:#7a6a4a;color:#e0c080}
#fullkb .fk.mod.held{background:#d4a017;color:#000;border-color:#d4a017}
#fullkb .fk.wide{max-width:none;flex:1.6}
#fullkb .fk.space{max-width:none;flex:3}
#fullkb .fk.toggle{background:#2a4a3c;border-color:#4a7a6a;color:#80e0c0}
.arrow,.k.arrow{background:#1e3a4a!important;border-color:#3a6a8a!important;color:#70c8f0!important}
.del,.k.del{background:#4a2828!important;border-color:#7a4848!important;color:#f08888!important}
.pink,.k.pink{background:#4a2040!important;border-color:#7a4070!important;color:#f088c0!important}

/* position-based color flash on press */
@keyframes pos-flash{
  0%{background:hsl(var(--hue),80%,55%);color:#fff;border-color:hsl(var(--hue),80%,40%)}
  100%{background:#3c3c3c;color:#ccc;border-color:#555}
}
.fk.flash,.k.flash{animation:pos-flash .35s ease-out}

/* wide portrait (e.g. iPad): let keys stretch to fill width */
@media (orientation:portrait) and (min-width:600px){
  #fullkb .fk{max-width:none;padding:14px 0;font-size:16px}
}

/* split gap: hidden in portrait, visible in landscape */
#fullkb .split{display:none;flex-shrink:0}
@media (orientation:landscape){
  #fullkb .kbrow{max-width:none;justify-content:flex-start}
  #fullkb .fk{max-width:42px;padding:5px 0;font-size:13px}
  #fullkb .fk.wide{max-width:42px;flex:1}
  #fullkb .fk.space{max-width:none}
  #fullkb .split{display:block;flex:1;min-width:32px}
}
/* landscape on tablet-sized screens (e.g. iPad) */
@media (orientation:landscape) and (min-height:600px){
  #fullkb .fk{padding:10px 0;font-size:14px;max-width:56px}
  #fullkb .fk.wide{max-width:56px}
}

.hidden{display:none!important}

/* floating show-keyboard button */
#showkb{
  display:none;position:fixed;bottom:8px;left:8px;z-index:10;
  background:#3c3c3c;color:#80e0c0;border:1px solid #4a7a6a;border-radius:6px;
  padding:8px 12px;font-size:16px;font-family:monospace;
  cursor:pointer;user-select:none;-webkit-tap-highlight-color:transparent;
}
</style>
</head>
<body>
<div id="terminal"></div>
<div id="keys"></div>
<span id="showkb">⌨</span>
<div id="fullkb"></div>
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/lib/addon-web-links.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-webgl@0.18.0/lib/addon-webgl.min.js"></script>
<script>
const term = new Terminal({
  fontSize: 14, fontFamily: 'Menlo, Monaco, "Courier New", monospace',
  cursorBlink: true, theme: {background:'#1e1e1e'},
  allowProposedApi: true,
  scrollback: 10000,
  overviewRulerWidth: 0,
});
const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.loadAddon(new WebLinksAddon.WebLinksAddon());
term.open(document.getElementById('terminal'));
try {
  const webglAddon = new WebglAddon.WebglAddon();
  webglAddon.onContextLoss(() => webglAddon.dispose());
  term.loadAddon(webglAddon);
} catch(e) { console.warn('WebGL addon failed, using canvas fallback'); }
fitAddon.fit();

/* Touch-drag → synthesize WheelEvent so tmux mouse mode scrolls on mobile. */
(function() {
  const el = term.element;
  const target = el.querySelector('.xterm-screen') || el;
  const STEP = 24;
  let lastY = 0, active = false;
  el.addEventListener('touchstart', e => {
    active = e.touches.length === 1;
    if (active) lastY = e.touches[0].clientY;
  }, {passive: true});
  el.addEventListener('touchmove', e => {
    if (!active || e.touches.length !== 1) return;
    const y = e.touches[0].clientY;
    const dy = lastY - y;
    if (Math.abs(dy) < STEP) return;
    lastY = y;
    target.dispatchEvent(new WheelEvent('wheel', {
      deltaY: dy, deltaMode: 0,
      clientX: e.touches[0].clientX, clientY: y,
      bubbles: true, cancelable: true,
    }));
    e.preventDefault();
  }, {passive: false});
})();

const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
const params = new URLSearchParams(location.search);
const sessionLabel = params.get('attach') || params.get('name');
if (sessionLabel) document.title = sessionLabel;
const wsParams = new URLSearchParams();
['name','cwd','cmd','attach'].forEach(k => {
  if (params.has(k)) wsParams.set(k, params.get(k));
});
const wsQuery = wsParams.toString();
const ws = new WebSocket(`${proto}//${location.host}/ws${wsQuery ? '?' + wsQuery : ''}`);
ws.binaryType = 'arraybuffer';

ws.onopen = () => { sendResize(); term.focus(); };
ws.onmessage = e => {
  if (e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data));
  else term.write(e.data);
};
ws.onclose = () => {
  term.write('\r\n\x1b[31m[连接已断开]\x1b[0m\r\n');
  if (params.get('name') || params.get('attach'))
    term.write('\x1b[33m[刷新页面以重新连接]\x1b[0m\r\n');
};

function sendResize() {
  if (ws.readyState === 1)
    ws.send(JSON.stringify({type:'resize', cols:term.cols, rows:term.rows}));
}
term.onResize(() => sendResize());
let kbSwitching = false;
let fitTimer = 0;
function debouncedFit() {
  clearTimeout(fitTimer);
  fitTimer = setTimeout(() => {
    fitAddon.fit();
    if (kbSwitching) term.scrollToBottom();
  }, 50);
}
new ResizeObserver(() => debouncedFit()).observe(document.getElementById('terminal'));

/* Shrink body to visualViewport so soft keyboard never covers the terminal.
   Without this, iPad keeps layout viewport at full height and the cursor hides
   behind the native keyboard. ResizeObserver above re-fits xterm automatically. */
if (window.visualViewport) {
  const vv = window.visualViewport;
  const syncVV = () => { document.body.style.height = vv.height + 'px'; };
  vv.addEventListener('resize', syncVV);
  vv.addEventListener('scroll', syncVV);
  syncVV();
}

/* ========== shared modifier state ========== */
const modState = {ctrl:false, alt:false, shift:false};

function resetMods() {
  modState.ctrl = false; modState.alt = false; modState.shift = false;
  document.querySelectorAll('.mod').forEach(b => b.classList.remove('held'));
}

function sendData(raw) {
  if (ws.readyState !== 1) return;
  let data = raw;
  if (modState.shift && data.length === 1 && data >= 'a' && data <= 'z')
    data = data.toUpperCase();
  if (modState.ctrl && data.length === 1 && data >= ' ' && data <= '~')
    data = String.fromCharCode(data.toUpperCase().charCodeAt(0) & 0x1f);
  if (modState.alt) data = '\x1b' + data;
  ws.send(data);
}

function toggleMod(name) {
  modState[name] = !modState[name];
  document.querySelectorAll(`[data-mod="${name}"]`).forEach(
    b => b.classList.toggle('held', modState[name])
  );
}

/* ========== phone keyboard passthrough (compact bar mode) ========== */
term.onData(data => {
  if (ws.readyState !== 1) return;
  if (modState.ctrl || modState.alt || modState.shift) {
    let out = '';
    for (let i = 0; i < data.length; i++) {
      let ch = data[i];
      if (modState.shift && ch >= 'a' && ch <= 'z') ch = ch.toUpperCase();
      if (modState.ctrl && ch >= ' ' && ch <= '~')
        ch = String.fromCharCode(ch.toUpperCase().charCodeAt(0) & 0x1f);
      if (modState.alt) ch = '\x1b' + ch;
      out += ch;
    }
    ws.send(out);
    resetMods();
  } else {
    ws.send(data);
  }
});

/* ========== helper: bind touch/click without stealing focus ========== */
function flash(el) {
  el.classList.remove('flash');
  void el.offsetWidth; // reflow to restart animation
  el.classList.add('flash');
}

function bindBtn(el, fn, repeat) {
  el.addEventListener('animationend', () => el.classList.remove('flash'));
  if (repeat) {
    let timer = null, iv = null;
    function start() { flash(el); fn(); timer = setTimeout(() => { iv = setInterval(fn, 60); }, 400); }
    function stop() { clearTimeout(timer); clearInterval(iv); timer = iv = null; }
    el.addEventListener('touchstart', e => { e.preventDefault(); start(); });
    el.addEventListener('touchend', e => { e.preventDefault(); stop(); });
    el.addEventListener('touchcancel', () => stop());
    el.addEventListener('mousedown', e => { e.preventDefault(); start(); });
    el.addEventListener('mouseup', () => stop());
    el.addEventListener('mouseleave', () => stop());
  } else {
    el.addEventListener('touchstart', e => e.preventDefault());
    el.addEventListener('touchend', e => { e.preventDefault(); flash(el); fn(); });
    el.addEventListener('mousedown', e => e.preventDefault());
    el.addEventListener('click', e => { e.preventDefault(); flash(el); fn(); });
  }
}

/* ========== compact key bar ========== */
const keysDiv = document.getElementById('keys');
const compactKeys = [
  {label:'Esc',   send:'\x1b', cls:'pink'},
  {label:'Tab',   send:'\t'},
  {label:'Ctrl',  mod:'ctrl'},
  {label:'Alt',   mod:'alt'},
  {label:'Shift', mod:'shift'},
  {label:'\u2191',send:'\x1b[A', shifted:'\x1b[1;2A', cls:'arrow'},
  {label:'\u2193',send:'\x1b[B', shifted:'\x1b[1;2B', cls:'arrow'},
  {label:'\u2190',send:'\x1b[D', shifted:'\x1b[1;2D', cls:'arrow', repeat:true},
  {label:'\u2192',send:'\x1b[C', shifted:'\x1b[1;2C', cls:'arrow', repeat:true},
  {label:'Home',  send:'\x1b[H'},
  {label:'End',   send:'\x1b[F'},
  {label:'Enter', send:'\r', cls:'del'},
  {label:'C-c',   send:'\x03'},
  {label:'C-d',   send:'\x04'},
  {label:'C-z',   send:'\x1a'},
  {label:'C-l',   send:'\x0c'},
  {label:'C-a',   send:'\x01'},
  {label:'C-r',   send:'\x12'},
  {label:'Scr',   send:'\x02[', cls:'pink'},
];

compactKeys.forEach(k => {
  const btn = document.createElement('span');
  btn.className = 'k' + (k.mod ? ' mod' : '') + (k.cls ? ' ' + k.cls : '');
  btn.textContent = k.label;
  if (k.mod) btn.setAttribute('data-mod', k.mod);
  bindBtn(btn, () => {
    if (k.mod) { toggleMod(k.mod); }
    else {
      let d = (modState.shift && k.shifted) ? k.shifted : k.send;
      if (modState.alt) d = '\x1b' + d;
      if (modState.ctrl && d.length === 1)
        d = String.fromCharCode(d.charCodeAt(0) & 0x1f);
      if (ws.readyState === 1) ws.send(d);
      resetMods();
    }
    term.focus();
  }, k.repeat);
  keysDiv.appendChild(btn);
});

// toggle button in compact bar
const togBtn = document.createElement('span');
togBtn.className = 'k';
togBtn.textContent = '\u2328';
togBtn.title = 'Full keyboard';
bindBtn(togBtn, () => toggleFullKB(true));
keysDiv.appendChild(togBtn);

// position → hue: piecewise linear for balanced rainbow
function posToHue(t) {
  if (t < 0.35) return t / 0.35 * 80;            // red → yellow
  if (t < 0.5)  return 80 + (t-0.35) / 0.15 * 80; // yellow → cyan
  if (t < 0.7)  return 160 + (t-0.5) / 0.2 * 80;  // cyan → blue
  return 240 + (t-0.7) / 0.3 * 60;                 // blue → purple
}

// assign hues to compact bar keys
const compactBtns = keysDiv.querySelectorAll('.k');
compactBtns.forEach((btn, i) => {
  const t = i / Math.max(compactBtns.length - 1, 1);
  btn.style.setProperty('--hue', Math.round(posToHue(t)));
});

/* ========== full virtual keyboard ========== */
const fullkbDiv = document.getElementById('fullkb');
let fullkbActive = false;
let symLayer = false;
let capsLock = false;

const mainRows = [
  ['1','2','3','4','5','6','7','8','9','0'],
  ['q','w','e','r','t','y','u','i','o','p'],
  ['a','s','d','f','g','h','j','k','l'],
  ['z','x','c','v','b','n','m'],
];
const symRows = [
  ['!','@','#','$','%','^','&','*','(',')'],
  ['`','~','-','_','=','+','[',']','{','}'],
  ['\\','|',';',':',"\'",'\"',],
  ['/','?','<'],
];

function buildFullKB() {
  fullkbDiv.innerHTML = '';
  const rows = symLayer ? symRows : mainRows;
  const capsActive = capsLock && !symLayer;

  // row 0: Esc + numbers/symbols + ⌫
  addRow(rows[0].map(c => ({label: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c,
    send: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c})), {
    before:[{label:'Esc', send:'\x1b', cls:'pink'}],
    after:[{label:'\u232b', send:'\x7f', cls:'wide del', repeat:true}]
  });
  // row 1: Tab + letters/symbols + Sym/Main
  addRow(rows[1].map(c => ({label: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c,
    send: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c})), {
    before:[{label:'Tab', send:'\t'}],
    after:[{label: symLayer ? 'Main' : 'Sym', action:'sym', cls:'toggle'}]
  });
  // row 2: Caps + letters/symbols + ↵
  addRow(rows[2].map(c => ({label: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c,
    send: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c})), {
    before:[{label:'Caps', action:'caps', cls: capsLock ? 'mod held' : 'mod'}],
    after:[{label:'\u21b5', send:'\r', cls:'wide del'}],
  });
  // row 3: Shift + letters/symbols + ↑ , .
  const row3after = symLayer
    ? [{label:'Scr', send:'\x02[', cls:'pink'},{label:'Del', send:'\x1b[3~', cls:'pink'},{label:'>', send:'>'},{label:'PgU', send:'\x1b[5~', cls:'arrow'},{label:',', send:','},{label:'.', send:'.'}]
    : [{label:'\u2191', send:'\x1b[A', cls:'arrow'},{label:',', send:','},{label:'.', send:'.'}];
  addRow(rows[3].map(c => ({label: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c,
    send: capsActive && c >= 'a' && c <= 'z' ? c.toUpperCase() : c})), {
    before:[{label:'Shift', mod:'shift', cls:'mod'}],
    after: row3after,
    splitAt: symLayer ? 5 : undefined,
  });
  // row 4: ▼ Ctrl Alt [space] ← ↓ → ⌨
  addBottomRow();
  assignHues(fullkbDiv);
}

function assignHues(container) {
  const rows = container.querySelectorAll('.kbrow');
  const totalRows = rows.length;
  rows.forEach((row, ri) => {
    const keys = row.querySelectorAll('.fk');
    const totalCols = keys.length;
    keys.forEach((key, ci) => {
      const ry = totalRows > 1 ? ri / (totalRows - 1) : 0;
      const rx = totalCols > 1 ? ci / (totalCols - 1) : 0;
      const diag = (ry + rx) / 2;
      key.style.setProperty('--hue', Math.round(posToHue(diag)));
    });
  });
}

function makeSplit() {
  const sp = document.createElement('span');
  sp.className = 'split';
  return sp;
}

function addRow(keys, extra) {
  const row = document.createElement('div');
  row.className = 'kbrow';
  const allItems = [];
  if (extra && extra.before) extra.before.forEach(k => allItems.push(makeFK(k)));
  keys.forEach(k => allItems.push(makeFK(k)));
  if (extra && extra.after) extra.after.forEach(k => allItems.push(makeFK(k)));
  const mid = (extra && extra.splitAt != null) ? extra.splitAt : Math.ceil(allItems.length / 2);
  allItems.forEach((el, i) => {
    row.appendChild(el);
    if (i === mid - 1) row.appendChild(makeSplit());
  });
  fullkbDiv.appendChild(row);
}

function addBottomRow() {
  const row = document.createElement('div');
  row.className = 'kbrow';
  const left = [
    {label:'\u25bc', action:'hide', cls:'toggle'},
    {label:'Ctrl', mod:'ctrl', cls:'mod'},
    {label:'Alt', mod:'alt', cls:'mod'},
  ];
  const right = symLayer ? [
    {label:'\u2190', send:'\x1b[D', cls:'arrow', repeat:true},
    {label:'PgD', send:'\x1b[6~', cls:'arrow'},
    {label:'\u2192', send:'\x1b[C', cls:'arrow', repeat:true},
    {label:'\u2328', action:'toggle', cls:'toggle'},
  ] : [
    {label:'\u2190', send:'\x1b[D', cls:'arrow', repeat:true},
    {label:'\u2193', send:'\x1b[B', cls:'arrow'},
    {label:'\u2192', send:'\x1b[C', cls:'arrow', repeat:true},
    {label:'\u2328', action:'toggle', cls:'toggle'},
  ];
  left.forEach(k => row.appendChild(makeFK(k)));
  row.appendChild(makeFK({label:'', send:' ', cls:'space'}));
  right.forEach(k => row.appendChild(makeFK(k)));
  fullkbDiv.appendChild(row);
}

function makeFK(k) {
  const btn = document.createElement('span');
  btn.className = 'fk' + (k.cls ? ' ' + k.cls : '');
  btn.textContent = k.label;
  if (k.mod) btn.setAttribute('data-mod', k.mod);

  bindBtn(btn, () => {
    if (k.action === 'toggle') { toggleFullKB(false); return; }
    if (k.action === 'hide') { hideFullKB(); return; }
    if (k.action === 'sym') { symLayer = !symLayer; buildFullKB(); return; }
    if (k.action === 'caps') { capsLock = !capsLock; buildFullKB(); return; }
    if (k.mod) { toggleMod(k.mod); return; }

    let data = k.send;
    // Shift as one-shot modifier: uppercase letters, or send shifted arrow etc.
    if (modState.shift && data.length === 1 && data >= 'a' && data <= 'z')
      data = data.toUpperCase();
    if (modState.ctrl && data.length === 1 && data >= ' ' && data <= '~')
      data = String.fromCharCode(data.toUpperCase().charCodeAt(0) & 0x1f);
    if (modState.alt) data = '\x1b' + data;
    if (ws.readyState === 1) ws.send(data);

    // all modifiers are one-shot: reset after use
    resetMods();
  }, k.repeat);

  return btn;
}

function suppressPhoneKB(yes) {
  const ta = document.querySelector('.xterm-helper-textarea');
  if (!ta) return;
  if (yes) {
    ta.setAttribute('inputmode', 'none');
    ta.setAttribute('readonly', '');
    ta.blur();
  } else {
    ta.removeAttribute('inputmode');
    ta.removeAttribute('readonly');
    term.focus();
  }
}

function fitAndScroll() {
  kbSwitching = true;
  requestAnimationFrame(() => {
    fitAddon.fit(); term.scrollToBottom();
    setTimeout(() => { kbSwitching = false; }, 500);
  });
}

function toggleFullKB(on) {
  fullkbActive = on;
  const showBtn = document.getElementById('showkb');
  if (on) {
    buildFullKB();
    keysDiv.classList.add('hidden');
    fullkbDiv.style.display = 'block';
    showBtn.style.display = 'none';
    suppressPhoneKB(true);
  } else {
    fullkbDiv.style.display = 'none';
    showBtn.style.display = 'none';
    keysDiv.classList.remove('hidden');
    suppressPhoneKB(false);
    resetMods();
  }
  fitAndScroll();
}

function hideFullKB() {
  fullkbDiv.style.display = 'none';
  const showBtn = document.getElementById('showkb');
  showBtn.style.display = 'block';
  fitAndScroll();
}

// floating show-keyboard button
const showKbBtn = document.getElementById('showkb');
bindBtn(showKbBtn, () => {
  showKbBtn.style.display = 'none';
  fullkbDiv.style.display = 'block';
  fitAndScroll();
});
</script>
</body>
</html>"""


class BasicAuthMixin:
    """HTTP Basic Auth check. Skipped when AUTH is empty."""

    def _check_auth(self):
        if not AUTH:
            return True
        header = self.request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode()
                if secrets.compare_digest(decoded, AUTH):
                    return True
            except Exception:
                pass
        self.set_status(401)
        self.set_header("WWW-Authenticate", 'Basic realm="webterminal"')
        self.finish()
        return False


class IndexHandler(BasicAuthMixin, tornado.web.RequestHandler):
    def get(self):
        if not self._check_auth():
            return
        self.write(HTML)


class TermWebSocket(BasicAuthMixin, tornado.websocket.WebSocketHandler):
    def open(self):
        self.fd = None
        self.child_pid = None
        self.session_name = None
        self.is_anonymous = False
        if AUTH:
            header = self.request.headers.get("Authorization", "")
            ok = False
            if header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(header[6:]).decode()
                    ok = secrets.compare_digest(decoded, AUTH)
                except Exception:
                    pass
            if not ok:
                self.close(4401, "Unauthorized")
                return

        # Parse URL parameters
        attach = self.get_argument("attach", None)
        name = self.get_argument("name", None)
        cwd = self.get_argument("cwd", None)
        cmd = self.get_argument("cmd", None)

        # Determine tmux command
        if attach:
            if not _valid_session_name(attach):
                self.close(4400, "Invalid session name")
                return
            rc = subprocess.call([TMUX, "has-session", "-t", attach],
                                 stderr=subprocess.DEVNULL)
            if rc != 0:
                self.close(4404, "Session not found")
                return
            self.session_name = attach
            tmux_cmd = [TMUX, "attach-session", "-t", attach]
        elif name:
            if not _valid_session_name(name):
                self.close(4400, "Invalid session name")
                return
            self.session_name = name
            tmux_cmd = [TMUX, "new-session", "-A", "-s", name]
        else:
            self.session_name = _auto_session_name()
            self.is_anonymous = True
            tmux_cmd = [TMUX, "new-session", "-s", self.session_name]

        # Spawn PTY with tmux
        master_fd, slave_fd = pty.openpty()
        child_pid = os.fork()
        if child_pid == 0:
            # child
            os.close(master_fd)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            os.execvpe(tmux_cmd[0], tmux_cmd, env)
        else:
            # parent
            os.close(slave_fd)
            self.fd = master_fd
            self.child_pid = child_pid
            tornado.ioloop.IOLoop.current().add_handler(
                self.fd, self._read_pty, tornado.ioloop.IOLoop.READ
            )
            # Send initial cwd/cmd after tmux initializes
            if not attach and (cwd or cmd):
                loop = tornado.ioloop.IOLoop.current()
                if cwd:
                    loop.call_later(0.3, self._send_initial_keys,
                                    f"cd {cwd}")
                if cmd:
                    delay = 0.5 if cwd else 0.3
                    loop.call_later(delay, self._send_initial_keys, cmd)

    def _send_initial_keys(self, text):
        """Send a command string to the tmux session via the PTY."""
        if self.fd:
            try:
                os.write(self.fd, (text + "\n").encode())
            except OSError:
                pass

    def _read_pty(self, fd, events):
        try:
            data = os.read(fd, 65536)
            if data:
                self.write_message(data, binary=True)
            else:
                self.close()
        except OSError:
            self.close()

    def on_message(self, message):
        if isinstance(message, str) and message.startswith("{"):
            try:
                msg = json.loads(message)
                if msg.get("type") == "resize":
                    cols, rows = msg["cols"], msg["rows"]
                    winsize = struct.pack("HHHH", rows, cols, 0, 0)
                    fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
                    if self.child_pid:
                        os.kill(self.child_pid, signal.SIGWINCH)
                    return
            except (ValueError, KeyError):
                pass
        if self.fd:
            os.write(self.fd, message if isinstance(message, bytes) else message.encode())

    def on_close(self):
        if self.fd:
            try:
                tornado.ioloop.IOLoop.current().remove_handler(self.fd)
            except Exception:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
        if self.child_pid:
            try:
                os.waitpid(self.child_pid, os.WNOHANG)
            except OSError:
                pass
        # Clean up anonymous sessions (no one will reattach)
        if self.is_anonymous and self.session_name:
            try:
                subprocess.call([TMUX, "kill-session", "-t", self.session_name],
                                stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def check_origin(self, origin):
        return True


class ListTerminalsHandler(BasicAuthMixin, tornado.web.RequestHandler):
    def get(self):
        if not self._check_auth():
            return
        result = subprocess.run(
            [TMUX, "list-sessions", "-F",
             "#{session_name}|#{session_created}|#{session_windows}|#{session_attached}"],
            capture_output=True, text=True,
        )
        sessions = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                sessions.append({
                    "name": parts[0],
                    "created": int(parts[1]),
                    "windows": int(parts[2]),
                    "attached": int(parts[3]),
                })
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"sessions": sessions}))


class SendKeysHandler(BasicAuthMixin, tornado.web.RequestHandler):
    def post(self, name):
        if not self._check_auth():
            return
        if not _valid_session_name(name):
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid session name"}))
            return
        rc = subprocess.call([TMUX, "has-session", "-t", name],
                             stderr=subprocess.DEVNULL)
        if rc != 0:
            self.set_status(404)
            self.write(json.dumps({"error": "Session not found"}))
            return
        try:
            body = json.loads(self.request.body)
            keys = body["keys"]
        except (json.JSONDecodeError, KeyError):
            self.set_status(400)
            self.write(json.dumps({"error": "Body must contain 'keys'"}))
            return
        parts = keys.split("\n")
        for i, part in enumerate(parts):
            if part:
                subprocess.call([TMUX, "send-keys", "-t", name, "-l", part],
                                stderr=subprocess.DEVNULL)
            if i < len(parts) - 1:
                subprocess.call([TMUX, "send-keys", "-t", name, "Enter"],
                                stderr=subprocess.DEVNULL)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"ok": True}))


class KillTerminalHandler(BasicAuthMixin, tornado.web.RequestHandler):
    def delete(self, name):
        if not self._check_auth():
            return
        if not _valid_session_name(name):
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid session name"}))
            return
        rc = subprocess.call([TMUX, "has-session", "-t", name],
                             stderr=subprocess.DEVNULL)
        if rc != 0:
            self.set_status(404)
            self.write(json.dumps({"error": "Session not found"}))
            return
        subprocess.call([TMUX, "kill-session", "-t", name],
                        stderr=subprocess.DEVNULL)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"ok": True}))


def main():
    app = tornado.web.Application([
        (r"/", IndexHandler),
        (r"/ws", TermWebSocket),
        (r"/api/terminals", ListTerminalsHandler),
        (r"/api/terminals/([^/]+)/send", SendKeysHandler),
        (r"/api/terminals/([^/]+)", KillTerminalHandler),
    ])
    app.listen(PORT, address="0.0.0.0")
    print(f"Web terminal running at http://0.0.0.0:{PORT}")
    print(f"Shell: {SHELL} (via tmux)")
    print(f"Auth: {'enabled' if AUTH else 'disabled'}")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
