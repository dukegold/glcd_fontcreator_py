# GLCD Font Creator – Python 3 Port: Developer Context

## What this project is

A Python 3 / tkinter port of **GLCD_FontCreator** (Martin Burri, 2015, Apache 2.0), originally a .NET 4.5.2 / Visual Studio 2015 Windows Forms application. The original is in `GLCD_FontCreator/`. The Python port lives in the root of this repo alongside it.

The tool converts TrueType system fonts into C header files (`*.h`) for use with the Arduino GLCD library (KS0108-compatible graphical LCD controllers). It also saves a PNG thumbnail alongside each generated header.

---

## File layout

```
/Users/dukes/glcd/
├── glcd_font_creator.py        # Entry point + full tkinter GUI
├── font_optimizer.py           # Core rendering / optimization engine
├── app_settings.py             # JSON settings persistence
├── font_creators/
│   ├── __init__.py             # Format registry (AVAILABLE_CREATORS dict)
│   ├── fc_base.py              # Abstract base class for format creators
│   └── glcd_fc2.py             # GLCD FC2 format (the only format currently)
├── requirements.txt            # Pillow>=9.0.0
├── CONTEXT.md                  # This file
└── GLCD_FontCreator/           # Original C# source (reference only)
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| Pillow  | Font rendering (replaces Windows GDI+), image save for thumbnails |
| tkinter | GUI — built-in to Python stdlib, no install needed |

Install: `pip install Pillow`

The project was developed and tested inside a venv at `.venv/`.

---

## How to run

```bash
source .venv/bin/activate
python3 glcd_font_creator.py
```

---

## Architecture

### `app_settings.py` — `AppSettings`

Thin JSON wrapper that persists two paths across sessions:
- `font_dir` — last used font/TTF directory
- `save_dir` — last used save directory

Stored at `~/.glcd_font_creator.json`.

---

### `font_optimizer.py` — `FontOptimizer`, `WidthTarget`, `Rect`, `find_system_fonts`

**Direct port of `FontOptimizer.cs`.**

#### `Rect` dataclass
Simple rectangle with `x, y, width, height` plus `.right`, `.bottom`, and `.union(other)`.

#### `WidthTarget` enum
```python
WT_NONE    = 0   # Full character width from font metrics
WT_MONO    = 1   # Same width for all chars (minimum that fits the whole charset)
WT_MINIMUM = 2   # Individual minimum width per character
```

#### `FontOptimizer`

Constructor: `FontOptimizer(font_path, font_name='', bold=False, italic=False)`

Set these before calling `optimize()`:
```python
fo.first_char    = ' '    # first character (single char string)
fo.char_count    = 95     # number of characters
fo.target_height = 16     # desired rendered height in pixels
fo.remove_top    = True   # strip blank rows above ink
fo.remove_bottom = True   # strip blank rows below ink
```

After `optimize()`, these are populated:
```python
fo.font_to_use    # PIL ImageFont.FreeTypeFont at the right size
fo.scanline_start # first non-blank row in the rendered bitmap
fo.scanline_end   # last non-blank row
fo.final_height   # scanline_end - scanline_start + 1
fo.minimum_rect   # Rect: tightest box that fits all chars in the charset
fo._font_size     # float, the converged PIL font size
```

**Optimization algorithm** (mirrors original exactly):
1. Start at `target_height / 2` px
2. Render test string (all chars in range), scan bitmap for content rows
3. Adjust `remove_top`/`remove_bottom` flags to find start/end scanlines
4. Increment font size with adaptive steps until rendered height >= target:
   - deficit -1 or -2 → `+0.125`
   - deficit -3 → `+0.25`
   - deficit -4 → `+0.5`
   - deficit < -4 → `+2.0`
5. After convergence, scan every character individually to build `minimum_rect`

**`_get_string_bitmap(pil_font, text)`**:
- Calls `draw.textbbox((0,0), text, font)` to get the ink bounding box: `(left, top, right, bottom)`
- Computes canvas size: `w = bbox[2] + x_off + 2`, `h = bbox[3] + 2` (same formula as before)
- Calls `pil_font.getmask(text, mode='1')` to get a tight 1-bit FreeType bitmap of size `(right-left, bottom-top)`
- Pastes it at `(x_off, top_off)` in the canvas, where `x_off = max(0, -bbox[0])` (left-bearing) and `top_off = max(0, bbox[1])` (blank rows above ink = natural font leading)
- Result: canvas identical in size/coordinates to the old `draw.text()` approach, but pixels are strictly 0 or 255 — no antialiasing artifacts that would undercount character widths
- Falls back to antialiased `draw.text()` on exception (some unusual fonts reject `mode='1'`)

**Threshold** — `BLANKTX = 20`:
- A pixel is "blank" if its red channel < 20
- Scanning uses `>= BLANKTX` (not blank); letter encoding uses `> BLANKTX` (set bit)
- This matches the original C# exactly, including its minor inconsistency

**`get_map_for_char(c, width_target)`**:
Returns a cropped PIL Image for a single character using the global scanlines and `minimum_rect`. PIL's `crop()` auto-pads with black if the box extends beyond the bitmap (matching the original's try/catch fallback).

**`make_thumbnail(file_path)`**:
Renders all characters as one string and saves to `file_path + '.png'`.

**`find_system_fonts()`** (module-level):
Scans OS font directories and returns `{display_name: file_path}`.
- macOS: `/System/Library/Fonts`, `/Library/Fonts`, `~/Library/Fonts`
- Windows: `%WINDIR%\Fonts`
- Linux: `/usr/share/fonts`, `/usr/local/share/fonts`, `~/.fonts`, `~/.local/share/fonts`

Display name = filename without extension (e.g. `Arial.ttf` → `Arial`).

---

### `font_creators/fc_base.py` — `FCBase`

**Port of `FC_Base.cs`.**

Base class for all output format creators. Constructor takes a fully-optimized `FontOptimizer`.

Public attributes (set during `font_file()`):
```python
self.name               # font display name
self.font_name_created  # C-identifier-safe name (set by mod_name())
self.width              # max character width across charset
self.height             # final rendered height
self.monospace          # True if all chars have identical dimensions
self.first_char         # first char of the range
self.char_count         # number of chars
self.code_size          # total bytes in output array
```

**`mod_name()`** — generates C identifier:
- Replaces ` - + % ( ) , ;` with `_`
- Appends `x{width}` only if monospace
- Appends height
- Appends `_b` if bold, `_i` if italic
- Appends `_{first_ord:03d}_{last_ord:03d}`
- Example: `Arial16_032_126`, `Arialx1624_048_057`

**`_hex_byte(b)`** → `"0x1a, "` (single byte)
**`_hex_word(w)`** → `"0x00, 0x5b, "` (16-bit, MSB first)

Abstract methods subclasses must implement:
`letter_factory()`, `font_file()`, `_header()`, `_descriptor()`, `_code_start()`, `_trailer()`

---

### `font_creators/glcd_fc2.py` — `GLCD_FC2_Compatible`

**Port of `GLCD_FC2_Compatible.cs`.**
`NAME = 'GLCD_FC2_compatible'`

#### Byte encoding (the critical part)

The encoding is **page-major, column-minor**:

```
for b in range(bytes_per_col):          # outer: 8-px vertical pages (0,1,2...)
    for x in range(width):              # inner: columns left -> right
        col_byte = 0
        bit = 1
        for y in range(b*8, (b+1)*8):
            if y < height:
                if pixel[x,y].R > BLANKTX:
                    col_byte |= bit
                bit = (bit << 1) & 0xFF
            else:
                col_byte = (col_byte << 1) & 0xFF  # intentional FC2 "bug"
        append col_byte
