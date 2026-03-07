"""
GLCD Font Creator – Python 3 port of the .NET GLCD_FontCreator (Martin Burri, 2015).

Converts system / custom TrueType fonts into C header files suitable for
Arduino GLCD (KS0108 / compatible) displays.

Dependencies
------------
  pip install Pillow

Usage
-----
  python glcd_font_creator.py
"""
from __future__ import annotations

import glob
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from app_settings import AppSettings
from font_creators import AVAILABLE_CREATORS
from font_optimizer import FontOptimizer, WidthTarget, find_system_fonts

APP_NAME = 'GLCD Font Creator'
APP_VERSION = '1.0'


# ---------------------------------------------------------------------------
# Font-selection dialog
# ---------------------------------------------------------------------------

class FontDialog(tk.Toplevel):
    """Searchable modal dialog for picking a font from the known collections."""

    def __init__(self, parent, system_fonts: dict, custom_fonts: dict):
        super().__init__(parent)
        self.title('Select Font')
        self.resizable(True, True)
        self.minsize(320, 380)
        self.geometry('420x520')

        # Custom fonts override system fonts with the same display name
        self._all_fonts = {**system_fonts, **custom_fonts}
        self._sorted_names = sorted(self._all_fonts.keys(), key=str.lower)
        self.result = None  # set to (name, path) on OK

        self._build_ui()
        self.grab_set()
        self.transient(parent)

    def _build_ui(self):
        # Search row
        top = ttk.Frame(self, padding=(8, 8, 8, 4))
        top.pack(fill='x')
        ttk.Label(top, text='Search:').pack(side='left')
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', self._filter_list)
        ttk.Entry(top, textvariable=self._search_var).pack(
            side='left', fill='x', expand=True, padx=(4, 0))

        # Font list with scrollbar
        mid = ttk.Frame(self, padding=(8, 0))
        mid.pack(fill='both', expand=True)
        self._listbox = tk.Listbox(mid, selectmode='single', exportselection=False,
                                   activestyle='dotbox')
        sb = ttk.Scrollbar(mid, orient='vertical', command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=sb.set)
        self._listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self._listbox.bind('<Double-Button-1>', lambda _e: self._ok())

        # Status line
        self._info_var = tk.StringVar(value='')
        ttk.Label(self, textvariable=self._info_var, anchor='w',
                  padding=(8, 2)).pack(fill='x')

        # Buttons
        btns = ttk.Frame(self, padding=(8, 4, 8, 8))
        btns.pack(fill='x')
        ttk.Button(btns, text='OK', width=8, command=self._ok).pack(
            side='right', padx=(4, 0))
        ttk.Button(btns, text='Cancel', width=8, command=self.destroy).pack(
            side='right')
        ttk.Label(btns, text=f'{len(self._all_fonts)} fonts available').pack(
            side='left')

        self._populate_list(self._sorted_names)

    def _populate_list(self, names: list):
        self._listbox.delete(0, 'end')
        for name in names:
            self._listbox.insert('end', name)

    def _filter_list(self, *_):
        query = self._search_var.get().lower()
        filtered = [n for n in self._sorted_names if query in n.lower()]
        self._populate_list(filtered)
        self._info_var.set(f'{len(filtered)} match(es)' if query else '')

    def _ok(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        name = self._listbox.get(sel[0])
        path = self._all_fonts.get(name)
        if path:
            self.result = (name, path)
        self.destroy()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class FontCreatorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(f'{APP_NAME}  v{APP_VERSION}')
        self.resizable(True, True)
        self.minsize(660, 680)

        self._settings = AppSettings()
        self._system_fonts: dict = {}
        self._custom_fonts: dict = {}
        self._fo: FontOptimizer | None = None
        self._current_font_path = ''
        self._current_font_name = ''
        self._photo_img = None  # must keep reference to prevent GC

        self._build_ui()
        self._validate_chars()
        # Scan fonts in background so the window appears immediately
        threading.Thread(target=self._load_system_fonts, daemon=True).start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- menu bar ----
        menubar = tk.Menu(self)
        self.configure(menu=menubar)
        fm = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label='File', menu=fm)
        fm.add_command(label='Load Font…',            command=self._load_font)
        fm.add_command(label='Add TTF File(s)…',      command=self._add_ttf_files)
        fm.add_command(label='Add TTF Directory…',    command=self._add_font_directory)
        fm.add_separator()
        fm.add_command(label='Save Font As .h…',      command=self._save_font_as)
        fm.add_separator()
        fm.add_command(label='Exit',                  command=self.destroy)

        # ---- status bar (bottom) ----
        self._status_var = tk.StringVar(value='Scanning system fonts…')
        ttk.Label(self, textvariable=self._status_var, relief='sunken',
                  anchor='w', padding=(4, 2)).pack(side='bottom', fill='x')

        # ---- scrollable main area ----
        outer = ttk.Frame(self, padding=6)
        outer.pack(fill='both', expand=True)

        # == Font selection ==
        ff = ttk.LabelFrame(outer, text='Font', padding=6)
        ff.pack(fill='x', pady=(0, 4))
        r0 = ttk.Frame(ff)
        r0.pack(fill='x', pady=(0, 4))
        ttk.Label(r0, text='Font:').pack(side='left')
        self._font_name_var = tk.StringVar(value='(none selected)')
        ttk.Entry(r0, textvariable=self._font_name_var,
                  state='readonly').pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(r0, text='Select…',
                   command=self._load_font).pack(side='left')
        r1 = ttk.Frame(ff)
        r1.pack(fill='x')
        ttk.Button(r1, text='Add TTF File(s)…',
                   command=self._add_ttf_files).pack(side='left', padx=(0, 6))
        ttk.Button(r1, text='Add TTF Directory…',
                   command=self._add_font_directory).pack(side='left')

        # == Character range ==
        cf = ttk.LabelFrame(outer, text='Character Range', padding=6)
        cf.pack(fill='x', pady=(0, 4))
        g = ttk.Frame(cf)
        g.pack()

        ttk.Label(g, text='First char:').grid(row=0, column=0, sticky='e', padx=4)
        self._first_char_var = tk.StringVar(value=' ')
        fe = ttk.Entry(g, textvariable=self._first_char_var, width=3)
        fe.grid(row=0, column=1, padx=2)
        fe.bind('<KeyRelease>', self._validate_chars)
        ttk.Label(g, text='ASCII:').grid(row=0, column=2, sticky='e', padx=(10, 4))
        self._first_asc_var = tk.StringVar()
        ttk.Entry(g, textvariable=self._first_asc_var, width=5,
                  state='readonly').grid(row=0, column=3, padx=2)

        ttk.Label(g, text='Last char:').grid(row=1, column=0, sticky='e', padx=4, pady=2)
        self._last_char_var = tk.StringVar(value='~')
        le = ttk.Entry(g, textvariable=self._last_char_var, width=3)
        le.grid(row=1, column=1, padx=2)
        le.bind('<KeyRelease>', self._validate_chars)
        ttk.Label(g, text='ASCII:').grid(row=1, column=2, sticky='e', padx=(10, 4))
        self._last_asc_var = tk.StringVar()
        ttk.Entry(g, textvariable=self._last_asc_var, width=5,
                  state='readonly').grid(row=1, column=3, padx=2)
        ttk.Label(g, text='Count:').grid(row=1, column=4, sticky='e', padx=(10, 4))
        self._char_count_var = tk.StringVar()
        ttk.Entry(g, textvariable=self._char_count_var, width=6,
                  state='readonly').grid(row=1, column=5, padx=2)

        # == Optimization ==
        of = ttk.LabelFrame(outer, text='Optimization', padding=6)
        of.pack(fill='x', pady=(0, 4))

        hr = ttk.Frame(of)
        hr.pack(fill='x', pady=(0, 4))
        ttk.Label(hr, text='Target height (px):').pack(side='left')
        self._height_var = tk.IntVar(value=16)
        self._height_scale = ttk.Scale(hr, from_=4, to=96,
                                       variable=self._height_var, orient='horizontal',
                                       command=self._on_scale_change)
        self._height_scale.pack(side='left', fill='x', expand=True, padx=6)
        self._height_entry = ttk.Entry(hr, textvariable=self._height_var, width=5)
        self._height_entry.pack(side='left')
        self._height_entry.bind('<Return>', self._on_height_entry)
        self._height_entry.bind('<FocusOut>', self._on_height_entry)

        cbr = ttk.Frame(of)
        cbr.pack(fill='x', pady=(0, 4))
        self._remove_top_var = tk.BooleanVar(value=True)
        self._remove_bottom_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cbr, text='Remove Top blank rows',
                        variable=self._remove_top_var).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(cbr, text='Remove Bottom blank rows',
                        variable=self._remove_bottom_var).pack(side='left')

        obr = ttk.Frame(of)
        obr.pack(fill='x')
        ttk.Button(obr, text='Optimize Font',
                   command=self._optimize).pack(side='left')
        ttk.Label(obr, text='Final size:').pack(side='left', padx=(16, 4))
        self._size_result_var = tk.StringVar(value='—')
        ttk.Label(obr, textvariable=self._size_result_var,
                  font=('TkFixedFont', 10, 'bold')).pack(side='left')

        # == Font properties ==
        pf = ttk.LabelFrame(outer, text='Font Properties', padding=6)
        pf.pack(fill='x', pady=(0, 4))
        self._props_list = tk.Listbox(pf, height=5, selectmode='browse',
                                      font='TkFixedFont')
        self._props_list.pack(fill='x')

        # == Output ==
        wf = ttk.LabelFrame(outer, text='Output', padding=6)
        wf.pack(fill='x', pady=(0, 4))

        wr = ttk.Frame(wf)
        wr.pack(fill='x', pady=(0, 4))
        ttk.Label(wr, text='Width mode:').pack(side='left')
        self._width_mode_var = tk.IntVar(value=0)
        ttk.Radiobutton(wr, text='None',    variable=self._width_mode_var,
                        value=0).pack(side='left', padx=6)
        ttk.Radiobutton(wr, text='Mono',    variable=self._width_mode_var,
                        value=1).pack(side='left', padx=6)
        ttk.Radiobutton(wr, text='Minimum', variable=self._width_mode_var,
                        value=2).pack(side='left', padx=6)

        sr = ttk.Frame(wf)
        sr.pack(fill='x')
        ttk.Label(sr, text='Format:').pack(side='left')
        self._format_var = tk.StringVar()
        format_names = list(AVAILABLE_CREATORS.keys())
        fc = ttk.Combobox(sr, textvariable=self._format_var,
                          values=format_names, state='readonly', width=26)
        fc.pack(side='left', padx=6)
        if format_names:
            fc.current(0)
        ttk.Button(sr, text='Save Font As .h…',
                   command=self._save_font_as).pack(side='left', padx=8)

        # == Preview ==
        pvf = ttk.LabelFrame(outer, text='Preview', padding=6)
        pvf.pack(fill='both', expand=True, pady=(0, 4))

        pr = ttk.Frame(pvf)
        pr.pack(fill='x', pady=(0, 4))
        ttk.Label(pr, text='Test text:').pack(side='left')
        self._test_text_var = tk.StringVar()
        ttk.Entry(pr, textvariable=self._test_text_var).pack(
            side='left', fill='x', expand=True, padx=4)
        ttk.Button(pr, text='Char range',
                   command=self._use_char_range).pack(side='left', padx=2)
        ttk.Button(pr, text='Clear',
                   command=lambda: self._test_text_var.set('')).pack(side='left')

        self._canvas = tk.Canvas(pvf, bg='black', height=80,
                                 highlightthickness=0)
        self._canvas.pack(fill='both', expand=True)

        self._test_text_var.trace_add('write', lambda *_: self._update_preview())

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_scale_change(self, value):
        self._height_var.set(int(float(value)))

    def _on_height_entry(self, _event=None):
        try:
            v = int(str(self._height_var.get()))
            v = max(4, min(v, 128))
            self._height_var.set(v)
        except (ValueError, tk.TclError):
            pass

    def _validate_chars(self, *_):
        fc = self._first_char_var.get()
        lc = self._last_char_var.get()
        self._first_asc_var.set(str(ord(fc[0])) if fc else '—')
        self._last_asc_var.set(str(ord(lc[0])) if lc else '—')
        if fc and lc:
            fo = ord(fc[0])
            lo = ord(lc[0])
            if lo >= fo:
                self._char_count_var.set(str(lo - fo + 1))
                return
        self._char_count_var.set('—')

    def _get_char_range(self):
        """Return (first_char, char_count) or None if the range is invalid."""
        fc = self._first_char_var.get()
        lc = self._last_char_var.get()
        if not fc or not lc:
            return None
        fo = ord(fc[0])
        lo = ord(lc[0])
        if lo < fo:
            return None
        return fc[0], lo - fo + 1

    def _use_char_range(self):
        result = self._get_char_range()
        if result:
            first, count = result
            self._test_text_var.set(
                ''.join(chr(ord(first) + i) for i in range(count)))

    # ------------------------------------------------------------------
    # Font loading
    # ------------------------------------------------------------------

    def _load_system_fonts(self):
        self._system_fonts = find_system_fonts()
        self.after(0, lambda: self._status_var.set(
            f'Ready — {len(self._system_fonts)} system fonts found.'))

    def _load_font(self):
        dlg = FontDialog(self, self._system_fonts, self._custom_fonts)
        self.wait_window(dlg)
        if dlg.result:
            name, path = dlg.result
            self._current_font_name = name
            self._current_font_path = path
            self._font_name_var.set(name)
            self._optimize()

    def _add_ttf_files(self):
        paths = filedialog.askopenfilenames(
            title='Add TTF / OTF File(s)',
            initialdir=self._settings.font_dir,
            filetypes=[('Font files', '*.ttf *.otf *.TTF *.OTF'),
                       ('All files', '*.*')])
        failed = []
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            try:
                from PIL import ImageFont as _IF
                _IF.truetype(path, 12)
                self._custom_fonts[name] = path
            except Exception:
                failed.append(name)
        if paths:
            self._settings.font_dir = os.path.dirname(paths[0])
            self._settings.save()
        added = len(paths) - len(failed)
        self._status_var.set(f'Added {added} custom font(s).'
                             + (f'  {len(failed)} failed.' if failed else ''))
        if failed:
            messagebox.showwarning(
                'Add Font Files',
                'Could not load the following fonts:\n' + '\n'.join(failed))

    def _add_font_directory(self):
        directory = filedialog.askdirectory(
            title='Add Font Directory',
            initialdir=self._settings.font_dir)
        if not directory:
            return
        self._settings.font_dir = directory
        self._settings.save()
        loaded = failed = 0
        for ext in ('*.ttf', '*.TTF', '*.otf', '*.OTF'):
            for path in glob.glob(
                    os.path.join(directory, '**', ext), recursive=True):
                name = os.path.splitext(os.path.basename(path))[0]
                try:
                    from PIL import ImageFont as _IF
                    _IF.truetype(path, 12)
                    self._custom_fonts[name] = path
                    loaded += 1
                except Exception:
                    failed += 1
        self._status_var.set(f'Added {loaded} font(s) from directory.'
                             + (f'  {failed} failed.' if failed else ''))

    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------

    def _optimize(self):
        if not self._current_font_path:
            messagebox.showwarning('Optimize', 'Please select a font first.')
            return
        result = self._get_char_range()
        if result is None:
            messagebox.showwarning('Optimize', 'Invalid character range.')
            return
        first_char, char_count = result
        target_height = int(self._height_var.get())
        self._status_var.set('Optimizing…')
        self.update_idletasks()
        try:
            fo = FontOptimizer(
                font_path=self._current_font_path,
                font_name=self._current_font_name)
            fo.first_char = first_char
            fo.char_count = char_count
            fo.target_height = target_height
            fo.remove_top = self._remove_top_var.get()
            fo.remove_bottom = self._remove_bottom_var.get()
            fo.optimize()
            self._fo = fo
        except Exception as exc:
            messagebox.showerror('Optimization Error', str(exc))
            self._status_var.set('Optimization failed.')
            return

        self._size_result_var.set(
            f'{self._fo.minimum_rect.width} × {self._fo.minimum_rect.height} px')
        self._show_font_props()
        self._update_preview()
        self._status_var.set(
            f'Optimized: {self._fo.font_name}  '
            f'height={self._fo.final_height}px  '
            f'scanlines={self._fo.scanline_start}–{self._fo.scanline_end}')

    def _show_font_props(self):
        self._props_list.delete(0, 'end')
        if self._fo is None:
            return
        for text in (
            f'Font Name  : {self._fo.font_name}',
            f'Bold       : {self._fo.bold}',
            f'Italic     : {self._fo.italic}',
            f'Final Ht   : {self._fo.final_height} px',
            f'Scanlines  : {self._fo.scanline_start} – {self._fo.scanline_end}',
            f'Min Rect   : x={self._fo.minimum_rect.x}'
            f'  y={self._fo.minimum_rect.y}'
            f'  w={self._fo.minimum_rect.width}'
            f'  h={self._fo.minimum_rect.height}',
        ):
            self._props_list.insert('end', text)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _update_preview(self):
        if self._fo is None or self._fo.font_to_use is None:
            return
        text = self._test_text_var.get()
        if not text:
            result = self._get_char_range()
            if result:
                first, count = result
                text = ''.join(chr(ord(first) + i) for i in range(count))
        if not text:
            return
        try:
            img = self._fo._get_string_bitmap(self._fo.font_to_use, text)
            w, h = img.size
            # Scale up for readability, capped to avoid huge images
            canvas_h = max(self._canvas.winfo_height(), 60)
            scale = max(1, min(4, canvas_h // max(h, 1)))
            if scale > 1:
                img = img.resize((w * scale, h * scale), Image.NEAREST)
            self._photo_img = ImageTk.PhotoImage(img)
            self._canvas.delete('all')
            self._canvas.create_image(2, 2, anchor='nw', image=self._photo_img)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_font_as(self):
        if self._fo is None:
            messagebox.showwarning('Save', 'Please optimize a font first.')
            return
        result = self._get_char_range()
        if result is None:
            messagebox.showwarning('Save', 'Invalid character range.')
            return
        first_char, char_count = result

        format_name = self._format_var.get()
        if format_name not in AVAILABLE_CREATORS:
            messagebox.showwarning('Save', 'Select a valid output format.')
            return

        width_mode = WidthTarget(self._width_mode_var.get())
        creator_cls = AVAILABLE_CREATORS[format_name]
        creator = creator_cls(self._fo)

        self._status_var.set('Generating font data…')
        self.update_idletasks()
        try:
            content = creator.font_file(first_char, char_count, width_mode)
        except Exception as exc:
            messagebox.showerror('Generation Error', str(exc))
            self._status_var.set('Generation failed.')
            return

        save_path = filedialog.asksaveasfilename(
            title='Save Font Header',
            initialdir=self._settings.save_dir,
            initialfile=creator.font_name_created + '.h',
            defaultextension='.h',
            filetypes=[('C Header', '*.h'), ('All files', '*.*')])
        if not save_path:
            self._status_var.set('Save cancelled.')
            return

        try:
            with open(save_path, 'w', encoding='utf-8') as fh:
                fh.write(content)
            self._fo.make_thumbnail(save_path)
            self._settings.save_dir = os.path.dirname(save_path)
            self._settings.save()
            self._status_var.set(
                f'Saved: {os.path.basename(save_path)}'
                f'  ({creator.code_size} bytes)  — thumbnail: {os.path.basename(save_path)}.png')
        except Exception as exc:
            messagebox.showerror('Save Error', str(exc))
            self._status_var.set('Save failed.')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app = FontCreatorApp()
    app.mainloop()
