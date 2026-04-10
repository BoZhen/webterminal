#!/usr/bin/env python3
"""Lightweight web terminal with mobile-friendly virtual keys."""

import fcntl
import os
import pty
import select
import signal
import struct
import termios

import tornado.ioloop
import tornado.web
import tornado.websocket

SHELL = os.environ.get("SHELL", "/usr/bin/bash")
PORT = int(os.environ.get("WEBTERMINAL_PORT", "7683"))

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
#fullkb .fk.space{max-width:none;flex:5}
#fullkb .fk.toggle{background:#2a4a3c;border-color:#4a7a6a;color:#80e0c0}

/* position-based color flash on press */
@keyframes pos-flash{
  0%{background:hsl(var(--hue),80%,55%);color:#fff;border-color:hsl(var(--hue),80%,40%)}
  100%{background:#3c3c3c;color:#ccc;border-color:#555}
}
.fk.flash,.k.flash{animation:pos-flash .35s ease-out}

/* split gap: hidden in portrait, visible in landscape */
#fullkb .split{display:none;flex-shrink:0}
@media (orientation:landscape){
  #fullkb .kbrow{max-width:none;justify-content:flex-start}
  #fullkb .fk{max-width:42px;padding:5px 0;font-size:13px}
  #fullkb .fk.wide{max-width:62px;flex:1.3}
  #fullkb .fk.space{max-width:none}
  #fullkb .split{display:block;flex:1;min-width:32px}
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
<script>
const term = new Terminal({
  fontSize: 14, fontFamily: 'Menlo, Monaco, "Courier New", monospace',
  cursorBlink: true, theme: {background:'#1e1e1e'},
  allowProposedApi: true,
});
const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.loadAddon(new WebLinksAddon.WebLinksAddon());
term.open(document.getElementById('terminal'));
fitAddon.fit();

const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${proto}//${location.host}/ws`);
ws.binaryType = 'arraybuffer';

ws.onopen = () => { sendResize(); term.focus(); };
ws.onmessage = e => {
  if (e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data));
  else term.write(e.data);
};
ws.onclose = () => term.write('\r\n\x1b[31m[连接已断开]\x1b[0m\r\n');

function sendResize() {
  if (ws.readyState === 1)
    ws.send(JSON.stringify({type:'resize', cols:term.cols, rows:term.rows}));
}
term.onResize(() => sendResize());
window.addEventListener('resize', () => fitAddon.fit());
new ResizeObserver(() => fitAddon.fit()).observe(document.getElementById('terminal'));

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

function bindBtn(el, fn) {
  el.addEventListener('touchstart', e => e.preventDefault());
  el.addEventListener('touchend', e => { e.preventDefault(); flash(el); fn(); });
  el.addEventListener('mousedown', e => e.preventDefault());
  el.addEventListener('click', e => { e.preventDefault(); flash(el); fn(); });
  el.addEventListener('animationend', () => el.classList.remove('flash'));
}

/* ========== compact key bar ========== */
const keysDiv = document.getElementById('keys');
const compactKeys = [
  {label:'Esc',   send:'\x1b'},
  {label:'Tab',   send:'\t'},
  {label:'Ctrl',  mod:'ctrl'},
  {label:'Alt',   mod:'alt'},
  {label:'Shift', mod:'shift'},
  {label:'\u2191',send:'\x1b[A', shifted:'\x1b[1;2A'},
  {label:'\u2193',send:'\x1b[B', shifted:'\x1b[1;2B'},
  {label:'\u2190',send:'\x1b[D', shifted:'\x1b[1;2D'},
  {label:'\u2192',send:'\x1b[C', shifted:'\x1b[1;2C'},
  {label:'Home',  send:'\x1b[H'},
  {label:'End',   send:'\x1b[F'},
  {label:'Enter', send:'\r'},
  {label:'C-c',   send:'\x03'},
  {label:'C-d',   send:'\x04'},
  {label:'C-z',   send:'\x1a'},
  {label:'C-l',   send:'\x0c'},
  {label:'C-a',   send:'\x01'},
  {label:'C-r',   send:'\x12'},
];

compactKeys.forEach(k => {
  const btn = document.createElement('span');
  btn.className = 'k' + (k.mod ? ' mod' : '');
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
  });
  keysDiv.appendChild(btn);
});

