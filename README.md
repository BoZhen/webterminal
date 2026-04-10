# webterminal

Lightweight web-based terminal with a mobile-friendly virtual key bar. Single Python file, no build step.

## Features

- Full terminal via xterm.js + WebSocket
- Virtual key bar for touch screens: Esc, Tab, Ctrl, Alt, Shift, arrow keys, Home/End, Enter, and common Ctrl combos (C-c, C-d, C-z, C-l, C-a, C-r)
- Modifier keys (Ctrl/Alt/Shift) are toggle-style: tap to activate, then tap another key or type on the soft keyboard to send the combo
- Auto-fit terminal to viewport, responsive on resize
- Clickable URLs (web-links addon)

## Requirements

- Python 3.10+
- [Tornado](https://www.tornadoweb.org/)

```bash
pip install tornado
```

## Usage

```bash
python server.py
```

Open `http://<host>:7683` in a browser.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `WEBTERMINAL_PORT` | `7683` | Listen port |
| `SHELL` | `/usr/bin/bash` | Shell to spawn |

```bash
WEBTERMINAL_PORT=8888 SHELL=/usr/bin/fish python server.py
```

## Mobile usage

Designed for accessing a remote machine's terminal from a phone.

The bottom bar provides modifier and special keys that phone soft keyboards lack. Modifier keys are sticky: tap Ctrl, then type `c` on the soft keyboard to send Ctrl-C.

## License

MIT