```

So for a 16×24 character: 3 pages × 16 columns = 48 bytes.
Byte 0 = col 0 rows 0-7, byte 1 = col 1 rows 0-7, …, byte 16 = col 0 rows 8-15, etc.

The **overrun shift** (`col_byte = (col_byte << 1) & 0xFF` when `y >= height`) is a bug in FontCreator 2.x that **must be preserved** for compatibility with existing GLCD library font parsers.

#### `Letter` class
- `create_char(c, fo, width_target)` → runs the encoding loop, returns `(w, h)`
- `get_bytes()` → formats bytes as `0xNN, ` with one page per line, comment at end:
  `// char (032) ' '`
- `byte_count` property

#### `SizeTable` class
Stores per-character widths for variable-width fonts. `get_bytes()` outputs 16 values per line.

#### `GLCD_FC2_Compatible.font_file(first_char, char_count, width_target)`
Full pipeline:
1. Loops chars, calls `letter.create_char()` for each
2. Detects monospace (all chars same `(w, h)`)
3. Computes `total_size` = 6 (descriptor) + width_table (if variable) + all letter bytes
4. Concatenates: `_header() + _descriptor() + _code_start() + [size_table] + letters + _trailer()`
5. Removes the final trailing comma from the last hex byte
6. Returns complete string

#### Output file structure

```c
//
// Created by GLCD_FC2_compatible on MM/DD/YYYY
//   Font Name:  Arial16_032_126
//   ...
//
#include <inttypes.h>
#include <avr/pgmspace.h>
#ifndef _ARIAL_H_
#define _ARIAL_H_
#define ARIAL_WIDTH  15
#define ARIAL_HEIGHT 16

static const uint8_t Arial16_032_126[] PROGMEM = {
    0x05, 0xb9,  // size          ← 0x0000 if monospace
    0x0f,        // width
    0x10,        // height
    0x20,        // first char
    0x5f,        // char count

    // char widths  (only present if variable-width)
    0x04, 0x04, ...

    // font data
    0x00, 0x00, ...  // char (032) ' '
    ...
};

#endif
```

