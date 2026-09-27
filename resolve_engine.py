"""
Wraps DaVinci Resolve's scripting API to render proxy media for a single
source clip at a time, mimicking what Blackmagic's Windows "Proxy Generator"
does under the hood (it uses the same decode/encode engine as Resolve).

Design notes:
- If no Resolve instance is running, we launch one headless (`-nogui`) and
  keep a dedicated project ("BMPG Proxy Generator") for our own use.
- If Resolve is already running (the user has it open editing), we do NOT
  silently steal their open project. `is_project_busy()` lets the caller
  decide whether to wait or force it.
"""
import os
import subprocess
import time
import glob

RESOLVE_INSTALL_DIR = "/opt/resolve"
RESOLVE_BIN = "/opt/resolve/bin/resolve"
SCRIPT_API = "/opt/resolve/Developer/Scripting"
SCRIPT_LIB = "/opt/resolve/libs/Fusion/fusionscript.so"
PROXY_PROJECT_NAME = "BMPG Proxy Generator"

CODEC_PRESETS = {
    "h264_proxy": dict(format="mp4", codec="H.264", label="H.264 Proxy (leggero)"),
    "prores_proxy": dict(format="QuickTime", codec="ProRes422Proxy", label="ProRes 422 Proxy"),
    "prores_lt": dict(format="QuickTime", codec="ProRes422LT", label="ProRes 422 LT"),
    "dnxhr_lb": dict(format="QuickTime", codec="DNxHR_LB", label="DNxHR LB"),
    "dnxhr_sq": dict(format="QuickTime", codec="DNxHR_SQ", label="DNxHR SQ"),
}

RESOLUTION_PRESETS = {
    "full": None,
    "1080": 1080,
    "720": 720,
    "540": 540,
}


