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
.k:active,.k.held{background:#0078d4;color:#fff;border-color:#0078d4}
.k.mod{background:#4a3c2a;border-color:#7a6a4a;color:#e0c080}
.k.mod.held{background:#d4a017;color:#000;border-color:#d4a017}
.sp{flex-grow:1}
</style>
</head>
<body>
<div id="terminal"></div>
<div id="keys"></div>
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

ws.onopen = () => {
  sendResize();
  term.focus();
};
ws.onmessage = e => {
  if (e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data));
  else term.write(e.data);
};
ws.onclose = () => term.write('\r\n\x1b[31m[连接已断开]\x1b[0m\r\n');

term.onData(data => {
  if (ws.readyState !== 1) return;
  if (modState.ctrl || modState.alt || modState.shift) {
    let out = '';
    for (let i = 0; i < data.length; i++) {
      let ch = data[i];
      if (modState.shift && ch >= 'a' && ch <= 'z') {
        ch = ch.toUpperCase();
      }
      if (modState.ctrl && ch >= ' ' && ch <= '~') {
        ch = String.fromCharCode(ch.toUpperCase().charCodeAt(0) & 0x1f);
      }
      if (modState.alt) ch = '\x1b' + ch;
      out += ch;
    }
    ws.send(out);
    modState.ctrl = false; modState.alt = false; modState.shift = false;
    document.querySelectorAll('.k.mod').forEach(b => b.classList.remove('held'));
  } else {
    ws.send(data);
  }
});

function sendResize() {
  if (ws.readyState === 1) {
    ws.send(JSON.stringify({type:'resize', cols:term.cols, rows:term.rows}));
  }
}
term.onResize(() => sendResize());
window.addEventListener('resize', () => { fitAddon.fit(); });
new ResizeObserver(() => fitAddon.fit()).observe(document.getElementById('terminal'));

// --- Mobile virtual keys ---
const keysDiv = document.getElementById('keys');
const modState = {ctrl:false, alt:false, shift:false};

const keymap = [
  {label:'Esc',   send:'\x1b'},
  {label:'Tab',   send:'\t'},
  {label:'Ctrl',  mod:'ctrl', cls:'mod'},
  {label:'Alt',   mod:'alt',  cls:'mod'},
  {label:'Shift', mod:'shift', cls:'mod'},
  {label:'↑',     send:'\x1b[A', shifted:'\x1b[1;2A'},
  {label:'↓',     send:'\x1b[B', shifted:'\x1b[1;2B'},
  {label:'←',     send:'\x1b[D', shifted:'\x1b[1;2D'},
  {label:'→',     send:'\x1b[C', shifted:'\x1b[1;2C'},
  {label:'Home',  send:'\x1b[H', shifted:'\x1b[1;2H'},
  {label:'End',   send:'\x1b[F', shifted:'\x1b[1;2F'},
  {label:'Enter', send:'\r'},
  {label:'C-c',   send:'\x03'},
  {label:'C-d',   send:'\x04'},
  {label:'C-z',   send:'\x1a'},
  {label:'C-l',   send:'\x0c'},
  {label:'C-a',   send:'\x01'},
  {label:'C-r',   send:'\x12'},
];

function doKey(k) {
  if (k.mod) {
    modState[k.mod] = !modState[k.mod];
    document.querySelectorAll(`.k[data-mod="${k.mod}"]`).forEach(
      b => b.classList.toggle('held', modState[k.mod])
    );
  } else {
    let data = (modState.shift && k.shifted) ? k.shifted : k.send;
    if (modState.alt) data = '\x1b' + data;
    if (modState.ctrl && data.length === 1) {
      data = String.fromCharCode(data.charCodeAt(0) & 0x1f);
    }
    if (ws.readyState === 1) ws.send(data);
    Object.keys(modState).forEach(m => { modState[m] = false; });
    document.querySelectorAll('.k.mod').forEach(b => b.classList.remove('held'));
  }
  term.focus();
}

keymap.forEach(k => {
  const btn = document.createElement('span');
  btn.className = 'k' + (k.cls ? ' ' + k.cls : '');
  btn.textContent = k.label;
  if (k.mod) btn.setAttribute('data-mod', k.mod);

  btn.addEventListener('touchstart', e => { e.preventDefault(); });
  btn.addEventListener('touchend', e => { e.preventDefault(); doKey(k); });
  btn.addEventListener('mousedown', e => { e.preventDefault(); });
  btn.addEventListener('click', e => { e.preventDefault(); doKey(k); });

  keysDiv.appendChild(btn);
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
