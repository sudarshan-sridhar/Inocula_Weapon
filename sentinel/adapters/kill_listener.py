"""Inocula Sentinel — remediation adapter.

When NetworkSentinel / ProcessSentinel classify an attack as
CRITICAL, the walker calls one of the functions below to contain it.
Everything is shelled out via subprocess with a strict allowlist so
the sentinel can never execute arbitrary strings.

Functions:
- `kill_listener_by_port(port)` — find the owning PID via psutil,
  taskkill /F /PID <pid>. Returns dict with before/after state.
- `block_ip_netsh(ip, rule_name)` — adds an inbound+outbound block
  rule via `netsh advfirewall firewall add rule`. Idempotent: if
  the rule exists it is deleted and re-added with the fresh IP.
- `kill_process_by_name(name)` — kills *all* processes matching a
  name from a hard-coded allowlist (calc/notepad/cmd/etc.).
- `remediation_dryrun(port, ip)` — returns what *would* be done
  without actually running anything. Used by tests and the UI
  "Dry Run" button.

Zero edits to upstream. No eval/exec. No shell=True on netsh so
IPs cannot escape argument parsing.
"""
from __future__ import annotations

import ipaddress
import re
import subprocess
from datetime import datetime, timezone
from typing import Optional

# Only these process names can be force-killed from walker responses.
# Anything else requires manual operator action.
_KILL_ALLOWLIST: set[str] = {
    "calc.exe",
    "notepad.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "wscript.exe",
    "cscript.exe",
    "mshta.exe",
}

# Firewall rule name prefix so we can find/delete our own rules without
# touching anything the user added manually.
_RULE_PREFIX = "Inocula-Sentinel-Block"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except Exception:
        return False


def _valid_port(port: int) -> bool:
    return isinstance(port, int) and 1 <= port <= 65535


def _valid_process_name(name: str) -> bool:
    # windows executables only, no path separators
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]+\.exe", name or ""))


def find_pid_by_port(port: int) -> Optional[int]:
    """Return PID of the process listening on `port`, or None."""
    if not _valid_port(port):
        return None
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status != psutil.CONN_LISTEN:
                continue
            if not c.laddr:
                continue
            if int(c.laddr.port) == port and c.pid:
                return int(c.pid)
    except Exception:
        return None
    return None


def kill_listener_by_port(port: int, *, dry_run: bool = False) -> dict:
    """Kill the TCP listener on `port`. Returns a result dict."""
    result = {
        "ts": _now_iso(),
        "action": "kill_listener",
        "port": port,
        "dry_run": dry_run,
        "ok": False,
        "pid": None,
        "process": None,
        "error": "",
    }
    if not _valid_port(port):
        result["error"] = f"invalid port: {port!r}"
        return result
    pid = find_pid_by_port(port)
    if pid is None:
        result["error"] = "no listener found"
        return result
    result["pid"] = pid
    try:
        import psutil  # type: ignore
        result["process"] = psutil.Process(pid).name().lower()
    except Exception:
        result["process"] = ""
    if dry_run:
        result["ok"] = True
        return result
    try:
        proc = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        result["ok"] = proc.returncode == 0
        if proc.returncode != 0:
            result["error"] = (proc.stderr or proc.stdout).strip()[:200]
    except Exception as e:
        result["error"] = str(e)[:200]
    return result


def kill_process_by_name(name: str, *, dry_run: bool = False) -> dict:
    """Kill all processes matching `name` (from allowlist only)."""
    result = {
        "ts": _now_iso(),
        "action": "kill_process",
        "name": (name or "").lower(),
        "dry_run": dry_run,
        "ok": False,
        "killed_pids": [],
        "error": "",
    }
    nm = (name or "").lower()
    if not _valid_process_name(nm):
        result["error"] = f"invalid process name: {name!r}"
        return result
    if nm not in _KILL_ALLOWLIST:
        result["error"] = f"name not in allowlist: {nm}"
        return result
    try:
        import psutil  # type: ignore
    except Exception:
        result["error"] = "psutil missing"
        return result
    pids: list[int] = []
    try:
        for p in psutil.process_iter(["pid", "name"]):
            if (p.info.get("name") or "").lower() == nm:
                pids.append(int(p.info["pid"]))
    except Exception as e:
        result["error"] = str(e)[:200]
        return result
    if dry_run:
        result["ok"] = True
        result["killed_pids"] = pids
        return result
    killed: list[int] = []
    for pid in pids:
        try:
            proc = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            if proc.returncode == 0:
                killed.append(pid)
        except Exception:
            continue
    result["ok"] = len(killed) > 0 or len(pids) == 0
    result["killed_pids"] = killed
    return result


def block_ip_netsh(
    ip: str,
    *,
    rule_name: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Add a firewall rule blocking all traffic to/from `ip`.

    Idempotent: existing rule with same name is deleted first.
    """
    result = {
        "ts": _now_iso(),
        "action": "block_ip",
        "ip": ip,
        "rule_name": "",
        "dry_run": dry_run,
        "ok": False,
        "error": "",
    }
    if not _valid_ip(ip):
        result["error"] = f"invalid ip: {ip!r}"
        return result
    name = rule_name or f"{_RULE_PREFIX}-{ip.replace(':', '_')}"
    # Whitelist the rule name charset to avoid quoting bugs.
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", name):
        result["error"] = f"invalid rule name: {name!r}"
        return result
    result["rule_name"] = name
    if dry_run:
        result["ok"] = True
        return result
    try:
        # Delete any stale rule with this name. Ignore failures.
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        # Add inbound block.
        pin = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={name}", "dir=in", "action=block", f"remoteip={ip}",
            ],
            capture_output=True, text=True, timeout=5, shell=False,
        )
        # Add outbound block.
        pout = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={name}", "dir=out", "action=block", f"remoteip={ip}",
            ],
            capture_output=True, text=True, timeout=5, shell=False,
        )
        result["ok"] = pin.returncode == 0 and pout.returncode == 0
        if not result["ok"]:
            err = (pin.stderr or pin.stdout or pout.stderr or pout.stdout).strip()
            result["error"] = err[:200]
    except Exception as e:
        result["error"] = str(e)[:200]
    return result


def remediation_dryrun(port: Optional[int] = None, ip: Optional[str] = None) -> dict:
    """Return what a full remediation would do, without side-effects."""
    actions: list[dict] = []
    if port is not None:
        actions.append(kill_listener_by_port(port, dry_run=True))
    if ip:
        actions.append(block_ip_netsh(ip, dry_run=True))
    return {
        "ts": _now_iso(),
        "dry_run": True,
        "actions": actions,
    }


def adapter_healthcheck() -> dict:
    """Verify the tools we'll shell out to are on PATH."""
    ok = {"taskkill": False, "netsh": False, "psutil": False}
    for tool in ("taskkill", "netsh"):
        try:
            proc = subprocess.run(
                [tool, "/?"], capture_output=True, text=True, timeout=3, shell=False
            )
            ok[tool] = proc.returncode in (0, 1)
        except Exception:
            ok[tool] = False
    try:
        import psutil  # type: ignore  # noqa: F401
        ok["psutil"] = True
    except Exception:
        ok["psutil"] = False
    return ok
