"""Inocula C2 — track dispatcher adapters.

Two entry points the Jac walker `run_operation` calls into:

- `fire_stealth(sentinel_url, token, operation_id, force)` — HTTP POST
  to the Sentinel's `/walker/trigger_payload` bait endpoint. The
  Sentinel's Phase 3 NetworkSentinel is expected to fire on this,
  which is the whole point: C2 trips the defense on purpose to
  demonstrate the detection gap.

- `fire_noisy(pi_ssh_host, target_mac, ssh_identity, then_stealth_fn)`
  — SSH into the Pi scout and run `bt_clone.sh <mac>`. On success,
  Laptop A's duplicate-MAC sentinel (Phase 2) fires. If
  `then_stealth_fn` is provided it runs next so the operation still
  lands the stealth "impact" phase.

Both functions are exception-safe and return a structured dict that
the walker can log verbatim into `C2Node.event_log`. They never raise.

Configuration sources (env vars read at call time, not import time so
tests can override):
  INOCULA_SENTINEL_URL   base URL (e.g. http://192.168.137.42:8787)
  INOCULA_TOKEN          shared secret for X-Inocula-Token
  INOCULA_PI_SSH_HOST    inocula@<pi_ip>
  INOCULA_SSH_IDENTITY   optional path to SSH key (falls back to agent)
  INOCULA_SSH_TIMEOUT    SSH connect timeout seconds (default 6)
  INOCULA_C2_OP_TIMEOUT  HTTP call total timeout (default 8)
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional


# ─── shared helpers ───────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(env_name: str, default: int) -> int:
    try:
        return int(os.getenv(env_name, str(default)))
    except ValueError:
        return default


def _valid_mac(mac: str) -> bool:
    return bool(re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac or ""))


def _valid_ssh_host(host: str) -> bool:
    # `user@host` where user and host are both benign shell tokens.
    if not host or "@" not in host:
        return False
    user, sep, rest = host.partition("@")
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", user):
        return False
    # host is either an IPv4/IPv6 literal or a hostname
    if re.fullmatch(r"[A-Za-z0-9_\-\.]+", rest):
        return True
    try:
        ipaddress.ip_address(rest)
        return True
    except ValueError:
        return False


# ─── STEALTH track ────────────────────────────────────────────────────

def fire_stealth(
    sentinel_url: Optional[str] = None,
    token: Optional[str] = None,
    operation_id: str = "",
    *,
    force: bool = False,
    dry_run: bool = False,
    timeout_s: Optional[float] = None,
) -> dict:
    """POST trigger_payload to the Sentinel.

    Returns a dict with shape::
        {
          "track": "stealth",
          "ts": "<iso>",
          "ok": bool,
          "fired": bool,              # Sentinel actually ran the payload
          "operation_id": "<id>",
          "sentinel_url": "<url>",
          "http_status": int | None,
          "response": { ... },        # parsed JSON body if available
          "error": "<str>",           # populated on failure
          "dry_run": bool,
        }
    """
    url = (sentinel_url or os.getenv("INOCULA_SENTINEL_URL", "")).rstrip("/")
    tok = token or os.getenv("INOCULA_TOKEN", "")
    op_id = operation_id or f"op_{int(time.time())}"
    t_total = float(timeout_s if timeout_s is not None else _safe_int("INOCULA_C2_OP_TIMEOUT", 8))

    result: dict = {
        "track": "stealth",
        "ts": _now_iso(),
        "ok": False,
        "fired": False,
        "operation_id": op_id,
        "sentinel_url": url,
        "http_status": None,
        "response": {},
        "error": "",
        "dry_run": bool(dry_run),
    }

    if not url:
        result["error"] = "INOCULA_SENTINEL_URL unset"
        return result

    # Quick sanity: url must start with http:// or https://
    if not (url.startswith("http://") or url.startswith("https://")):
        result["error"] = f"invalid sentinel url: {url!r}"
        return result

    # Sentinel's trigger_payload walker only declares force/origin/operation_id,
    # so we keep the body strict to avoid Jac's unexpected-kwarg rejection.
    body = {
        "force": bool(force),
        "origin": "c2_stealth",
        "operation_id": op_id,
    }

    if dry_run:
        result["ok"] = True
        result["response"] = {"dry_run": True, "would_post": body}
        return result

    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if tok:
        headers["X-Inocula-Token"] = tok

    endpoint = f"{url}/walker/trigger_payload"
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=t_total) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result["http_status"] = int(resp.status)
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"raw": raw[:500]}
            result["response"] = parsed
            # Dig out Sentinel's fired flag from the walker report.
            rep_list = (
                parsed.get("data", {}).get("reports", [])
                if isinstance(parsed, dict) else []
            )
            if rep_list and isinstance(rep_list[0], dict):
                result["fired"] = bool(rep_list[0].get("fired", False))
                # Sentinel's trigger_payload is a bait endpoint in Phase 3+ — it
                # *records* the attempt rather than actually firing. That's fine:
                # for our purposes "ok" means the Sentinel logged it, which is
                # what trips the NetworkSentinel detector downstream.
                if not result["fired"] and rep_list[0].get("logged"):
                    result["fired"] = False  # explicit: refusal is expected
            result["ok"] = 200 <= result["http_status"] < 300
    except urllib.error.HTTPError as e:
        result["http_status"] = int(e.code)
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            result["response"] = json.loads(err_body)
        except Exception:
            result["response"] = {"raw": str(e)[:200]}
        result["error"] = f"http_error {e.code}"
    except urllib.error.URLError as e:
        result["error"] = f"url_error: {e.reason}"
    except socket.timeout:
        result["error"] = "timeout"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return result


# ─── NOISY track ──────────────────────────────────────────────────────

def fire_noisy(
    target_mac: str,
    pi_ssh_host: Optional[str] = None,
    *,
    ssh_identity: Optional[str] = None,
    remote_script: str = "/home/inocula/Inocula_Final/scout/bt_clone.sh",
    use_sudo: bool = True,
    dry_run: bool = False,
    then_stealth: Optional[Callable[[], dict]] = None,
    timeout_s: Optional[float] = None,
) -> dict:
    """SSH into the Pi and invoke the MAC-clone script.

    If `then_stealth` is provided, it's called after the noisy step
    regardless of outcome (so the demo still lands an "impact" event
    even if the clone failed). The stealth result is attached under
    `stealth_chain`.
    """
    host = pi_ssh_host or os.getenv("INOCULA_PI_SSH_HOST", "")
    identity = ssh_identity or os.getenv("INOCULA_SSH_IDENTITY", "")
    t_connect = _safe_int("INOCULA_SSH_TIMEOUT", 6)
    t_total = float(timeout_s if timeout_s is not None else 30)

    result: dict = {
        "track": "noisy",
        "ts": _now_iso(),
        "ok": False,
        "stage": "init",
        "target_mac": target_mac,
        "pi_ssh_host": host,
        "return_code": None,
        "stdout": "",
        "stderr": "",
        "error": "",
        "dry_run": bool(dry_run),
        "stealth_chain": None,
    }

    # Validation gates — fail fast with clear errors.
    if not _valid_mac(target_mac):
        result["error"] = f"invalid mac: {target_mac!r}"
        return result
    if not host:
        result["error"] = "INOCULA_PI_SSH_HOST unset"
        return result
    if not _valid_ssh_host(host):
        result["error"] = f"invalid ssh host: {host!r}"
        return result
    if not re.fullmatch(r"[A-Za-z0-9_\-/\.]+", remote_script):
        result["error"] = f"invalid remote script path: {remote_script!r}"
        return result

    # Build remote command. target_mac has been validated — no injection vector.
    remote_cmd_parts = []
    if use_sudo:
        remote_cmd_parts.append("sudo")
    remote_cmd_parts.extend([remote_script, target_mac])
    remote_cmd = " ".join(shlex.quote(p) for p in remote_cmd_parts)

    ssh_args = [
        "ssh",
        "-o", f"ConnectTimeout={t_connect}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "LogLevel=ERROR",
    ]
    if identity:
        ssh_args += ["-i", identity]
    ssh_args += [host, remote_cmd]

    if dry_run:
        result["ok"] = True
        result["stage"] = "dry_run"
        result["stdout"] = "(dry run — ssh command not executed)"
        result["planned_command"] = ssh_args
        if then_stealth is not None:
            try:
                result["stealth_chain"] = then_stealth()
            except Exception as e:
                result["stealth_chain"] = {"ok": False, "error": str(e)[:200]}
        return result

    try:
        result["stage"] = "ssh"
        proc = subprocess.run(
            ssh_args,
            capture_output=True,
            text=True,
            timeout=t_total,
            shell=False,
        )
        result["return_code"] = proc.returncode
        result["stdout"] = (proc.stdout or "")[:500]
        result["stderr"] = (proc.stderr or "")[:500]
        result["ok"] = proc.returncode == 0
        result["stage"] = "done" if result["ok"] else "ssh_failed"
        if not result["ok"]:
            result["error"] = (
                (proc.stderr or proc.stdout or "").strip().splitlines()[-1][:200]
                if (proc.stderr or proc.stdout) else f"exit {proc.returncode}"
            )
    except FileNotFoundError:
        result["error"] = "ssh client not found on PATH"
        result["stage"] = "no_ssh"
    except subprocess.TimeoutExpired:
        result["error"] = f"ssh timeout after {t_total}s"
        result["stage"] = "timeout"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        result["stage"] = "exception"

    # Chain stealth regardless — demo lands the payload even if clone failed.
    if then_stealth is not None:
        try:
            result["stealth_chain"] = then_stealth()
        except Exception as e:
            result["stealth_chain"] = {"ok": False, "error": str(e)[:200]}

    return result


# ─── dry-run planner ──────────────────────────────────────────────────

def plan_operation(track: str, target_mac: str = "") -> dict:
    """Return what a live call would do, without side-effects.

    Used by the C2 "DRY RUN" UI control and by tests.
    """
    plan: dict = {"ts": _now_iso(), "track": track, "steps": []}
    if track in ("stealth", "both"):
        res = fire_stealth(dry_run=True, operation_id=f"dryrun_{int(time.time())}")
        plan["steps"].append({"kind": "stealth", "result": res})
    if track in ("noisy", "both"):
        mac = target_mac or "AA:BB:CC:DD:EE:FF"
        res = fire_noisy(target_mac=mac, dry_run=True)
        plan["steps"].append({"kind": "noisy", "result": res})
    return plan


def adapter_healthcheck() -> dict:
    """Verify the tools and env vars the adapter needs at call time."""
    have_ssh = False
    try:
        proc = subprocess.run(
            ["ssh", "-V"], capture_output=True, text=True, timeout=3, shell=False
        )
        have_ssh = proc.returncode in (0, 255)  # ssh -V exits 0 or prints to stderr
    except Exception:
        have_ssh = False
    return {
        "ssh_ok": have_ssh,
        "has_sentinel_url": bool(os.getenv("INOCULA_SENTINEL_URL", "").strip()),
        "has_token": bool(os.getenv("INOCULA_TOKEN", "").strip()),
        "has_pi_ssh_host": bool(os.getenv("INOCULA_PI_SSH_HOST", "").strip()),
    }
