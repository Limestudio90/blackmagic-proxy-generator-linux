#!/usr/bin/env python3
import os
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import *

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_store
import resolve_engine
from engine import ProxyEngine

APP_TITLE = "Blackmagic Proxy Generator"
ICON_PATH = "/opt/resolve/graphics/application-x-braw-clip_48x48_mimetypes.png"
ICON_PATH_BIG = "/opt/resolve/graphics/application-x-braw-clip_256x256_mimetypes.png"

CODEC_LABELS = {k: v["label"] for k, v in resolve_engine.CODEC_PRESETS.items()}
RESOLUTION_LABELS = {
    "full": "Originale",
    "1080": "1080p",
    "720": "720p",
    "540": "540p",
}

STATUS_STYLE = {
    "In coda": "secondary",
    "In corso": "info",
    "In attesa (Resolve occupato)": "warning",
    "Completato": "success",
    "Errore": "danger",
}


class App:
    def __init__(self, root: tb.Window):
        self.root = root
        self.cfg = config_store.load()
        self.event_queue = queue.Queue()
        self.row_by_file = {}
        self.tray_icon = None
        self.watching = True

        root.title(APP_TITLE)
        root.geometry("980x620")
        root.minsize(760, 480)
        try:
            root.iconphoto(True, tk.PhotoImage(file=ICON_PATH))
        except Exception:
            pass
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.engine = ProxyEngine(cfg_getter=lambda: self.cfg, event_cb=self._on_event)
        self.engine.start()
        self._poll_events()
        self._setup_tray()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # Header
        header = tb.Frame(self.root, padding=(18, 14), bootstyle="dark")
        header.pack(fill="x")
        try:
            self._icon_img = tk.PhotoImage(file=ICON_PATH)
            tb.Label(header, image=self._icon_img, bootstyle="inverse-dark").pack(side="left", padx=(0, 10))
        except Exception:
            pass
        title_box = tb.Frame(header, bootstyle="dark")
        title_box.pack(side="left")
        tb.Label(title_box, text=APP_TITLE, font=("Inter", 16, "bold"),
                  bootstyle="inverse-dark").pack(anchor="w")
        tb.Label(title_box, text="Generazione automatica proxy via motore DaVinci Resolve",
                  font=("Inter", 9), bootstyle="inverse-dark").pack(anchor="w")

        self.status_badge = tb.Label(header, text="●  In ascolto", font=("Inter", 10, "bold"),
                                      bootstyle="success-inverse", padding=(10, 4))
        self.status_badge.pack(side="right")

        body = tb.Frame(self.root, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Sidebar
        sidebar = tb.Frame(body, width=280)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        sidebar.grid_propagate(False)

        folders_card = tb.Labelframe(sidebar, text=" Cartelle sorvegliate", padding=12, bootstyle="secondary")
        folders_card.pack(fill="x", pady=(0, 14))

        list_frame = tb.Frame(folders_card)
        list_frame.pack(fill="both", expand=True)
        self.folder_list = tk.Listbox(list_frame, height=6, relief="flat", highlightthickness=1,
                                       activestyle="none", borderwidth=0)
        self.folder_list.pack(side="left", fill="both", expand=True)
        scroll = tb.Scrollbar(list_frame, command=self.folder_list.yview, bootstyle="round")
        scroll.pack(side="right", fill="y")
        self.folder_list.configure(yscrollcommand=scroll.set)
        for wf in self.cfg["watch_folders"]:
            self.folder_list.insert("end", wf["path"])

        btns = tb.Frame(folders_card)
        btns.pack(fill="x", pady=(10, 0))
        tb.Button(btns, text="＋ Aggiungi", command=self._add_folder,
                   bootstyle="success-outline").pack(side="left", expand=True, fill="x", padx=(0, 5))
        tb.Button(btns, text="－ Rimuovi", command=self._remove_folder,
                   bootstyle="danger-outline").pack(side="left", expand=True, fill="x")

        settings_card = tb.Labelframe(sidebar, text=" Impostazioni proxy", padding=12, bootstyle="secondary")
        settings_card.pack(fill="x", pady=(0, 14))

        tb.Label(settings_card, text="Codec").pack(anchor="w")
        self.codec_var = tk.StringVar(value=CODEC_LABELS[self.cfg["codec"]])
        codec_combo = tb.Combobox(settings_card, textvariable=self.codec_var, state="readonly",
                                    values=list(CODEC_LABELS.values()), bootstyle="secondary")
        codec_combo.pack(fill="x", pady=(2, 10))
        codec_combo.bind("<<ComboboxSelected>>", self._on_settings_change)

        tb.Label(settings_card, text="Risoluzione").pack(anchor="w")
        self.res_var = tk.StringVar(value=RESOLUTION_LABELS[self.cfg["resolution"]])
        res_combo = tb.Combobox(settings_card, textvariable=self.res_var, state="readonly",
                                  values=list(RESOLUTION_LABELS.values()), bootstyle="secondary")
        res_combo.pack(fill="x", pady=(2, 0))
        res_combo.bind("<<ComboboxSelected>>", self._on_settings_change)

        self.watch_toggle_btn = tb.Button(sidebar, text="⏸  Metti in pausa", bootstyle="warning",
                                            command=self._toggle_watching)
        self.watch_toggle_btn.pack(fill="x")

        # Main area: notebook with queue + log
        main = tb.Frame(body)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)

        notebook = tb.Notebook(main, bootstyle="secondary")
        notebook.grid(row=0, column=0, sticky="nsew")

        queue_tab = tb.Frame(notebook, padding=10)
        notebook.add(queue_tab, text="  Coda di elaborazione  ")
        queue_tab.rowconfigure(0, weight=1)
        queue_tab.columnconfigure(0, weight=1)

        columns = ("file", "status", "progress")
        self.tree = tb.Treeview(queue_tab, columns=columns, show="headings",
                                  bootstyle="secondary", height=14)
        self.tree.heading("file", text="File")
        self.tree.heading("status", text="Stato")
        self.tree.heading("progress", text="Avanzamento")
        self.tree.column("file", width=480)
        self.tree.column("status", width=200)
        self.tree.column("progress", width=110, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        tscroll = tb.Scrollbar(queue_tab, command=self.tree.yview, bootstyle="round")
        tscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tscroll.set)
        self.tree.bind("<Double-1>", self._on_row_double_click)
        for name, style in STATUS_STYLE.items():
            self.tree.tag_configure(name, foreground=tb.Style().colors.get(style))

        log_tab = tb.Frame(notebook, padding=10)
        notebook.add(log_tab, text="  Log  ")
        log_tab.rowconfigure(0, weight=1)
        log_tab.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_tab, wrap="word", relief="flat", highlightthickness=0,
                                 bg=tb.Style().colors.get("bg"), fg=tb.Style().colors.get("fg"),
                                 insertbackground=tb.Style().colors.get("fg"))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------ actions
    def _add_folder(self):
        path = filedialog.askdirectory(title="Scegli cartella da sorvegliare")
        if not path:
            return
        if any(wf["path"] == path for wf in self.cfg["watch_folders"]):
            return
        self.cfg["watch_folders"].append({"path": path, "output": ""})
        config_store.save(self.cfg)
        self.folder_list.insert("end", path)
        self.engine.reload_watch_folders()

    def _remove_folder(self):
        sel = self.folder_list.curselection()
        if not sel:
            return
        idx = sel[0]
        path = self.folder_list.get(idx)
        self.cfg["watch_folders"] = [w for w in self.cfg["watch_folders"] if w["path"] != path]
        config_store.save(self.cfg)
        self.folder_list.delete(idx)
        self.engine.reload_watch_folders()

    def _on_settings_change(self, _evt=None):
        codec_key = next(k for k, v in CODEC_LABELS.items() if v == self.codec_var.get())
        res_key = next(k for k, v in RESOLUTION_LABELS.items() if v == self.res_var.get())
        self.cfg["codec"] = codec_key
        self.cfg["resolution"] = res_key
        config_store.save(self.cfg)

    def _toggle_watching(self):
        if self.watching:
            self.engine.stop()
            self.watching = False
            self.watch_toggle_btn.configure(text="▶  Riprendi", bootstyle="success")
            self.status_badge.configure(text="●  In pausa", bootstyle="warning-inverse")
        else:
            self.engine.start()
            self.watching = True
            self.watch_toggle_btn.configure(text="⏸  Metti in pausa", bootstyle="warning")
            self.status_badge.configure(text="●  In ascolto", bootstyle="success-inverse")

    def _on_row_double_click(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        status = item["values"][1]
        filepath = self._file_for_row(sel[0])
        if filepath and "occupato" in str(status).lower():
            if messagebox.askyesno(
                "Resolve occupato",
                "Resolve ha un progetto aperto. Generare comunque il proxy ora "
                "interromperà quello che stai facendo in Resolve. Procedere?"):
                self.engine.force_generate(filepath)

    def _file_for_row(self, row_id):
        for f, r in self.row_by_file.items():
            if r == row_id:
                return f
        return None

    # -------------------------------------------------------------- tray
    def _setup_tray(self):
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return
        image = Image.open(ICON_PATH_BIG)
        menu = pystray.Menu(
            pystray.MenuItem("Apri", self._show_window, default=True),
            pystray.MenuItem("Esci", self._quit),
        )
        self.tray_icon = pystray.Icon(APP_TITLE, image, APP_TITLE, menu)
        import threading
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_window(self, *_):
        self.root.after(0, self.root.deiconify)

    def _on_close(self):
        if self.tray_icon:
            self.root.withdraw()
        else:
            self._quit()

    def _quit(self, *_):
        self.engine.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ------------------------------------------------------------- events
    def _on_event(self, evt):
        self.event_queue.put(evt)

    def _poll_events(self):
        try:
            while True:
                evt = self.event_queue.get_nowait()
                self._handle_event(evt)
        except queue.Empty:
            pass
        self.root.after(300, self._poll_events)

    def _handle_event(self, evt):
        kind = evt["kind"]
        if kind == "log":
            self._log(evt["msg"])
        elif kind == "queued":
            row = self.tree.insert("", "end", values=(evt["file"], "In coda", ""), tags=("In coda",))
            self.row_by_file[evt["file"]] = row
            self._log(f"In coda: {evt['file']}")
        elif kind == "status":
            row = self.row_by_file.get(evt["file"])
            if row:
                self.tree.set(row, "status", evt["status"])
                self.tree.item(row, tags=(evt["status"],))
        elif kind == "progress":
            row = self.row_by_file.get(evt["file"])
            if row:
                self.tree.set(row, "progress", f"{evt['pct']}%")
        elif kind == "done":
            row = self.row_by_file.get(evt["file"])
            if row:
                self.tree.set(row, "status", "Completato")
                self.tree.set(row, "progress", "100%")
                self.tree.item(row, tags=("Completato",))
            self._log(f"Completato: {evt['file']} -> {evt.get('output')}")
        elif kind == "error":
            row = self.row_by_file.get(evt["file"])
            if row:
                self.tree.set(row, "status", "Errore")
                self.tree.item(row, tags=("Errore",))
            self._log(f"ERRORE su {evt['file']}: {evt['error']}")

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def main():
    root = tb.Window(themename="darkly")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