---

### `font_creators/__init__.py` — Format registry

```python
AVAILABLE_CREATORS = {
    'GLCD_FC2_compatible': GLCD_FC2_Compatible,
}
```

To add a new output format: create a class inheriting `FCBase`, add it here.

---

### `glcd_font_creator.py` — GUI

Built with **tkinter + ttk**. Two classes:

#### `FontDialog(tk.Toplevel)`
Modal font picker. Shows a merged dict of system + custom fonts in a searchable `Listbox`. Double-click or OK sets `self.result = (name, path)`.

#### `FontCreatorApp(tk.Tk)`
Main window. Sections (top to bottom):

| Section | Controls |
|---------|----------|
| Font | Font name entry (readonly), Select button, Add TTF File(s) button, Add TTF Directory button |
| Character Range | First char entry, Last char entry, ASCII readouts, Count readout |
| Optimization | Target height scale + entry, Remove Top/Bottom checkboxes, Optimize button, Final size label |
| Font Properties | Listbox showing optimizer results |
| Output | Width mode radios (None/Mono/Minimum), Format combobox, Save button |
| Preview | Test text entry, Char Range / Clear buttons, Canvas (black bg) |

**Key internal methods:**

- `_load_system_fonts()` — runs in background thread on startup; populates `self._system_fonts`
- `_load_font()` — opens `FontDialog`, stores `_current_font_path` / `_current_font_name`, calls `_optimize()`
- `_add_ttf_files()` / `_add_font_directory()` — add custom fonts to `self._custom_fonts`
- `_optimize()` — creates `FontOptimizer`, sets params, calls `fo.optimize()`, stores as `self._fo`
- `_show_font_props()` — populates the properties listbox from `self._fo`
- `_update_preview()` — renders test text via `fo._get_string_bitmap()`, scales up for readability, displays via `ImageTk.PhotoImage` on the canvas
- `_save_font_as()` — instantiates the selected creator class, calls `font_file()`, opens save dialog, writes `.h` and calls `make_thumbnail()`
- `_get_char_range()` → `(first_char, char_count)` or `None`
- `_validate_chars()` — keeps ASCII readouts and count label in sync

**State:**
```python
self._fo                  # FontOptimizer | None — set after Optimize
self._current_font_path   # str — path to selected .ttf/.otf
self._current_font_name   # str — display name
self._system_fonts        # dict name->path from find_system_fonts()
self._custom_fonts        # dict name->path from user-added files
self._photo_img           # ImageTk.PhotoImage ref (must be kept to prevent GC)
```

---

## Known differences from the original C# version

| Area | Original | Python port |
|------|-----------|-------------|
| Font rendering | GDI+ `SingleBitPerPixelGridFit` | Pillow `getmask(mode='1')` → FreeType `FT_RENDER_MODE_MONO` (1-bit, no antialiasing). Pasted onto a canvas with `textbbox` coordinates so scanline logic is unchanged. Falls back to `draw.text()` for fonts that reject mode='1'. |
| Bold / Italic synthesis | GDI can synthesize bold/italic from a regular font | Pillow cannot; user must select the bold/italic TTF file directly |
| Font picker | Custom WinForms dialog with style checkboxes | Searchable listbox; style is determined by the file chosen |
| `bold`/`italic` flags | Read from `Font.Bold` / `Font.Italic` | Set manually on `FontOptimizer`; currently always `False` unless explicitly set |
| Font size units | Points (GDI DPI-dependent) | Pixels (Pillow default); optimization converges to same result |
| Preview rendering | WinForms TextBox with font applied | Pillow image on a Canvas widget |
| Settings storage | .NET `ApplicationSettingsBase` (registry/AppData) | JSON at `~/.glcd_font_creator.json` |
| Platform | Windows only | macOS / Linux / Windows |

---

## How to add a new output format

1. Create `font_creators/my_format.py` — subclass `FCBase`, set `NAME`, implement all abstract methods and a `Letter`-like encoder.
2. Register it in `font_creators/__init__.py`:
   ```python
   from font_creators.my_format import MyFormat
   AVAILABLE_CREATORS['my_format_name'] = MyFormat
   ```
3. It will automatically appear in the Format combobox in the GUI.

---

## Tested environment

- macOS Darwin 25.3.0
- Python 3.x (venv at `.venv/`)
- Pillow 9+
- 284 system fonts discovered on test machine
- Tested with Arial, WT_MINIMUM and WT_MONO, heights 16 and 24 px
