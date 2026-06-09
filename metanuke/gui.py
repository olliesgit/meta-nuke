"""Meta Nuke GUI — Tkinter-based desktop interface."""

import os
import re
import sys
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


class MetaNukeGUI:
    """Dark-themed GUI for MetaNuke with drag-and-drop and full options."""

    def __init__(self, preloaded_files=None):
        if DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("META NUKE ☢️")
        self.root.geometry("560x620")
        self.root.configure(bg='#0a0a0a')
        self.root.resizable(False, False)

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
        self.audit_logging = tk.BooleanVar(value=False)
        self.output_dir: Optional[str] = None
        self.is_processing = False

        self.config_path = os.path.join(os.path.expanduser('~'), '.metanukerc')

        # Load saved config
        cfg = load_config(self.config_path)
        self.noise_level.set(cfg.get('noise_level', 5))
        self.audit_logging.set(cfg.get('audit_log', False))
        saved_out = cfg.get('output_dir')
        if saved_out and os.path.isdir(saved_out):
            self.output_dir = saved_out
            self.out_dir_label = None  # will be set in _setup_ui

        self._setup_styles()
        self._setup_ui()

        if preloaded_files:
            self._set_files(preloaded_files)

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('Nuke.TButton', font=('Menlo', 14, 'bold'),
                             padding=15, background='#ff0000', foreground='#ffffff')
        self.style.configure('Status.TLabel', font=('Menlo', 10),
                             background='#0a0a0a', foreground='#00ff00')

    def _setup_ui(self):
        main_frame = tk.Frame(self.root, bg='#0a0a0a')
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Title
        tk.Label(main_frame, text="☢️ META NUKE ☢️",
                 font=('Menlo', 24, 'bold'), bg='#0a0a0a', fg='#ff3300').pack(pady=(0, 5))
        tk.Label(main_frame, text="FORENSICALLY SAFE • NUCLEAR DESTRUCTION",
                 font=('Menlo', 10), bg='#0a0a0a', fg='#ff6600').pack(pady=(0, 20))

        # Drop zone
        self._drop_zone_state = 'default'
        self.drop_zone = tk.Canvas(main_frame, bg='#0d0303', highlightthickness=0,
                                   bd=0, height=150)
        self.drop_zone.pack(fill='x', pady=(0, 15))

        self.drop_label = tk.Label(self.drop_zone,
            text="📁 DROP IMAGE(S) HERE\nor click to browse\n(supports bulk processing)",
            font=('Menlo', 12), bg='#0d0303', fg='#cccccc', justify='center')
        self.drop_zone.create_window(0, 0, window=self.drop_label,
                                     anchor='center', tags='drop_label_window')

        def _draw_border():
            self.drop_zone.delete('border')
            w = self.drop_zone.winfo_width()
            h = self.drop_zone.winfo_height()
            if w < 10 or h < 10:
                return
            palettes = {
                'default':    {'outer': '#3a0000', 'inner': '#5a0000', 'brackets': '#aa0000'},
                'hover':      {'outer': '#8a0000', 'inner': '#b80000', 'brackets': '#ff3300'},
                'loaded':     {'outer': '#3a0000', 'inner': '#5a0000', 'brackets': '#00cc66'},
                'processing': {'outer': '#3a0000', 'inner': '#5a0000', 'brackets': '#ffaa00'},
            }
            c = palettes.get(self._drop_zone_state, palettes['default'])
            self.drop_zone.create_rectangle(1, 1, w-2, h-2, outline=c['outer'], width=1, tags='border')
            self.drop_zone.create_rectangle(5, 5, w-6, h-6, outline=c['inner'], width=1, tags='border')
            bl = min(28, max(16, w//8))
            m = 14
            for x1, y1, x2, y2 in [(m,m,m+bl,m), (m,m,m,m+bl), (w-m,m,w-m-bl,m), (w-m,m,w-m,m+bl),
                                    (m,h-m,m+bl,h-m), (m,h-m,m,h-m-bl), (w-m,h-m,w-m-bl,h-m), (w-m,h-m,w-m,h-m-bl)]:
                self.drop_zone.create_line(x1, y1, x2, y2, fill=c['brackets'], width=2, tags='border')

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
        else:
            self.drop_label.configure(text="📁 CLICK TO SELECT IMAGES\n(supports bulk processing)")

        # Options panel — noise, output dir, preview, audit log
        opts = tk.LabelFrame(main_frame, text="OPTIONS", font=('Menlo', 10, 'bold'),
                              bg='#0a0a0a', fg='#ff6600', bd=1, relief='solid',
                              padx=10, pady=10)
        opts.pack(fill='x', pady=(0, 12))

        # Noise slider
        nr = tk.Frame(opts, bg='#0a0a0a')
        nr.pack(fill='x', pady=(4, 6))
        tk.Label(nr, text="FORENSIC NOISE", font=('Menlo', 11, 'bold'),
                 bg='#0a0a0a', fg='#ff6600', width=16, anchor='w').pack(side='left')
        tk.Scale(nr, from_=0, to=10, orient='horizontal', variable=self.noise_level,
                 showvalue=True, bg='#1a1a1a', fg='#ffffff', troughcolor='#333333',
                 highlightthickness=0, bd=0, length=220, sliderrelief='flat',
                 width=20, font=('Menlo', 11)).pack(side='left', padx=(0, 8))
        tk.Label(nr, text="0=lossless  10=max", font=('Menlo', 10),
                 bg='#0a0a0a', fg='#888888').pack(side='left')

        # Output dir
        orow = tk.Frame(opts, bg='#0a0a0a')
        orow.pack(fill='x', pady=(4, 6))
        tk.Label(orow, text="OUTPUT DIRECTORY", font=('Menlo', 11, 'bold'),
                 bg='#0a0a0a', fg='#ff6600', width=16, anchor='w').pack(side='left')
        self.out_dir_label = tk.Label(orow, text="(overwrite in-place)" if not self.output_dir
                                       else self.output_dir,
                                       font=('Menlo', 10), bg='#0a0a0a',
                                       fg='#888888' if not self.output_dir else '#00cc66', anchor='w')
        self.out_dir_label.pack(side='left', fill='x', expand=True)
        tk.Button(orow, text="BROWSE", font=('Menlo', 10, 'bold'),
                  bg='#333333', fg='#cccccc', bd=0, padx=10, pady=4,
                  activebackground='#555555', activeforeground='#ffffff',
                  command=self._browse_output_dir).pack(side='right')
        tk.Button(orow, text="✕", font=('Menlo', 12, 'bold'), bg='#222222', fg='#888888', bd=0,
                  activebackground='#444444', activeforeground='#ff0000',
                  command=self._clear_output_dir).pack(side='right', padx=(0, 6))

        # Preview + audit log
        arow = tk.Frame(opts, bg='#0a0a0a')
        arow.pack(fill='x', pady=(6, 2))
        self.preview_btn = tk.Button(arow, text="🔍  PREVIEW METADATA", font=('Menlo', 11, 'bold'),
                                      bg='#333333', fg='#cccccc', bd=0, padx=14, pady=6,
                                      activebackground='#555555', activeforeground='#ffffff',
                                      state='disabled', command=self._preview_metadata)
        self.preview_btn.pack(side='left')
        tk.Checkbutton(arow, text="AUDIT LOG", font=('Menlo', 11),
                       variable=self.audit_logging, bg='#0a0a0a',
                       fg='#aaaaaa', selectcolor='#222222',
                       activebackground='#0a0a0a', activeforeground='#ffffff',
                       onvalue=True, offvalue=False).pack(side='left', padx=(14, 0))
        tk.Label(arow, text="~/.metanukerc", font=('Menlo', 8),
                 bg='#0a0a0a', fg='#555555').pack(side='right')
        # File display
        self.file_label = tk.Label(main_frame, text="No file selected", font=('Menlo', 11),
                                    bg='#0a0a0a', fg='#ffffff', wraplength=450)
        self.file_label.pack(pady=(0, 15))

        # NUKE button (Canvas-based for consistent macOS rendering)
        self.nuke_button = tk.Canvas(main_frame, bg='#0a0a0a', highlightthickness=0,
                                      bd=0, width=280, height=60)
        self.nuke_button.pack(pady=(0, 15))
        self._nuke_button_state = 'disabled'

        def _draw_nuke():
            self.nuke_button.delete('btn')
            w = self.nuke_button.winfo_width()
            h = self.nuke_button.winfo_height()
            if w < 10 or h < 10:
                return
            if self._nuke_button_state == 'normal':
                bg, border, highlight, fg, cursor = '#8B0000', '#cc0000', '#a00000', '#ffffff', 'hand2'
            else:
                bg, border, highlight, fg, cursor = '#3a3a3a', '#555555', '#4a4a4a', '#999999', 'arrow'
            self.nuke_button.configure(cursor=cursor)
            self.nuke_button.create_rectangle(1, 1, w-2, h-2, fill=bg, outline=border, width=2, tags='btn')
            self.nuke_button.create_line(8, 4, w-9, 4, fill=highlight, width=1, tags='btn')
            self.nuke_button.create_text(w//2, h//2+1, text="☢️  NUKE META  ☢️",
                                          font=('Menlo', 16, 'bold'), fill=fg, tags='btn')

        self._draw_nuke = _draw_nuke
        self.nuke_button.bind('<Configure>', lambda e: _draw_nuke())
        self.nuke_button.bind('<Button-1>', lambda e: self._nuke()
                              if (self._nuke_button_state == 'normal' and not self.is_processing)
                              else None)
        _draw_nuke()

        # Status
        self.status_label = tk.Label(main_frame, text="READY", font=('Menlo', 20, 'bold'),
                                      bg='#0a0a0a', fg='#00ffaa')
        self.status_label.pack(pady=(0, 15))

        # Info footer
        tk.Label(main_frame,
                 text="100% OFFLINE • NUCLEAR METADATA DESTRUCTION\n"
                      "EXIF • IPTC • XMP • ICC PROFILES • GPS • TIMESTAMPS\n"
                      "COLOR PROFILES • SCREEN TYPE • DPI • CAMERA INFO • SOFTWARE",
                 font=('Menlo', 10, 'bold'), bg='#0a0a0a', fg='#ffffff',
                 justify='center').pack(side='bottom', pady=(0, 10))

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
            self.out_dir_label.configure(text=d, fg='#00cc66')

    def _clear_output_dir(self):
        self.output_dir = None
        self.out_dir_label.configure(text="(overwrite in-place)", fg='#888888')

    def _preview_metadata(self):
        if not self.files or self.is_processing:
            return
        lines = []
        for f in self.files:
            name = Path(f).name
            meta = []
            try:
                with Image.open(f) as img:
                    if img.info:
                        meta.extend(f'{k}={str(v)[:40]}' for k, v in img.info.items())
                raw = Path(f).read_bytes()
                for sig, label in [(b'Exif\x00\x00', 'EXIF'), (b'<x:xmpmeta', 'XMP'),
                                   (b'ICC_PROFILE', 'ICC')]:
                    if sig in raw:
                        meta.append(label)
            except Exception as e:
                meta.append(f'ERR:{e}')
            lines.append(f'{name}:\n  {"  ".join(meta) if meta else "clean"}')
        messagebox.showinfo("METADATA PREVIEW", '\n\n'.join(lines))

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
        raw_data = event.data
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
            self._update_status("NO VALID FILES", '#ff0000')
            return
        self.files = valid_files
        count = len(valid_files)
        if count == 1:
            name = Path(valid_files[0]).name
            if len(name) > 50:
                name = name[:47] + "..."
            self.file_label.configure(text=f"🎯 {name}", fg='#00ff00')
            self.drop_label.configure(text="✓ 1 FILE LOADED", fg='#00ff00')
        else:
            self.file_label.configure(text=f"🎯 {count} FILES SELECTED", fg='#00ff00')
            self.drop_label.configure(text=f"✓ {count} FILES LOADED", fg='#00ff00')
        self._set_nuke_button_state('normal')
        self.preview_btn.configure(state='normal')
        self._drop_zone_state = 'loaded'
        self._draw_border()
        if skipped > 0:
            self._update_status(f"TARGETS LOCKED ({skipped} skipped)", '#ffaa00')
        else:
            self._update_status("TARGETS LOCKED", '#ffaa00')

    def _nuke(self):
        if not self.files:
            self._update_status("NO TARGET", '#ff0000')
            return
        total = len(self.files)
        noise_lvl = self.noise_level.get()
        use_audit = self.audit_logging.get()

        opts_parts = []
        if noise_lvl == 0:
            opts_parts.append("lossless (no noise)")
        else:
            opts_parts.append(f"noise level {noise_lvl}")
        if self.output_dir:
            opts_parts.append(f"output: {os.path.basename(self.output_dir)}")
        opts_str = ' | '.join(opts_parts)

        if total == 1:
            msg = (f"☢️ NUKE ALL METADATA FROM:\n\n{Path(self.files[0]).name}\n"
                   f"[{opts_str}]\n\nThis will PERMANENTLY overwrite the file.\n"
                   "Proceed?")
        else:
            msg = (f"☢️ BULK NUKE - {total} FILES\n\n[{opts_str}]\n\n"
                   f"This will PERMANENTLY overwrite ALL {total} files.\n"
                   "⚠️ THIS CANNOT BE UNDONE ⚠️\n\nProceed?")

        if not messagebox.askyesno("CONFIRM NUKE", msg, icon='warning'):
            self._update_status("ABORTED", '#ffaa00')
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

        # Progress bar
        pf = tk.Frame(self.root, bg='#0a0a0a')
        pf.pack(fill='x', padx=20, pady=(0, 10), before=self.status_label.master)
        pl = tk.Label(pf, text="", font=('Menlo', 8), bg='#0a0a0a', fg='#cccccc')
        pl.pack()
        pc = tk.Canvas(pf, bg='#1a1a1a', height=16, highlightthickness=1, highlightbackground='#333333')
        pc.pack(fill='x')

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
            self._update_status(f"NUKING {i}/{total}", '#ff3300')
            self.file_label.configure(text=f"☢️ {name}", fg='#ffaa00')
            self.drop_label.configure(text=f"Processing {i} of {total}...", fg='#ffaa00')
            pl.configure(text=f"  {name}")
            draw_prog(i - 1, total)
            self.root.update()

            success, message = MetaNuke.nuke_image(
                fp, noise_level=noise_lvl,
                output_path=str(Path(self.output_dir) / Path(fp).name) if self.output_dir else None,
            )
            results.append((fp, success, message))
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
            self._update_status(f"LOGGED: {os.path.basename(log_path)}", '#00ccff')
        else:
            self._update_status("☢️ ALL NUKED ☢️" if fail_count == 0
                                else f"PARTIAL: {ok_count}✓ {fail_count}✗",
                                '#00ff00' if fail_count == 0 else '#ffaa00')
        self.drop_label.configure(
            text="✓ ALL METADATA DESTROYED" if fail_count == 0
            else f"✓ {ok_count} / ✗ {fail_count}",
            fg='#00ff00' if fail_count == 0 else '#ffaa00')

        # Results summary with SHA256
        sha_lines = []
        for p, s, m in results[:20]:
            status = "✓" if s else "✗"
            sha_lines.append(f"  {status} {Path(p).name} — {m[:80]}")
        if len(results) > 20:
            sha_lines.append(f"  ... and {len(results) - 20} more")
        summary = (f"☢️ {'BULK ' if total > 1 else ''}NUKE RESULTS ☢️\n\n"
                   f"✓ {ok_count}  ✗ {fail_count}  of {total}\n\n" + '\n'.join(sha_lines))
        messagebox.showinfo("NUKE COMPLETE", summary)

        # Save config
        save_config({'noise_level': noise_lvl, 'output_dir': self.output_dir,
                      'audit_log': self.audit_logging.get()}, self.config_path)

        # Reset
        self.files = []
        self.file_label.configure(text="No file selected", fg='#ffffff')
        self._set_nuke_button_state('disabled')
        self.preview_btn.configure(state='disabled')
        self._drop_zone_state = 'default'
        self._draw_border()
        text = ("📁 DROP IMAGE(S) HERE\nor click to browse\n(supports bulk processing)"
                if DND_AVAILABLE else
                "📁 CLICK TO SELECT IMAGES\n(supports bulk processing)")
        self.drop_label.configure(text=text, fg='#cccccc')

    def _update_status(self, text: str, color: str):
        self.status_label.configure(text=text, fg=color)
        self.root.update()

    def _set_nuke_button_state(self, state: str):
        self._nuke_button_state = state
        self._draw_nuke()

    def run(self):
        self.root.mainloop()
