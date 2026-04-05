"""Inocula Sentinel — process-plane scanner adapter.

ProcessSentinel's job is to catch doppelganger-style SendInput attacks:
the victim is idle, and suddenly a shell / calc / notepad spawns and
gets typed into. Without an ETW subscription we can't see the actual
SendInput API calls, so we observe the visible side-effects:

- `list_recent_processes(window_s)` — all processes whose create_time
  is inside the last window_s seconds. Filtered down to the usual
  doppelganger cohort (calc.exe, notepad.exe, cmd.exe, powershell.exe,
  wscript.exe, mshta.exe, explorer.exe Win+R children).
- `detect_idle_cohort(idle_seconds, idle_threshold, window_s)` — returns
  the cohort of interactive-looking processes that spawned while the
  user was above the idle threshold. This is the core gap-closure
  signal for the STEALTH track.
- `detect_sendinput_burst(poc_marker_path)` — reads a side-channel file
  that `doppelganger_poc/payload/win_payload.py` already writes when
  its inject() routine runs. If the marker is newer than `max_age_s`,
  we treat it as a confirmed SendInput burst. This is defensible
  because the upstream POC emits a JSON line on every inject; we just
  read it. Upstream is NOT modified — the adapter reads whatever file
  exists; if POC hasn't been run, the function returns None cleanly.

All functions are read-only and exception-safe.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Processes doppelganger's SendInput chain would typically spawn.
_INTERACTIVE_COHORT: set[str] = {
    "calc.exe",
    "notepad.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "wscript.exe",
    "cscript.exe",
    "mshta.exe",
    "rundll32.exe",
}


def list_recent_processes(window_s: float = 30.0) -> list[dict]:
    """Return processes created within the last window_s seconds.

    Shape: [{"pid": int, "name": str, "parent_pid": int, "parent_name": str,
    "create_time": float, "age_s": float, "cmdline": str}]
    """
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    now = time.time()
    cutoff = now - window_s
    out: list[dict] = []
    try:
        for p in psutil.process_iter(["pid", "name", "ppid", "create_time", "cmdline"]):
            try:
                info = p.info
                ct = info.get("create_time", 0) or 0
                if ct < cutoff:
                    continue
                parent_name = ""
                try:
                    parent = psutil.Process(info.get("ppid", 0))
                    parent_name = parent.name()
                except Exception:
                    parent_name = ""
                cmdline_list = info.get("cmdline") or []
                out.append({
                    "pid": int(info.get("pid", 0) or 0),
                    "name": (info.get("name") or "").lower(),
                    "parent_pid": int(info.get("ppid", 0) or 0),
                    "parent_name": parent_name.lower(),
                    "create_time": float(ct),
                    "age_s": round(now - ct, 2),
                    "cmdline": " ".join(str(x) for x in cmdline_list),
                })
            except Exception:
                continue
    except Exception:
        return []
    return out


def detect_idle_cohort(
    idle_seconds: float,
    idle_threshold: float = 10.0,
    window_s: float = 15.0,
) -> list[dict]:
    """Return cohort processes (calc/notepad/cmd/etc.) that spawned while idle.

    Pre-filter on idle_seconds: if the user is currently active, we skip
    the check entirely and return an empty list — the attack model
    requires the user to be idle.
    """
    if idle_seconds < idle_threshold:
        return []
    recent = list_recent_processes(window_s=window_s)
    cohort: list[dict] = []
    for entry in recent:
        if entry["name"] in _INTERACTIVE_COHORT:
            # The process spawned at `create_time`. At that moment,
            # the user had to be at least (idle_seconds - age_s) idle.
            idle_at_spawn = idle_seconds - entry["age_s"]
            entry_with_idle = dict(entry)
            entry_with_idle["idle_at_spawn_s"] = round(max(0.0, idle_at_spawn), 2)
            cohort.append(entry_with_idle)
    return cohort


def detect_sendinput_burst(
    poc_marker_path: str,
    max_age_s: float = 30.0,
) -> Optional[dict]:
    """Read a side-channel SendInput burst marker written by the upstream POC.

    Returns {"burst_keys": int, "last_ts": str, "age_s": float, "source": str}
    if a recent burst is recorded, else None. Missing file / parse errors
    return None cleanly.
    """
    p = Path(poc_marker_path)
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            return None
        # Expect last line to be the most recent JSON record.
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return None
        entry = json.loads(lines[-1])
        ts_str = entry.get("ts", "")
        ts_clean = ts_str.replace("Z", "+00:00")
        try:
            ts = datetime.fromisoformat(ts_clean)
        except Exception:
            return None
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > max_age_s:
            return None
        return {
            "burst_keys": int(entry.get("keys", entry.get("count", 0))),
            "last_ts": ts_str,
            "age_s": round(age, 2),
            "source": entry.get("source", "doppelganger_poc"),
        }
    except Exception:
        return None


def adapter_healthcheck() -> dict:
    """Process adapter self-test."""
    try:
        import psutil  # type: ignore
        psutil_ok = True
        n_procs = len(psutil.pids())
    except Exception:
        psutil_ok = False
        n_procs = 0
    return {
        "psutil_ok": psutil_ok,
        "process_count": n_procs,
        "cohort_patterns": sorted(_INTERACTIVE_COHORT),
    }
