"""Meta Nuke GUI — Tkinter-based desktop interface."""

import os
import re
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image

from metanuke.core import MetaNuke, HEIF_AVAILABLE
from metanuke.utils import load_config, save_config, log_results


def _setup_macos_dock_icon():
    """Set activation policy and Dock icon on macOS."""
    if sys.platform != 'darwin':
        return
    try:
        import ctypes
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        NSApp = objc.objc_msgSend(
            objc.objc_getClass(b'NSApplication'),
            objc.sel_registerName(b'sharedApplication'),
        )
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
        objc.objc_msgSend(NSApp, objc.sel_registerName(b'setActivationPolicy:'), 0)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'Meta Nuke.app', 'Contents', 'Resources', 'MetaNuke.icns')
        if os.path.exists(icon_path):
            NSString = objc.objc_getClass(b'NSString')
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
            ns_path = objc.objc_msgSend(
                objc.objc_msgSend(NSString, objc.sel_registerName(b'alloc')),
                objc.sel_registerName(b'initWithUTF8String:'),
                icon_path.encode('utf-8'),
            )
            NSImage = objc.objc_getClass(b'NSImage')
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            icon_image = objc.objc_msgSend(
                objc.objc_msgSend(NSImage, objc.sel_registerName(b'alloc')),
                objc.sel_registerName(b'initWithContentsOfFile:'),
                ns_path,
            )
            objc.objc_msgSend(NSApp, objc.sel_registerName(b'setApplicationIconImage:'), icon_image)
    except Exception:
        pass


# Drag-and-drop support
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


TOOLTIPS = {
    'noise_check': 'Enable or disable forensic noise injection.\nWhen off, images are processed losslessly.',
    'noise_slider': 'Intensity of imperceptible pixel noise (0-10).\n0 = lossless, 5 = default, 10 = maximum.\nDefeats LSB steganography detection.',
    'lossless': 'Quick-toggle lossless mode.\nDisables noise, sets slider to 0, uses max quality.',
    'output_dir': 'Save nuked files to a different folder.\nLeave empty to overwrite originals.',
    'preview': 'Show all metadata found in the selected file(s)\nbefore nuking.',
    'audit_log': 'Save a log of all nuke operations to file.',
    'nuke_btn': 'Strip all metadata from the selected file(s).\nThis cannot be undone.',
    'drop_zone': 'Drop image files here or click to browse.\nSupports: JPG, PNG, GIF, WEBP, TIFF, BMP, SVG, AVIF, HEIC, PDF',
}