// toggle button in compact bar
const togBtn = document.createElement('span');
togBtn.className = 'k';
togBtn.textContent = '\u2328';
togBtn.title = 'Full keyboard';
bindBtn(togBtn, () => toggleFullKB(true));
keysDiv.appendChild(togBtn);

// assign hues to compact bar keys linearly
const compactBtns = keysDiv.querySelectorAll('.k');
compactBtns.forEach((btn, i) => {
  btn.style.setProperty('--hue', Math.round(i / Math.max(compactBtns.length - 1, 1) * 300));
});

/* ========== full virtual keyboard ========== */
const fullkbDiv = document.getElementById('fullkb');
let fullkbActive = false;
let symLayer = false;

const alphaRows = [
  [{l:'`',s:'~'},{l:'1',s:'!'},{l:'2',s:'@'},{l:'3',s:'#'},{l:'4',s:'$'},{l:'5',s:'%'},{l:'6',s:'^'},{l:'7',s:'&'},{l:'8',s:'*'},{l:'9',s:'('},{l:'0',s:')'},{l:'-',s:'_'},{l:'=',s:'+'}],
  [{l:'q'},{l:'w'},{l:'e'},{l:'r'},{l:'t'},{l:'y'},{l:'u'},{l:'i'},{l:'o'},{l:'p'},{l:'[',s:'{'},{l:']',s:'}'},{l:'\\',s:'|'}],
  [{l:'a'},{l:'s'},{l:'d'},{l:'f'},{l:'g'},{l:'h'},{l:'j'},{l:'k'},{l:'l'},{l:';',s:':'},{l:"'",s:'"'}],
  [{l:'z'},{l:'x'},{l:'c'},{l:'v'},{l:'b'},{l:'n'},{l:'m'},{l:',',s:'<'},{l:'.',s:'>'},{l:'/',s:'?'}],
];

function buildFullKB() {
  fullkbDiv.innerHTML = '';

  // row 0: esc + number/symbol row + backspace
  addRow(alphaRows[0], {
    before:[{label:'Esc', send:'\x1b'}],
    after:[{label:'\u232b', send:'\x7f', cls:'wide'}]
  });
  // row 1: qwerty
  addRow(alphaRows[1]);
  // row 2: home row + enter
  addRow(alphaRows[2], {
    after:[{label:'\u21b5', send:'\r', cls:'wide'}]
  });
  // row 3: shift + bottom row
  addRow(alphaRows[3], {
    before:[{label:'Shift', mod:'shift', cls:'mod wide'}],
  });
  // row 4: modifiers + space + special
  addSpecialRow();
  assignHues(fullkbDiv);
}