def _setup_env():
    os.environ.setdefault("RESOLVE_SCRIPT_API", SCRIPT_API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", SCRIPT_LIB)
    modules_path = os.path.join(SCRIPT_API, "Modules")
    pp = os.environ.get("PYTHONPATH", "")
    if modules_path not in pp.split(":"):
        os.environ["PYTHONPATH"] = f"{pp}:{modules_path}" if pp else modules_path


def _import_dvr():
    _setup_env()
    import DaVinciResolveScript as dvr  # noqa
    return dvr


def is_resolve_running():
    try:
        out = subprocess.check_output(["pgrep", "-af", "resolve"], text=True)
        return any("VideoIO" in l or l.strip().endswith("/resolve") or "/opt/resolve/bin/resolve" in l
                   for l in out.splitlines())
    except subprocess.CalledProcessError:
        return False


def launch_headless(timeout=60):
    """Launch Resolve in -nogui mode if it's not already running. Returns once scripting connects."""
    if not is_resolve_running():
        subprocess.Popen(
            [RESOLVE_BIN, "-nogui"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    dvr = _import_dvr()
    deadline = time.time() + timeout
    resolve = None
    while time.time() < deadline:
        try:
            resolve = dvr.scriptapp("Resolve")
        except Exception:
            resolve = None
        if resolve is not None:
            return resolve
        time.sleep(1.5)
    raise RuntimeError("Impossibile connettersi a DaVinci Resolve entro il timeout")


def get_resolve():
    dvr = _import_dvr()
    return dvr.scriptapp("Resolve")


def was_launched_headless_by_us():
    # Best-effort: true if the running resolve process has -nogui in its cmdline.
    try:
        out = subprocess.check_output(["pgrep", "-af", "resolve"], text=True)
        return any("-nogui" in l for l in out.splitlines())
    except subprocess.CalledProcessError:
        return False


def is_project_busy(resolve, our_project_name=PROXY_PROJECT_NAME):
    """True if a *different*, user-owned project is currently open (i.e. we'd disrupt them)."""
    pm = resolve.GetProjectManager()
    current = pm.GetCurrentProject()
    if current is None:
        return False
    return current.GetName() != our_project_name


def get_or_create_proxy_project(resolve):
    pm = resolve.GetProjectManager()
    current = pm.GetCurrentProject()
    if current is not None and current.GetName() == PROXY_PROJECT_NAME:
        return current
    project = pm.LoadProject(PROXY_PROJECT_NAME)
    if project is None:
        project = pm.CreateProject(PROXY_PROJECT_NAME)
    return project


def render_clip(input_path, output_dir, output_basename, codec_key, resolution_key,
                 progress_cb=None, force_even_if_busy=False):
    """
    Renders one clip to a proxy file. Raises RuntimeError on failure/refusal.
    progress_cb(percent:int) is called periodically if given.
    """
    resolve = launch_headless()
    if is_project_busy(resolve) and not force_even_if_busy:
        raise BusyError("Resolve è aperto con un altro progetto attivo")

    project = get_or_create_proxy_project(resolve)
    media_pool = project.GetMediaPool()

    root_folder = media_pool.GetRootFolder()
    media_pool.SetCurrentFolder(root_folder)

    existing = {c.GetClipProperty("File Path"): c for c in (root_folder.GetClipList() or [])}
    clip = existing.get(input_path)
    if clip is None:
        imported = media_pool.ImportMedia([input_path])
        if not imported:
            raise RuntimeError(f"Resolve non riesce a importare/decodificare: {input_path}")
        clip = imported[0]

    timeline_name = f"_bmpg_{os.path.basename(output_basename)}_{int(time.time())}"
    timeline = media_pool.CreateTimelineFromClips(timeline_name, [clip])
    if timeline is None:
        raise RuntimeError(f"Impossibile creare timeline temporanea per {input_path}")
    project.SetCurrentTimeline(timeline)

    preset = CODEC_PRESETS[codec_key]
    height = RESOLUTION_PRESETS.get(resolution_key)

    os.makedirs(output_dir, exist_ok=True)
    render_settings = {
        "SelectAllFrames": True,
        "TargetDir": output_dir,
        "CustomName": output_basename,
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": timeline.GetSetting("timelineResolutionWidth"),
        "FormatHeight": timeline.GetSetting("timelineResolutionHeight"),
    }
    if height:
        src_w = int(timeline.GetSetting("timelineResolutionWidth") or 1920)
        src_h = int(timeline.GetSetting("timelineResolutionHeight") or 1080)
        if src_h > 0:
            render_settings["FormatWidth"] = int(round(src_w * (height / src_h) / 2) * 2)
            render_settings["FormatHeight"] = height

    project.SetRenderSettings(render_settings)
    ok = project.SetCurrentRenderFormatAndCodec(preset["format"], preset["codec"])
    if not ok:
        # fall back: some Resolve versions want different codec token casing
        ok = project.SetCurrentRenderFormatAndCodec(preset["format"], preset["codec"].replace("_", " "))

    job_id = project.AddRenderJob()
    if not job_id:
        _cleanup_timeline(media_pool, timeline)
        raise RuntimeError(f"Resolve ha rifiutato il render job per {input_path}")

    project.StartRendering([job_id], isInteractiveMode=False)
    try:
        while project.IsRenderingInProgress():
            status = project.GetRenderJobStatus(job_id)
            pct = status.get("CompletionPercentage", 0) if status else 0
            if progress_cb:
                progress_cb(pct)
            time.sleep(1)
    finally:
        status = project.GetRenderJobStatus(job_id)
        project.DeleteRenderJob(job_id)
        _cleanup_timeline(media_pool, timeline)

    if not status or status.get("JobStatus") != "Complete":
        raise RuntimeError(f"Render fallito per {input_path}: {status}")

    matches = glob.glob(os.path.join(output_dir, output_basename + ".*"))
    return matches[0] if matches else None


def _cleanup_timeline(media_pool, timeline):
    try:
        project = timeline.GetName()  # noqa: just touch to ensure valid
    except Exception:
        pass
    try:
        media_pool.DeleteTimelines([timeline])
    except Exception:
        pass


class BusyError(RuntimeError):
    pass