class ToolTip:
    """Simple tooltip for tkinter widgets."""
    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip_window = None
        self._after_id = None
        widget.bind('<Enter>', self._enter)
        widget.bind('<Leave>', self._leave)
        widget.bind('<Motion>', self._motion)
        self._last_x = self._last_y = 0

    def _enter(self, event):
        self._after_id = self.widget.after(self.delay, self._show)

    def _leave(self, event):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        self._hide()

    def _motion(self, event):
        self._last_x, self._last_y = event.x_root, event.y_root

    def _show(self):
        if self.tip_window:
            return
        x = self._last_x + 12
        y = self._last_y + 8
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        tw.attributes('-topmost', True)
        label = tk.Label(tw, text=self.text, justify='left',
                         background='#2a2a2a', foreground='#f0f0f0',
                         font=('Helvetica Neue', 10),
                         padx=10, pady=6, wraplength=300)
        label.pack()

    def _hide(self):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class MetaNukeGUI:
    """Dark-themed GUI for MetaNuke with drag-and-drop and full options."""

    def __init__(self, preloaded_files=None):
        if DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("Meta Nuke")
        self.root.geometry("580x700")
        self.root.minsize(520, 620)
        self.root.configure(bg='#0a0a0a')
        self.root.resizable(True, True)

        # Set window icon
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        icon_png = os.path.join(project_root,
                                'Meta Nuke.app', 'Contents', 'Resources', 'MetaNuke.png')
        if os.path.exists(icon_png):
            try:
                icon = tk.PhotoImage(file=icon_png)
                self.root.iconphoto(True, icon)
                self._icon_ref = icon
            except Exception:
                pass

        _setup_macos_dock_icon()

        self.files: list[str] = []
        self.noise_level = tk.IntVar(value=5)
        self.noise_enabled = tk.BooleanVar(value=True)
        self.lossless_mode = tk.BooleanVar(value=False)
        self.audit_logging = tk.BooleanVar(value=False)
        self.output_dir: Optional[str] = None
        self.output_suffix = tk.StringVar(value="")
        self.is_processing = False

        self.config_path = os.path.join(os.path.expanduser('~'), '.metanukerc')

        # Load saved config
        cfg = load_config(self.config_path)
        self.noise_level.set(cfg.get('noise_level', 5))
        self.audit_logging.set(cfg.get('audit_log', False))
        saved_out = cfg.get('output_dir')
        if saved_out and os.path.isdir(saved_out):
            self.output_dir = saved_out
            self.out_dir_label = None
        self.output_suffix.set(cfg.get('output_suffix', ''))

        self._setup_styles()
        self._setup_ui()
        self._setup_keyboard_shortcuts()

        if preloaded_files:
            self._set_files(preloaded_files)

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')

    def _add_tooltips(self):
        ToolTip(self.drop_zone, TOOLTIPS['drop_zone'])
        ToolTip(self.noise_checkbtn, TOOLTIPS['noise_check'])
        ToolTip(self.noise_scale, TOOLTIPS['noise_slider'])
        ToolTip(self.lossless_checkbtn, TOOLTIPS['lossless'])
        ToolTip(self.out_dir_label, TOOLTIPS['output_dir'])
        ToolTip(self.preview_btn, TOOLTIPS['preview'])
        ToolTip(self.audit_checkbtn, TOOLTIPS['audit_log'])
        ToolTip(self.nuke_button, TOOLTIPS['nuke_btn'])

    def _setup_keyboard_shortcuts(self):
        self.root.bind('<Command-o>', lambda e: self._browse_files())
        self.root.bind('<Command-O>', lambda e: self._browse_files())
        self.root.bind('<Command-n>', lambda e: self._nuke() if not self.is_processing else None)
        self.root.bind('<Command-N>', lambda e: self._nuke() if not self.is_processing else None)
        self.root.bind('<Command-p>', lambda e: self._preview_metadata() if self.preview_btn['state'] == 'normal' else None)
        self.root.bind('<Command-P>', lambda e: self._preview_metadata() if self.preview_btn['state'] == 'normal' else None)
        self.root.bind('<Escape>', lambda e: self._clear_all() if not self.is_processing else None)

    def _clear_all(self):
        self.files = []
        self.file_label.configure(text="No file selected", fg='#777777')
        self._set_nuke_button_state('disabled')
        self.preview_btn.configure(state='disabled')
        self._drop_zone_state = 'default'
        self._draw_border()
        text = ("📁  Drop images here or click to browse"
                if DND_AVAILABLE else
                "📁  Click to select images  •  Bulk supported")
        self.drop_label.configure(text=text, fg='#aaaaaa')
        self._update_status("Ready", '#777777')

    def _setup_ui(self):
        FONT = 'Helvetica Neue'
        BG = '#0a0a0a'
        CARD_BG = '#1c1c1e'
        ACCENT = '#cc3333'
        TEXT = '#f0f0f0'
        TEXT_SEC = '#aaaaaa'
        TEXT_MUTED = '#777777'
        SUCCESS = '#30d158'

        main_frame = tk.Frame(self.root, bg=BG)
        main_frame.pack(fill='both', expand=True, padx=28, pady=24)

        # ── Header ──
        header = tk.Frame(main_frame, bg=BG)
        header.pack(fill='x', pady=(0, 20))
        tk.Label(header, text="Meta Nuke",
                 font=(FONT, 22, 'bold'), bg=BG, fg=TEXT).pack()
        tk.Label(header, text="Forensically safe metadata destruction",
                 font=(FONT, 11), bg=BG, fg=TEXT_SEC).pack(pady=(2, 0))

        # ── Drop zone ──
        self._drop_zone_state = 'default'
        self.drop_zone = tk.Canvas(main_frame, bg='#161618', highlightthickness=0,
                                   bd=0, height=130)
        self.drop_zone.pack(fill='x', pady=(0, 16))

        self.drop_label = tk.Label(self.drop_zone,
            text="📁  Drop images here or click to browse",
            font=(FONT, 12), bg='#161618', fg=TEXT_SEC, justify='center')
        self.drop_zone.create_window(0, 0, window=self.drop_label,
                                     anchor='center', tags='drop_label_window')

        def _draw_border():
            self.drop_zone.delete('border')
            w = self.drop_zone.winfo_width()
            h = self.drop_zone.winfo_height()
            if w < 10 or h < 10:
                return
            palettes = {
                'default':    {'outline': '#3a3a3c'},
                'hover':      {'outline': '#cc3333'},
                'loaded':     {'outline': '#30d158'},
                'processing': {'outline': '#ff9f0a'},
            }
            c = palettes.get(self._drop_zone_state, palettes['default'])
            self.drop_zone.create_rectangle(2, 2, w-3, h-3,
                outline=c['outline'], width=1, dash=(4, 3), tags='border')

        def _center_label():
            self.drop_zone.coords('drop_label_window',
                                  self.drop_zone.winfo_width()//2,
                                  self.drop_zone.winfo_height()//2)

        self._draw_border = _draw_border
        self._center_label = _center_label
        self.drop_zone.bind('<Configure>', lambda e: (_draw_border(), _center_label()))
        _draw_border()
        _center_label()

        self.drop_zone.bind('<Button-1>', self._browse_files)
        self.drop_label.bind('<Button-1>', self._browse_files)

        if DND_AVAILABLE:
            for widget in (self.drop_zone, self.drop_label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind('<<DropEnter>>', self._on_drop_enter)
                widget.dnd_bind('<<DropLeave>>', self._on_drop_leave)
                widget.dnd_bind('<<Drop>>', self._on_drop)
            # Also allow drop directly on the NUKE button
            self.nuke_button_dnd_registered = False
        else:
            self.drop_label.configure(text="📁  Click to select images  •  Bulk supported")

        # ── Options card ──
        opts = tk.Frame(main_frame, bg=CARD_BG, bd=0, highlightthickness=0)
        opts.pack(fill='x', pady=(0, 14))

        # ── Noise row ──
        nr = tk.Frame(opts, bg=CARD_BG)
        nr.pack(fill='x', padx=16, pady=(14, 4))
        tk.Label(nr, text="Forensic Noise", font=(FONT, 12, 'bold'),
                 bg=CARD_BG, fg=TEXT, anchor='w').pack(side='left')
        self.noise_checkbtn = tk.Checkbutton(nr, text="On", variable=self.noise_enabled,
                                              bg=CARD_BG, fg=TEXT_SEC, selectcolor='#3a3a3c',
                                              activebackground=CARD_BG, activeforeground=TEXT,
                                              onvalue=True, offvalue=False)
        self.noise_checkbtn.pack(side='right')

        # ── Noise slider ──
        ns = tk.Frame(opts, bg=CARD_BG)
        ns.pack(fill='x', padx=16, pady=(0, 6))
        self.noise_scale = tk.Scale(ns, from_=0, to=10, orient='horizontal',
                                     variable=self.noise_level, showvalue=True,
                                     bg=CARD_BG, fg=TEXT, troughcolor='#3a3a3c',
                                     highlightthickness=0, bd=0, length=200,
                                     sliderrelief='flat', width=16, font=(FONT, 10))
        self.noise_scale.pack(side='left')
        tk.Label(ns, text="0 = lossless  ·  5 = default  ·  10 = max", font=(FONT, 9),
                 bg=CARD_BG, fg=TEXT_MUTED).pack(side='left', padx=(10, 0))

        # ── Lossless mode ──
        lr = tk.Frame(opts, bg=CARD_BG)
        lr.pack(fill='x', padx=16, pady=(0, 10))
        self.lossless_checkbtn = tk.Checkbutton(lr, text="Lossless mode",
            variable=self.lossless_mode, bg=CARD_BG, fg=TEXT_SEC, selectcolor='#3a3a3c',
            activebackground=CARD_BG, activeforeground=TEXT,
            onvalue=True, offvalue=False,
            command=self._toggle_lossless)
        self.lossless_checkbtn.pack(side='left')
        tk.Label(lr, text="Disables noise, max quality, no pixel changes",
                 font=(FONT, 9), bg=CARD_BG, fg=TEXT_MUTED).pack(side='left', padx=(8, 0))

        # ── Separator ──
        tk.Frame(opts, bg='#3a3a3c', height=1).pack(fill='x', padx=16)

        # ── Output dir + naming ──
        orow = tk.Frame(opts, bg=CARD_BG)
        orow.pack(fill='x', padx=16, pady=(12, 4))
        tk.Label(orow, text="Save to", font=(FONT, 12, 'bold'),
                 bg=CARD_BG, fg=TEXT, anchor='w').pack(side='left')
        self.out_dir_label = tk.Label(orow, text="Original location (overwrite)" if not self.output_dir
                                       else self.output_dir,
                                       font=(FONT, 10), bg=CARD_BG,
                                       fg=TEXT_SEC if not self.output_dir else SUCCESS, anchor='w')
        self.out_dir_label.pack(side='left', fill='x', expand=True, padx=(10, 0))
        tk.Button(orow, text="Browse…", font=(FONT, 10),
                  bg='#6a6a6c', fg=TEXT, bd=0, padx=10, pady=4,
                  activebackground='#7a7a7c', activeforeground=TEXT,
                  command=self._browse_output_dir).pack(side='right')
        tk.Button(orow, text="✕", font=(FONT, 12), bg='#6a6a6c', fg=TEXT, bd=0, padx=8, pady=4,
                  activebackground='#7a7a7c', activeforeground=ACCENT,
                  command=self._clear_output_dir).pack(side='right', padx=(0, 6))

        # ── Output suffix ──
        sr = tk.Frame(opts, bg=CARD_BG)
        sr.pack(fill='x', padx=16, pady=(0, 10))
        tk.Label(sr, text="Name suffix", font=(FONT, 10),
                 bg=CARD_BG, fg=TEXT_SEC, anchor='w').pack(side='left')
        tk.Entry(sr, textvariable=self.output_suffix, font=(FONT, 10),
                 bg='#3a3a3c', fg=TEXT, bd=0, insertbackground=TEXT,
                 width=18, relief='flat').pack(side='right')
        tk.Label(sr, text="  e.g. _nuked  →  photo_nuked.jpg",
                 font=(FONT, 9), bg=CARD_BG, fg=TEXT_MUTED).pack(side='right', padx=(0, 6))

        # ── Separator ──
        tk.Frame(opts, bg='#3a3a3c', height=1).pack(fill='x', padx=16)

        # ── Preview + audit log ──
        arow = tk.Frame(opts, bg=CARD_BG)
        arow.pack(fill='x', padx=16, pady=(12, 14))
        self.preview_btn = tk.Button(arow, text="Preview Metadata", font=(FONT, 11),
                                      bg='#6a6a6c', fg=TEXT, bd=0, padx=12, pady=5,
                                      activebackground='#7a7a7c', activeforeground=TEXT,
                                      state='disabled', command=self._preview_metadata)
        self.preview_btn.pack(side='left')
        self.audit_checkbtn = tk.Checkbutton(arow, text="Audit Log", font=(FONT, 11),
                                              variable=self.audit_logging, bg=CARD_BG,
                                              fg=TEXT_SEC, selectcolor='#3a3a3c',
                                              activebackground=CARD_BG, activeforeground=TEXT,
                                              onvalue=True, offvalue=False)
        self.audit_checkbtn.pack(side='left', padx=(14, 0))
        tk.Label(arow, text="⌘O open  ·  ⌘N nuke  ·  ⌘P preview  ·  ⎋ clear",
                 font=(FONT, 8), bg=CARD_BG, fg=TEXT_MUTED).pack(side='right')

        # ── File info ──
        self.file_label = tk.Label(main_frame, text="No file selected", font=(FONT, 11),
                                    bg=BG, fg=TEXT_MUTED, wraplength=500)
        self.file_label.pack(pady=(0, 14))

        # ── NUKE button ──
        self.nuke_button = tk.Canvas(main_frame, bg=BG, highlightthickness=0,
                                      bd=0, width=280, height=48)
        self.nuke_button.pack(pady=(0, 14))
        self._nuke_button_state = 'disabled'

        def _draw_nuke():
            self.nuke_button.delete('btn')
            w = self.nuke_button.winfo_width()
            h = self.nuke_button.winfo_height()
            if w < 10 or h < 10:
                return
            if self._nuke_button_state == 'normal':
                bg, fg, cursor = ACCENT, '#ffffff', 'hand2'
            else:
                bg, fg, cursor = '#5a5a5c', TEXT_MUTED, 'arrow'
            self.nuke_button.configure(cursor=cursor)
            self.nuke_button.create_rectangle(2, 2, w-3, h-3,
                fill=bg, outline='', width=0, tags='btn')
            self.nuke_button.create_text(w//2, h//2, text="Nuke Metadata",
                                          font=(FONT, 14, 'bold'), fill=fg, tags='btn')

        self._draw_nuke = _draw_nuke
        self.nuke_button.bind('<Configure>', lambda e: _draw_nuke())
        self.nuke_button.bind('<Button-1>', lambda e: self._nuke()
                              if (self._nuke_button_state == 'normal' and not self.is_processing)
                              else None)
        _draw_nuke()

        # Register drop on nuke button after UI is built
        if DND_AVAILABLE:
            self.root.after(100, self._register_nuke_drop)

        # ── Status ──
        self.status_label = tk.Label(main_frame, text="Ready", font=(FONT, 12),
                                      bg=BG, fg=TEXT_MUTED)
        self.status_label.pack(pady=(0, 14))

        # ── Footer ──
        footer = tk.Frame(main_frame, bg=BG)
        footer.pack(side='bottom', pady=(0, 6))
        tk.Label(footer, text="100% offline  ·  Nuclear destruction",
                 font=(FONT, 9, 'bold'), bg=BG, fg=TEXT_SEC).pack()
        tk.Label(footer,
                 text="EXIF  ·  IPTC  ·  XMP  ·  ICC  ·  GPS  ·  Timestamps  ·  DPI  ·  Camera",
                 font=(FONT, 8), bg=BG, fg=TEXT_MUTED).pack()

        # Add tooltips after all widgets exist
        self.root.after(200, self._add_tooltips)

    def _register_nuke_drop(self):
        """Register DND on the nuke button for direct-drop-nuke."""
        if not DND_AVAILABLE or not hasattr(self, 'nuke_button'):
            return
        try:
            self.nuke_button.drop_target_register(DND_FILES)
            self.nuke_button.dnd_bind('<<Drop>>', self._on_nuke_drop)
            self.nuke_button_dnd_registered = True
        except Exception:
            pass

    def _on_nuke_drop(self, event):
        """Handle files dropped directly on the NUKE button."""
        if self.is_processing:
            return
        raw_data = event.data
        paths = self._parse_drop_data(raw_data)
        if paths:
            self._set_files(paths)
            if self._nuke_button_state == 'normal':
                self.root.after(100, self._nuke)

    def _toggle_lossless(self):
        """When lossless mode is toggled, sync the noise slider."""
        if self.lossless_mode.get():
            self.noise_enabled.set(False)
            self.noise_level.set(0)
        # When turning off lossless, restore defaults
        else:
            self.noise_enabled.set(True)
            self.noise_level.set(5)

    def _parse_drop_data(self, raw_data):
        """Parse drag-and-drop data into a list of file paths."""
        paths = []
        if '{' in raw_data:
            matches = re.findall(r'\{([^}]+)\}|(\S+)', raw_data)
            for match in matches:
                p = match[0] if match[0] else match[1]
                if p and os.path.exists(p):
                    paths.append(p)
        else:
            for p in raw_data.split():
                if os.path.exists(p):
                    paths.append(p)
            if not paths and os.path.exists(raw_data):
                paths.append(raw_data)
        return paths

    def _browse_files(self, event=None):
        if self.is_processing:
            return
        all_formats = ' '.join(sorted([f'*{e}' for e in MetaNuke.SUPPORTED_FORMATS]))
        paths = filedialog.askopenfilenames(
            title='Select Image(s) to Nuke - Hold Cmd/Ctrl for multiple',
            filetypes=[('Image files', all_formats), ('All files', '*.*')],
        )
        if paths:
            self._set_files(list(paths))

    def _browse_output_dir(self):
        d = filedialog.askdirectory(title='Select output directory')
        if d:
            self.output_dir = d
            self.out_dir_label.configure(text=d, fg='#30d158')

    def _clear_output_dir(self):
        self.output_dir = None
        self.out_dir_label.configure(text="Original location (overwrite)", fg='#aaaaaa')

    def _preview_metadata(self):
        if not self.files or self.is_processing:
            return
        parts = []
        for f in self.files:
            scan = MetaNuke.scan_metadata(f)
            name = scan['name']
            if scan['has_metadata']:
                lines = [f"▸ {name}"]
                if scan['info']:
                    for k, v in scan['info'].items():
                        lines.append(f"    {k}: {v}")
                if scan['exif_keys']:
                    lines.append(f"    EXIF tags: {', '.join(scan['exif_keys'][:10])}"
                                 f"{' …' if len(scan['exif_keys']) > 10 else ''}")
                if scan['marker_details']:
                    for d in scan['marker_details']:
                        lines.append(f"    ⚠ {d}")
                parts.append('\n'.join(lines))
            else:
                parts.append(f"▸ {name}  ✓  Clean — no metadata detected")
        messagebox.showinfo("Metadata Preview", '\n\n'.join(parts))

    def _on_drop_enter(self, event):
        if self.is_processing:
            return 'break'
        self._drop_zone_saved_state = self._drop_zone_state
        self._drop_zone_saved_label_fg = self.drop_label.cget('fg')
        self._drop_zone_state = 'hover'
        self.drop_label.configure(fg='#ffffff')
        self._draw_border()

    def _on_drop_leave(self, event):
        saved_state = getattr(self, '_drop_zone_saved_state', None)
        saved_fg = getattr(self, '_drop_zone_saved_label_fg', None)
        if saved_state is not None:
            self._drop_zone_state = saved_state
            delattr(self, '_drop_zone_saved_state')
        if saved_fg is not None:
            self.drop_label.configure(fg=saved_fg)
            delattr(self, '_drop_zone_saved_label_fg')
        self._draw_border()

    def _on_drop(self, event):
        if self.is_processing:
            return
        paths = self._parse_drop_data(event.data)
        if paths:
            self._set_files(paths)

    def _set_files(self, file_paths: list[str]):
        valid_files = []
        skipped = 0
        for file_path in file_paths:
            if not os.path.exists(file_path):
                skipped += 1
                continue
            if os.path.isdir(file_path):
                for f in sorted(Path(file_path).rglob('*')):
                    if f.is_file() and f.suffix.lower() in MetaNuke.SUPPORTED_FORMATS:
                        valid_files.append(str(f))
                continue
            ext = Path(file_path).suffix.lower()
            if ext not in MetaNuke.SUPPORTED_FORMATS:
                skipped += 1
                continue
            valid_files.append(file_path)
        if not valid_files:
            self._update_status("No valid files", '#ff0000')
            return
        self.files = valid_files
        count = len(valid_files)
        if count == 1:
            fp = valid_files[0]
            name = Path(fp).name
            if len(name) > 50:
                name = name[:47] + "..."
            size_bytes = os.path.getsize(fp)
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            dims = ""
            try:
                with Image.open(fp) as img:
                    dims = f"  ·  {img.width} × {img.height}px"
            except Exception:
                pass
            self.file_label.configure(
                text=f"🎯  {name}  ·  {size_str}{dims}",
                fg='#30d158'
            )
            self.drop_label.configure(text="✓  1 file loaded", fg='#30d158')
        else:
            self.file_label.configure(text=f"🎯  {count} files selected", fg='#30d158')
            self.drop_label.configure(text=f"✓  {count} files loaded", fg='#30d158')
        self._set_nuke_button_state('normal')
        self.preview_btn.configure(state='normal')
        self._drop_zone_state = 'loaded'
        self._draw_border()
        if skipped > 0:
            self._update_status(f"Targets locked ({skipped} unsupported skipped)", '#ff9f0a')
        else:
            self._update_status("Targets locked", '#ff9f0a')

    def _nuke(self):
        if not self.files:
            self._update_status("No target", '#ff0000')
            return

        total = len(self.files)
        noise_lvl = self.noise_level.get()
        if not self.noise_enabled.get():
            noise_lvl = 0
        use_audit = self.audit_logging.get()
        suffix = self.output_suffix.get().strip()

        # Scan all files before nuking for diff report
        before_scans = {}
        for fp in self.files:
            before_scans[fp] = MetaNuke.scan_metadata(fp)

        opts_parts = []
        if noise_lvl == 0:
            opts_parts.append("lossless (no noise)")
        else:
            opts_parts.append(f"noise level {noise_lvl}")
        if self.output_dir:
            opts_parts.append(f"output: {os.path.basename(self.output_dir)}")
        if suffix:
            opts_parts.append(f"suffix: {suffix}")
        opts_str = ' | '.join(opts_parts)

        if total == 1:
            msg = (f"Nuke all metadata from:\n\n{Path(self.files[0]).name}\n"
                   f"[{opts_str}]\n\nThis will permanently overwrite the file.\n"
                   "Proceed?")
        else:
            msg = (f"Bulk nuke — {total} files\n\n[{opts_str}]\n\n"
                   f"This will permanently overwrite all {total} files.\n"
                   "This cannot be undone.\n\nProceed?")

        if not messagebox.askyesno("Confirm Nuke", msg, icon='warning'):
            self._update_status("Aborted", '#ff9f0a')
            return

        self.is_processing = True
        self._set_nuke_button_state('disabled')
        self.preview_btn.configure(state='disabled')
        self._drop_zone_state = 'processing'
        self._draw_border()

        if self.output_dir:
            os.makedirs(self.output_dir, exist_ok=True)

        ok_count = 0
        fail_count = 0
        failed_files = []
        results = []
        diffs = []

        # Progress bar with ETA
        pf = tk.Frame(self.root, bg='#0a0a0a')
        pf.pack(fill='x', padx=20, pady=(0, 10), before=self.status_label.master)
        pl = tk.Label(pf, text="", font=('Menlo', 8), bg='#0a0a0a', fg='#cccccc')
        pl.pack()
        pc = tk.Canvas(pf, bg='#1a1a1a', height=16, highlightthickness=1, highlightbackground='#333333')
        pc.pack(fill='x')
        eta_label = tk.Label(pf, text="", font=('Menlo', 8), bg='#0a0a0a', fg='#888888')
        eta_label.pack()

        start_time = time.time()

        def draw_prog(cur, tot):
            pc.delete('all')
            if tot > 0:
                w = pc.winfo_width()
                fw = max(2, int(w * cur / tot))
                pc.create_rectangle(0, 0, fw, 16, fill='#cc0000', outline='', tags='bar')
                pc.create_text(w//2, 8, text=f"{cur}/{tot}", fill='#ffffff', font=('Menlo', 8, 'bold'))

        draw_prog(0, total)
        self.root.update()

        for i, fp in enumerate(self.files, 1):
            name = Path(fp).name
            self._update_status(f"Nuking {i} of {total}", '#ff3300')
            self.file_label.configure(text=f"☢️  {name}", fg='#ff9f0a')
            self.drop_label.configure(text=f"Processing {i} of {total}...", fg='#ff9f0a')
            pl.configure(text=f"  {name}")

            # ETA calculation
            if i > 1:
                elapsed = time.time() - start_time
                per_file = elapsed / (i - 1)
                remaining = per_file * (total - i + 1)
                if remaining < 60:
                    eta_label.configure(text=f"  ETA: {remaining:.0f}s remaining")
                else:
                    eta_label.configure(text=f"  ETA: {remaining/60:.1f}m remaining")

            draw_prog(i - 1, total)
            self.root.update()

            # Build output path with optional suffix
            output_path = None
            if self.output_dir or suffix:
                src_path = Path(fp)
                stem = src_path.stem
                ext = src_path.suffix
                new_name = f"{stem}{suffix}{ext}"
                out_dir = Path(self.output_dir) if self.output_dir else src_path.parent
                output_path = str(out_dir / new_name)

            success, message = MetaNuke.nuke_image(
                fp, noise_level=noise_lvl,
                output_path=output_path,
            )
            results.append((fp, success, message))

            # Build diff
            diff = MetaNuke.compare_metadata(before_scans[fp], output_path or fp)
            diffs.append(diff)

            if success:
                ok_count += 1
            else:
                fail_count += 1
                failed_files.append((name, message))

        draw_prog(total, total)
        pf.destroy()
        self.is_processing = False

        if use_audit:
            log_path = os.path.join(
                self.output_dir if self.output_dir else os.path.dirname(self.files[0]),
                'metanuke.log',
            )
            log_results(log_path, results)
            self._update_status(f"Logged: {os.path.basename(log_path)}", '#00ccff')
        else:
            self._update_status("All nuked" if fail_count == 0
                                else f"Partial: {ok_count} ✓  {fail_count} ✗",
                                '#30d158' if fail_count == 0 else '#ff9f0a')

        total_before = sum(1 for d in diffs if not d['was_clean'])
        total_cleaned = sum(1 for d in diffs if not d['is_clean'] and not d['was_clean'])
        removed_info_count = sum(len(d['removed_info']) for d in diffs)
        removed_markers_count = sum(len(d['removed_markers']) for d in diffs)

        # Results summary with diff
        sha_lines = []
        for idx, (p, s, m) in enumerate(results[:20]):
            status = "✓" if s else "✗"
            d = diffs[idx] if idx < len(diffs) else {}
            diff_note = ""
            if d.get('removed_markers'):
                diff_note = f"  — removed: {', '.join(d['removed_markers'][:3])}"
            elif d.get('removed_info'):
                diff_note = f"  — removed: {', '.join(list(d['removed_info'])[:3])}"
            elif d.get('was_clean'):
                diff_note = "  — already clean"
            sha_lines.append(f"  {status} {Path(p).name}{diff_note}")
        if len(results) > 20:
            sha_lines.append(f"  … and {len(results) - 20} more")

        summary_parts = [
            f"Nuke Results",
            f"✓ {ok_count}  ✗ {fail_count}  of {total}",
        ]
        if total_before > 0:
            summary_parts.append(f"\nMetadata cleaned: {total_cleaned} file(s)")
            summary_parts.append(f"Info fields removed: {removed_info_count}")
            summary_parts.append(f"Binary markers removed: {removed_markers_count}")
        summary_parts.append('')
        summary_parts.extend(sha_lines)
        messagebox.showinfo("Nuke Complete", '\n'.join(summary_parts))

        # Save config
        save_config({
            'noise_level': noise_lvl,
            'output_dir': self.output_dir,
            'audit_log': self.audit_logging.get(),
            'output_suffix': suffix,
        }, self.config_path)

        # Reset
        self.files = []
        self.file_label.configure(text="No file selected", fg='#777777')
        self._set_nuke_button_state('disabled')
        self.preview_btn.configure(state='disabled')
        self._drop_zone_state = 'default'
        self._draw_border()
        self.drop_label.configure(
            text="✓  All metadata destroyed" if fail_count == 0
            else f"✓  {ok_count} / ✗  {fail_count}",
            fg='#30d158' if fail_count == 0 else '#ff9f0a')

    def _update_status(self, text: str, color: str):
        self.status_label.configure(text=text, fg=color)
        self.root.update()

    def _set_nuke_button_state(self, state: str):
        self._nuke_button_state = state
        self._draw_nuke()

    def run(self):
        self.root.mainloop()
