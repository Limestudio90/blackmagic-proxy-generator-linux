"""Core watch-folder + render engine, used by the GUI (and could be used headless)."""
import os
import queue
import subprocess
import threading
import time

import resolve_engine

NOTIFY_AVAILABLE = os.path.exists("/usr/bin/notify-send")


def notify(title, body, urgency="normal"):
    if NOTIFY_AVAILABLE:
        try:
            subprocess.Popen(["notify-send", "-u", urgency, "-a", "Blackmagic Proxy Generator", title, body])
        except Exception:
            pass


class ProxyEngine:
    def __init__(self, cfg_getter, event_cb):
        """
        cfg_getter: callable returning the current config dict (live, so GUI edits apply)
        event_cb: callable(event_dict) - thread-safe-ish, called from worker/watcher threads.
                  Event kinds: log, queued, status, progress, done, error
        """
        self.cfg_getter = cfg_getter
        self.event_cb = event_cb
        self.job_queue = queue.Queue()
        self._watch_procs = {}
        self._stop = threading.Event()
        self._worker_thread = None
        self._watcher_threads = []
        self._pending_force = set()  # paths the user said "generate anyway"

    # ---- lifecycle -----------------------------------------------------
    def start(self):
        self._stop.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        self._restart_watchers()

    def stop(self):
        self._stop.set()
        for p in self._watch_procs.values():
            try:
                p.terminate()
            except Exception:
                pass
        self._watch_procs.clear()

    def reload_watch_folders(self):
        self._restart_watchers()

    def _restart_watchers(self):
        for p in self._watch_procs.values():
            try:
                p.terminate()
            except Exception:
                pass
        self._watch_procs.clear()
        cfg = self.cfg_getter()
        for wf in cfg["watch_folders"]:
            path = wf["path"]
            if not os.path.isdir(path):
                self.event_cb({"kind": "log", "msg": f"Cartella non trovata, salto: {path}"})
                continue
            t = threading.Thread(target=self._watch_folder, args=(path,), daemon=True)
            t.start()
            self._watcher_threads.append(t)

    # ---- watching --------------------------------------------------------
    def _watch_folder(self, path):
        cmd = ["inotifywait", "-m", "-r", "-e", "close_write", "-e", "moved_to",
               "--format", "%w%f", path]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self._watch_procs[path] = proc
        self.event_cb({"kind": "log", "msg": f"In ascolto su: {path}"})
        for line in proc.stdout:
            if self._stop.is_set():
                break
            filepath = line.strip()
            if filepath:
                self._maybe_enqueue(filepath, wf_path=path)

    def _maybe_enqueue(self, filepath, wf_path):
        cfg = self.cfg_getter()
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in cfg["extensions"]:
            return
        base = os.path.basename(filepath)
        if "/Proxy/" in filepath or base.startswith("._"):
            return
        if not self._wait_stable(filepath, cfg.get("stabilize_seconds", 2)):
            return
        wf_cfg = next((w for w in cfg["watch_folders"] if w["path"] == wf_path), None)
        output_dir = self._resolve_output_dir(filepath, wf_path, wf_cfg)
        self.event_cb({"kind": "queued", "file": filepath})
        self.job_queue.put((filepath, output_dir))

    def _wait_stable(self, filepath, seconds):
        try:
            last = -1
            stable_checks = 0
            for _ in range(60):
                if not os.path.exists(filepath):
                    return False
                size = os.path.getsize(filepath)
                if size == last:
                    stable_checks += 1
                    if stable_checks >= max(1, seconds):
                        return True
                else:
                    stable_checks = 0
                last = size
                time.sleep(1)
            return True
        except OSError:
            return False

    def _resolve_output_dir(self, filepath, wf_path, wf_cfg):
        rel_dir = os.path.dirname(os.path.relpath(filepath, wf_path))
        custom_out = wf_cfg.get("output") if wf_cfg else ""
        if custom_out:
            return os.path.join(custom_out, rel_dir) if rel_dir != "." else custom_out
        base_out = os.path.join(wf_path, "Proxy")
        return os.path.join(base_out, rel_dir) if rel_dir != "." else base_out

    # ---- rendering ---------------------------------------------------
    def force_generate(self, filepath):
        self._pending_force.add(filepath)

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                filepath, output_dir = self.job_queue.get(timeout=1)
            except queue.Empty:
                continue
            self._process_job(filepath, output_dir)

    def _process_job(self, filepath, output_dir):
        cfg = self.cfg_getter()
        base = os.path.splitext(os.path.basename(filepath))[0] + cfg.get("suffix", "_proxy")
        self.event_cb({"kind": "status", "file": filepath, "status": "In corso"})

        def progress(pct):
            self.event_cb({"kind": "progress", "file": filepath, "pct": pct})

        force = filepath in self._pending_force
        while True:
            try:
                out = resolve_engine.render_clip(
                    filepath, output_dir, base,
                    cfg["codec"], cfg["resolution"],
                    progress_cb=progress, force_even_if_busy=force,
                )
                self.event_cb({"kind": "done", "file": filepath, "output": out})
                notify("Proxy pronto", os.path.basename(out or filepath))
                self._pending_force.discard(filepath)
                return
            except resolve_engine.BusyError:
                self.event_cb({"kind": "status", "file": filepath,
                                "status": "In attesa (Resolve occupato)"})
                notify("Resolve è occupato",
                       f"{os.path.basename(filepath)} è in coda finché non chiudi il progetto aperto in Resolve",
                       urgency="low")
                # wait, checking periodically, unless user forces
                for _ in range(30):
                    time.sleep(2)
                    if filepath in self._pending_force:
                        force = True
                        break
                    if self._stop.is_set():
                        return
                continue
            except Exception as e:
                self.event_cb({"kind": "error", "file": filepath, "error": str(e)})
                notify("Errore generazione proxy", f"{os.path.basename(filepath)}: {e}", urgency="critical")
                return
