# GNOME Handwriting Overlay

![Version](https://img.shields.io/badge/version-0.2.3--alpha-orange.svg) ![License: CC0](https://img.shields.io/badge/License-CC0_1.0-lightgrey.svg)

A transparent fullscreen overlay for GNOME Wayland that recognises handwriting and types the result into any application. Draw with a stylus or finger, wait for the countdown, and the recognised text appears in whatever window had focus before you started drawing.

https://github.com/user-attachments/assets/ffdfa916-d539-4b12-9a92-74124a2d3396

---

## How it works

1. Launch the overlay — it appears as a transparent fullscreen layer above all windows
2. Write with your stylus (or finger, if enabled)
3. After a short pause, the recognition engine processes your writing
4. The recognised text is automatically typed into the previously focused window
5. The overlay clears and closes (or stays open for another round)

Two recognition engines are supported:

- **MyScript** (default) — cloud API, excellent accuracy, supports cursive and many languages
- **Google Handwriting API** — no API key required, supports 50+ languages

---

## Requirements

### System dependencies

| Component | Purpose |
|---|---|
| Python 3.10+ | Runtime |
| GTK 4 + libadwaita | UI framework |
| gtk4-layer-shell | Wayland overlay positioning |
| wl-clipboard | Text injection — `wl-copy` puts text in clipboard |
| ydotool + ydotoold | Text injection — sends Ctrl+V keypress to paste |
| evdev | High-frequency stylus input (optional but recommended) |

> **Note on wtype:** GNOME Shell does not expose the `zwp_virtual_keyboard_v1` Wayland protocol, so `wtype` cannot inject text on GNOME and is not used.

### Python dependencies

```
requests       # Recognition API calls
evdev          # High-frequency tablet input (optional)
pyyaml         # Config file parsing
```

---

## Installation

### Arch Linux

```bash
# System packages
sudo pacman -S python gtk4 libadwaita gtk4-layer-shell wl-clipboard ydotool

# Python dependencies
pip install requests evdev pyyaml

# Add yourself to the input group for evdev access
sudo usermod -aG input $USER
# Log out and back in for the group change to take effect
```

### Fedora

```bash
# System packages
sudo dnf install python3 gtk4 libadwaita gtk4-layer-shell wl-clipboard ydotool

# Python dependencies
pip install requests evdev pyyaml

# Add yourself to the input group for evdev access
sudo usermod -aG input $USER
```

### Ubuntu / Debian

```bash
# System packages
sudo apt install python3 python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 libgtk4-layer-shell-dev \
    wl-clipboard ydotool

# Python dependencies
pip install requests evdev pyyaml

# Add yourself to the input group for evdev access
sudo usermod -aG input $USER
```

---

## Running

```bash
python3 main.py
```

The overlay starts fullscreen and transparent. Start drawing immediately.

To launch with a GNOME keyboard shortcut, go to Settings → Keyboard → Custom Shortcuts and point it to:

```
/usr/bin/python3 /path/to/katip/main.py
```

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Shift+A` | Toggle Recognition ↔ Annotation mode |
| `Shift+C` | Clear all strokes |
| `Shift+Q` | Quit |
| `Shift+H` | Toggle status bar on/off |
| `Escape` | Clear selection (if active), otherwise quit |
| `Enter` | Fire OCR immediately (skips countdown) |
| `Tab` | Cycle through ink colours |
| `Delete` / `Backspace` | Delete selected strokes |

---

## Drawing gestures

**Scribble to erase** — draw a rapid back-and-forth horizontal stroke over any ink to erase it. The gesture must span at least 60 px and reverse direction 4 or more times.

**Shift+drag to select** — hold Shift and drag a rectangle to select strokes. Selected strokes are highlighted in blue. Press Delete or Backspace to remove them, or Escape to deselect.

**Timer slider** — the vertical slider on the left edge of the screen controls the countdown duration (0.5s – 10s). Drag it with the stylus to adjust.

---

## Options dialog

Click the **⚙** button in the status bar to open the live settings editor. Changes take effect immediately without restarting.

| Page | Settings |
|---|---|
| **Typing** | Injection strategy, enabled toggle, focus delay, press Enter, clear/quit after inject |
| **Recognition** | Timeout, line merge factor, word gap factor |
| **Appearance** | Default brush colour, glow on/off, glow radius |
| **Input** | Pressure curve preset, min/max stroke thickness, touch/finger input |
| **Erase** | Enabled, min reversals, min width, hit radius |
| **Save** | Write current settings to `config.yaml` |

> Saving via the dialog overwrites `config.yaml` with current values. Hand-written comments in the file are not preserved.

---

## Configuration

All settings live in `config.yaml`. Key options:

```yaml
recognition:
  engine: myscript          # google | myscript
  timeout_seconds: 1.5      # Pause before OCR fires (also adjustable with the slider)
  active_language: en       # Language code: en de fr es it zh-CN ja ar ...

typing:
  strategy: auto            # wl_paste | ydotool | clipboard_only
  press_enter: false        # Send Enter after typing (useful for search bars)
  quit_after_inject: true   # Close after typing, or stay open

input:
  pressure_curve:           # Firm default — see presets below
    - [0.0, 0.0]
    - [0.5, 0.1]
    - [0.85, 0.7]
    - [1.0, 1.0]
  min_thickness: 1.0        # Stroke width (px) at zero pressure
  max_thickness: 12.0       # Stroke width (px) at full pressure
  touch_enabled: true       # Allow drawing with finger

erase:
  enabled: true
  min_reversals: 4          # How vigorous the scribble must be
  hit_threshold: 15.0       # Erase radius in px

annotation:
  default_color: "#FFFFFF"  # Starting ink colour
  glow_enabled: true        # Soft glow behind strokes
```

### Pressure curve presets

The pressure curve controls how quickly strokes thicken as you press harder. Replace the four control points in `config.yaml`, or use the **Options → Input** dropdown:

| Preset | Control points | Feel |
|---|---|---|
| Soft | `[0,0] [0.10,0.50] [0.50,0.90] [1,1]` | Thick with light touch |
| Medium | `[0,0] [0.30,0.10] [0.70,0.90] [1,1]` | Steep S-curve |
| **Firm** (default) | `[0,0] [0.50,0.10] [0.85,0.70] [1,1]` | Needs moderate pressure |
| Very Firm | `[0,0] [0.65,0.05] [0.95,0.70] [1,1]` | Stays thin until hard press |

Stroke thickness is rendered **per-segment** — each point pair gets its own width based on local pressure, giving a natural thick-to-thin taper as pressure varies along the stroke.

### Adding languages

```yaml
recognition:
  languages:
    - en      # English
    - de      # German
    - fr      # French
    - ja      # Japanese
    - zh-CN   # Chinese (Simplified)
    - ar      # Arabic
  active_language: en
```

Switch between languages using the dropdown in the status bar.

---

## Text injection

After recognition the overlay types the result into the previously focused window.

### How `wl_paste` works (default)

1. `wl-copy` writes the recognised text directly to the clipboard — Unicode, layout-independent
2. `ydotool` sends a raw Ctrl+V keypress (keycodes `29:1 47:1 47:0 29:0`) to paste it

This sidesteps the QWERTZ y↔z problem: `ydotool` is only used to press Ctrl+V, never to type individual characters, so the keyboard layout does not affect the output.

> **Terminals** use `Ctrl+Shift+V` to paste, not `Ctrl+V`. If you are injecting into a terminal, set `strategy: ydotool` in `config.yaml` — direct keystroke injection works there (y↔z swap only affects QWERTZ users).

### Strategy reference

| Strategy | How it works | Limitation |
|---|---|---|
| `wl_paste` | clipboard via `wl-copy` + Ctrl+V via `ydotool` | Does not paste in terminals |
| `ydotool` | Simulates keystrokes via `/dev/uinput` | y↔z swapped on QWERTZ keyboards |
| `clipboard_only` | Copies text to clipboard only — shows "press Ctrl+V" toast | User must paste manually |

`auto` resolves to `wl_paste` when both `wl-copy` and `ydotoold` are available, otherwise falls back in the order above.

### Setting up ydotoold

The ydotool **system** service runs as root and creates a socket that your user cannot access. Run it as a **user** service instead:

```bash
# Disable system service if it exists
sudo systemctl stop ydotool 2>/dev/null
sudo systemctl disable ydotool 2>/dev/null

# Create user service
mkdir -p ~/.config/systemd/user/
cat > ~/.config/systemd/user/ydotool.service << 'EOF'
[Unit]
Description=ydotool daemon (user)
After=graphical-session.target

[Service]
ExecStart=/usr/bin/ydotoold
Restart=always

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ydotool
```

The socket will be created at `$XDG_RUNTIME_DIR/.ydotool_socket` (e.g. `/run/user/1000/.ydotool_socket`). Katip picks this up automatically.

Verify:

```bash
systemctl --user status ydotool
python3 diagnose.py
```

---

## High-frequency stylus input (evdev)

By default GNOME delivers tablet events at ~60Hz. The overlay includes an optional high-frequency input path that reads directly from `/dev/input` via `evdev`, giving the full 133–400Hz tablet rate for smoother strokes.

This activates automatically if `evdev` is installed and you have permission to read `/dev/input`:

```bash
pip install evdev
sudo usermod -aG input $USER
# Log out and back in
```

Verify it is active by checking terminal output on launch:

```
evdev: high-frequency input active     ✓ working
evdev: not available, using GTK input  ✗ check permissions
```

---

## File structure

```
.
├── main.py                  # Entry point
├── config.yaml              # All configuration
├── pyproject.toml           # Build and tool configuration
├── Makefile                 # Shortcuts: make run / test / lint
├── INTEGRATION_GUIDE.md     # Notes on embedding or extending the overlay
├── diagnose.py              # Injection setup checker — run this if text isn't typed
├── debug_inject.py          # Manual injection test harness
├── test_evdev.py            # Interactive evdev input tester
├── core/
│   ├── app.py               # Application lifecycle, global shortcuts
│   ├── config.py            # Config loading (YAML → dataclasses) + save()
│   └── state_machine.py     # IDLE → DRAWING → COUNTDOWN → RECOGNIZING
├── ui/
│   ├── canvas.py            # Drawing surface, per-segment pressure rendering
│   ├── overlay_window.py    # Main window, Wayland layer shell
│   ├── status_bar.py        # Mode / language / engine / countdown display
│   ├── options_dialog.py    # Live settings editor (⚙ button)
│   ├── palette_bar.py       # Colour swatches (Annotation mode)
│   ├── timer_slider.py      # Countdown duration slider
│   └── result_popup.py      # OCR result toast and history panel
├── input/
│   ├── stylus_handler.py    # GTK stylus/touch input, touch_enabled checked live
│   ├── evdev_handler.py     # High-frequency tablet input via /dev/input
│   └── pressure.py          # Cubic Bézier pressure → line width mapping
├── recognition/
│   ├── engine.py            # MyScript + Google Handwriting API clients
│   └── layout.py            # Multi-line stroke segmentation
├── utils/
│   ├── text_injector.py     # wl_paste / ydotool / clipboard_only backends
│   ├── timer.py             # Cancellable GLib timer wrapper
│   ├── color.py             # Colour utilities and palette
│   └── logging_setup.py     # Structured logging
└── tests/
    ├── test_config.py
    ├── test_pressure.py
    └── test_state_machine.py
```

---

## License

This project is released into the **public domain** under the [Creative Commons Zero v1.0 Universal (CC0)](https://creativecommons.org/publicdomain/zero/1.0/) license.

You can copy, modify, distribute and use the work, even for commercial purposes, without asking permission and without attribution.

See the [LICENSE](LICENSE) file for the full text.

> **Note:** Depending on the recognition engine, handwriting data is sent to Google's or MyScript's servers. No data is stored locally beyond the current session.

---

## Troubleshooting

**Overlay doesn't appear** — make sure you are on a GNOME Wayland session, not X11. Check with `echo $XDG_SESSION_TYPE` — it should say `wayland`.

**Text not injected** — run `python3 diagnose.py` for a full diagnosis. Check `systemctl --user status ydotool` and verify the socket exists at `$XDG_RUNTIME_DIR/.ydotool_socket`.

**Text injected into wrong window / nothing happens** — increase `focus_release_delay_ms` in `config.yaml` or the Options dialog (try 300ms). The compositor needs time to return focus to the target window after the overlay hides.

**Strokes are blocky / low resolution** — make sure `evdev` is installed and you are in the `input` group. Check `python3 main.py 2>&1 | grep evdev`.

**Wrong language recognised** — switch using the language dropdown in the status bar, or change `active_language` in `config.yaml`.

**Accidental erasing** — increase `erase.min_reversals` or `erase.min_width` in the Options dialog, or disable the gesture with `erase.enabled: false`.

**ydotool types wrong characters (y/z swapped on QWERTZ)** — switch to the `wl_paste` strategy (Options → Typing, or `strategy: wl_paste` in `config.yaml`). It pastes via clipboard so the keyboard layout has no effect.

**wl_paste does not work in my terminal** — terminals use Ctrl+Shift+V, not Ctrl+V. Switch to `strategy: ydotool` for terminal use.
