# webterminal

Lightweight web-based terminal with a mobile-friendly virtual key bar. Single Python file, no build step.

## Features

- Full terminal via xterm.js + WebSocket
- Compact key bar for touch screens: Esc, Tab, Ctrl, Alt, Shift, arrow keys, Home/End, Enter, and common Ctrl combos (C-c, C-d, C-z, C-l, C-a, C-r)
- Full virtual QWERTY keyboard mode (toggle via ⌨ button): complete letter, number, and symbol input without the phone soft keyboard
- Modifier keys (Ctrl/Alt/Shift) are toggle-style: tap to activate, then tap another key or type on the soft keyboard to send the combo
- Split keyboard in landscape: keys split into left/right halves for ergonomic thumb typing
- Position-based rainbow flash feedback: each key lights up in a color based on its position (red at top-left to purple at bottom-right)
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

Tap the ⌨ button to switch to a full virtual keyboard that suppresses the phone soft keyboard entirely. In landscape orientation the keyboard automatically splits into left/right halves for comfortable thumb typing. Tap ▼ to hide the keyboard for browsing terminal output; a floating ⌨ button appears at the bottom-left to restore it.

## License

MIT