function assignHues(container) {
  const rows = container.querySelectorAll('.kbrow');
  const totalRows = rows.length;
  rows.forEach((row, ri) => {
    const keys = row.querySelectorAll('.fk,.k');
    const totalCols = keys.length;
    keys.forEach((key, ci) => {
      const ry = totalRows > 1 ? ri / (totalRows - 1) : 0;
      const rx = totalCols > 1 ? ci / (totalCols - 1) : 0;
      const diag = (ry + rx) / 2;
      key.style.setProperty('--hue', Math.round(diag * 300));
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
  keys.forEach(k => {
    const shifted = modState.shift || symLayer;
    const label = (shifted && k.s) ? k.s : k.l;
    const send = label;
    allItems.push(makeFK({label, send}));
  });
  if (extra && extra.after) extra.after.forEach(k => allItems.push(makeFK(k)));
  const mid = Math.ceil(allItems.length / 2);
  allItems.forEach((el, i) => {
    row.appendChild(el);
    if (i === mid - 1) row.appendChild(makeSplit());
  });
  fullkbDiv.appendChild(row);
}

function addSpecialRow() {
  const row = document.createElement('div');
  row.className = 'kbrow';
  const left = [
    {label:'\u25bc', action:'hide', cls:'toggle'},
    {label:'Ctrl', mod:'ctrl', cls:'mod'},
    {label:'Alt', mod:'alt', cls:'mod'},
    {label:'Tab', send:'\t'},
  ];
  const right = [
    {label:'\u2190', send:'\x1b[D'},
    {label:'\u2192', send:'\x1b[C'},
    {label:'\u2191', send:'\x1b[A'},
    {label:'\u2193', send:'\x1b[B'},
    {label:'\u2328', action:'toggle', cls:'toggle'},
  ];
  left.forEach(k => row.appendChild(makeFK(k)));
  row.appendChild(makeFK({label:'', send:' ', cls:'space'}));
  row.appendChild(makeSplit());
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
    if (k.mod) { toggleMod(k.mod); return; }

    // shift: for letters, uppercase; for symbols, already resolved in label
    let data = k.send;
    if (modState.shift && data.length === 1 && data >= 'a' && data <= 'z')
      data = data.toUpperCase();
    if (modState.ctrl && data.length === 1 && data >= ' ' && data <= '~')
      data = String.fromCharCode(data.toUpperCase().charCodeAt(0) & 0x1f);
    if (modState.alt) data = '\x1b' + data;
    if (ws.readyState === 1) ws.send(data);

    // keep shift held (like a real keyboard) until explicit release
    if (!k.mod) { modState.ctrl = false; modState.alt = false; }
    document.querySelectorAll('[data-mod="ctrl"],[data-mod="alt"]').forEach(
      b => b.classList.remove('held'));
  });

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
  setTimeout(() => fitAddon.fit(), 50);
}

function hideFullKB() {
  fullkbDiv.style.display = 'none';
  const showBtn = document.getElementById('showkb');
  showBtn.style.display = 'block';
  setTimeout(() => fitAddon.fit(), 50);
}

// floating show-keyboard button
const showKbBtn = document.getElementById('showkb');
bindBtn(showKbBtn, () => {
  showKbBtn.style.display = 'none';
  fullkbDiv.style.display = 'block';
  setTimeout(() => fitAddon.fit(), 50);
});
</script>
</body>
</html>"""


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(HTML)


class TermWebSocket(tornado.websocket.WebSocketHandler):
    def open(self):
        self.fd = None
        self.child_pid = None
        pid, fd = pty.openpty()
        # pid from pty.fork pattern: use fork
        child_pid = os.fork()
        if child_pid == 0:
            # child
            os.close(pid)
            os.setsid()
            fcntl.ioctl(fd, termios.TIOCSCTTY, 0)
            os.dup2(fd, 0)
            os.dup2(fd, 1)
            os.dup2(fd, 2)
            if fd > 2:
                os.close(fd)
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            os.execvpe(SHELL, [SHELL, "-l"], env)
        else:
            # parent
            os.close(fd)
            self.fd = pid
            self.child_pid = child_pid
            tornado.ioloop.IOLoop.current().add_handler(
                self.fd, self._read_pty, tornado.ioloop.IOLoop.READ
            )

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
                import json
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
                os.kill(self.child_pid, signal.SIGTERM)
                os.waitpid(self.child_pid, os.WNOHANG)
            except OSError:
                pass

    def check_origin(self, origin):
        return True


def main():
    app = tornado.web.Application([
        (r"/", IndexHandler),
        (r"/ws", TermWebSocket),
    ])
    app.listen(PORT, address="0.0.0.0")
    print(f"Web terminal running at http://0.0.0.0:{PORT}")
    print(f"Shell: {SHELL}")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
