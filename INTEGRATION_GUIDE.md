# GNOME Handwriting Overlay — Setup & Integration Guide

## Project Structure

```
gnome-overlay/
├── main.py                    # Entry point
├── config.yaml                # All tuneable parameters
├── core/
│   ├── app.py                 # Adwaita Application, global actions & shortcuts
│   ├── config.py              # YAML loader + typed dataclasses
│   └── state_machine.py       # FSM: IDLE → DRAWING → COUNTDOWN → RECOGNIZING
├── ui/
│   ├── overlay_window.py      # Transparent Wayland window + layer-shell
│   ├── canvas.py              # Cairo drawing surface, color persistence
│   └── status_bar.py          # Adwaita toolbar: mode / language / countdown
├── input/
│   ├── stylus_handler.py      # GtkGestureStylus + GestureDrag, pressure
│   └── pressure.py            # Cubic Bézier pressure → thickness mapping
├── recognition/
│   └── engine.py              # Threaded Tesseract OCR via pytesseract
└── utils/
    └── __init__.py
```

---

## 1. System Dependencies

### Ubuntu / Debian

```bash
# GTK 4, Adwaita, PyGObject
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
    gir1.2-adw-1 gir1.2-gdk-4.0 libgtk-4-dev

# Layer-shell (GNOME 45+ / wlroots)
sudo apt install libgtk4-layer-shell-dev

# Python binding for layer-shell
pip install gtk4-layer-shell          # or build from source (see §4)

# Cairo Python bindings
sudo apt install python3-cairo

# Tesseract OCR engine + languages
sudo apt install tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra
# Add more: tesseract-ocr-<ISO-639-3>

# Python OCR + image processing
pip install pytesseract pillow pyyaml
```

### Fedora / RHEL

```bash
sudo dnf install python3-gobject python3-cairo gtk4 libadwaita \
    gtk4-layer-shell tesseract
pip install pytesseract pillow pyyaml gtk4-layer-shell
```

---

## 2. Running the Application

```bash
# From the project root
python3 main.py

# With a custom config location
CONFIG_PATH=/etc/handwriting-overlay/config.yaml python3 main.py
```

---

## 3. GNOME Wayland Integration

### 3a. wlr-layer-shell: OVERLAY layer

The application uses **gtk4-layer-shell** to request the Wayland
`zwlr_layer_shell_v1` OVERLAY layer.  This ensures the window floats
above all application windows **and** below the GNOME system panel by
default (configurable via `z_layer` in config.yaml).

> **GNOME Shell note:** GNOME Shell supports the layer-shell protocol
> from GNOME 45 onwards via the `gnome-shell-extension-gtk4-desktop-icons`
> mechanism.  On older versions, the window will still open but z-ordering
> is not guaranteed.  Use KDE Plasma or Hyprland for full compatibility.

### 3b. Click-through ↔ Capture: Input Region

This is the central architectural challenge on Wayland.

| State               | Desired behaviour                        | Mechanism                              |
|---------------------|------------------------------------------|----------------------------------------|
| IDLE / COUNTDOWN    | Pointer/touch pass through to desktop   | `GdkSurface.set_input_region(empty)`   |
| DRAWING / ANNOTATING| App captures all pointer/touch events   | `GdkSurface.set_input_region(full)`    |

**Implementation detail (`ui/overlay_window.py`):**

```python
import cairo
region = cairo.Region()           # empty  → pass-through
# OR
region = cairo.Region(cairo.RectangleInt(0, 0, w, h))  # full → capture

surface = gtk_window.get_surface()   # GdkSurface
surface.set_input_region(region)
```

`GdkSurface.set_input_region` requires **PyGObject ≥ 3.48** and a GDK
Wayland backend.  If the binding is missing, the app logs a warning and
falls back to a always-capturing window (annotation still works; only
the click-through feature is missing).

### 3c. Triggering Capture on Pen Proximity

For pen tablets that emit `proximity-in` events before `down`, you can
upgrade to full capture earlier:

```python
# In StylusHandler.__init__:
stylus.connect("proximity", self._on_proximity)

def _on_proximity(self, gesture, sequence):
    # Switch to capture mode so the first down event isn't lost
    self._begin_capture()
```

---

## 4. Building gtk4-layer-shell from Source

If the pip package is unavailable:

```bash
git clone https://github.com/wmww/gtk4-layer-shell.git
cd gtk4-layer-shell
meson setup build -Dtests=false -Dexamples=false -Ddocs=false
ninja -C build
sudo ninja -C build install
```

Then generate the GObject Introspection typelib so Python can find it:

```bash
sudo ldconfig
# The .gir and .typelib files install to /usr/local/lib/girepository-1.0/
```

---

## 5. Extending the Application

### Add a new language at runtime

Edit `config.yaml` → `recognition.languages` list, or use the
language dropdown in the status bar.  The dropdown is wired to
`RecognitionConfig.active_language` and takes effect on the next
OCR call.

### Custom pressure curves

Open `config.yaml` and edit `input.pressure_curve`.  The four `[x,y]`
pairs define a cubic Bézier:
- P0 must be `[0,0]`
- P3 must be `[1,1]`
- P1 and P2 are free control points

Use a tool like [cubic-bezier.com](https://cubic-bezier.com) to
design the curve visually, then paste the coordinates.

### Plug in a different OCR engine

Replace `recognition/engine.py`'s `_worker` method with any
engine (Google Vision, Apple Vision via subprocess, etc.).  The only
contract is calling `GLib.idle_add(cls._finish, sm, result, callback)`
on completion.

---

## 6. Systemd User Service (autostart)

```ini
# ~/.config/systemd/user/handwriting-overlay.service
[Unit]
Description=GNOME Handwriting Overlay
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/gnome-overlay/main.py
Restart=on-failure
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0

[Install]
WantedBy=graphical-session.target
```

```bash
systemctl --user enable --now handwriting-overlay
```

---

## Pending Feature: Gesture Commands (Delete / Backspace)

**Request:** Allow the user to mark text in another window, open the overlay,
draw a gesture over empty canvas space, and have that gesture send a key action
(e.g. Delete or Backspace) to remove the selected text.

### Options discussed

**Option A — Shape recognition via Google OCR**
Match the OCR result of an abstract shape against a lookup table of known
shapes → key actions. Simple but fragile.

**Option B — Local gesture detection (no OCR)**
Detect shape geometry directly from raw stroke points in `_on_stroke_end`
before the OCR countdown starts. If a gesture matches, fire the key via
`ydotool key` immediately and skip OCR. More reliable.

### The conflict problem
Any simple drawable shape (horizontal line, zigzag) is also a valid character
(dash, tilde, z) so naive shape detection would conflict with normal writing.

### Proposed solutions (undecided)
1. **Command mode** — a third state (alongside Recognition and Annotation)
   activated by a shortcut (e.g. `Shift+D`). In command mode, strokes are
   interpreted as key gestures rather than text. Zero conflict with normal use.

2. **Stylus eraser end** — use the back/eraser end of the pen to draw gestures.
   evdev reports this as a separate tool type (`BTN_TOOL_RUBBER`). Completely
   unambiguous — you would never write text with the eraser.

3. **Multitouch arm** — a two-finger tap arms gesture mode for the next stroke.
   Requires multitouch implementation first.

### Files that would need changes
- `ui/canvas.py` — add `_detect_gesture(stroke)` in `_on_stroke_end`
- `utils/text_injector.py` — add `send_key(keyname)` calling `ydotool key`
- `core/state_machine.py` — add `COMMAND` state if going with option 1
- `core/config.py` — add gesture mappings config section
