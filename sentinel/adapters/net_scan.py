"""Inocula Sentinel — network-plane scanner adapter.

Surfaces the signals NetworkSentinel needs without running a full
packet capture. Everything here is pure-Python stdlib so it boots
on any Windows 10/11 box in the shared venv:

- `list_listeners()` — open TCP listener sockets owned by this machine,
  used to catch a rogue 18765/8787/<custom> listener that a stealth
  payload may have opened.
- `list_lan_peers()` — distinct remote LAN IPs currently connected to
  any local listener. Feeds the "unexpected host scanning :8787" signal.
- `trigger_log_recent(path, window_s)` — reads an append-only NDJSON
  access log left by sentinel's `/walker/trigger_payload` handler
  (sentinel writes it; this module only reads). Returns entries whose
  UTC timestamp is within `window_s` of now.
- `classify_ip(ip)` — returns one of {"localhost", "rfc1918", "public"}
  so NetworkSentinel can decide if a POST came from a LAN peer or the
  open internet.

None of these functions mutate state. All errors are swallowed and
turned into empty-result return values so a walker that calls them
cannot crash the sentinel process.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _safe_getaddr(conn: Any, attr: str) -> tuple[str, int]:
    try:
        pair = getattr(conn, attr)
        if pair is None:
            return ("", 0)
        return (str(pair.ip), int(pair.port))
    except Exception:
        return ("", 0)


def list_listeners() -> list[dict]:
    """Return TCP listeners bound on this host.

    Shape: [{"port": int, "addr": str, "pid": int, "process": str}]
    Uses psutil if available, falls back to an empty list on import
    failure so sentinel never hard-fails on a box without psutil.
    """
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    out: list[dict] = []
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status != psutil.CONN_LISTEN:
                continue
            laddr, lport = _safe_getaddr(c, "laddr")
            pid = int(c.pid) if c.pid else 0
            proc_name = ""
            if pid:
                try:
                    proc_name = psutil.Process(pid).name()
                except Exception:
                    proc_name = ""
            out.append({
                "port": lport,
                "addr": laddr,
                "pid": pid,
                "process": proc_name,
            })
    except Exception:
        return []
    return out


def list_lan_peers(self_port: int = 8787) -> list[dict]:
    """Return ESTABLISHED remote peers connected to self_port.

    Shape: [{"remote_ip": str, "remote_port": int, "pid": int}]
    """
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    out: list[dict] = []
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status != psutil.CONN_ESTABLISHED:
                continue
            laddr, lport = _safe_getaddr(c, "laddr")
            if lport != self_port:
                continue
            raddr, rport = _safe_getaddr(c, "raddr")
            if not raddr:
                continue
            out.append({
                "remote_ip": raddr,
                "remote_port": rport,
                "pid": int(c.pid) if c.pid else 0,
            })
    except Exception:
        return []
    return out


def classify_ip(ip: str) -> str:
    """Classify an IPv4/IPv6 address as localhost / rfc1918 / public."""
    if not ip:
        return "unknown"
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return "unknown"
    if addr.is_loopback:
        return "localhost"
    if addr.is_private:
        return "rfc1918"
    return "public"


def trigger_log_recent(path: str, window_s: float = 60.0) -> list[dict]:
    """Read sentinel's trigger_payload access log; return entries newer than window.

    Each line is a JSON object of shape {"ts": ISO8601, "source_ip": str,
    "walker": str, "accepted": bool, "reason": str}. Missing file or
    parse errors → empty list.
    """
    p = Path(path)
    if not p.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_s)
    out: list[dict] = []
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                ts_str = entry.get("ts", "")
                try:
                    # ISO with trailing Z
                    ts_clean = ts_str.replace("Z", "+00:00")
                    ts = datetime.fromisoformat(ts_clean)
                except Exception:
                    continue
                if ts >= cutoff:
                    out.append(entry)
    except Exception:
        return []
    return out


def own_lan_ips() -> list[str]:
    """Return this host's non-loopback IPv4 addresses.

    Used to tell "POST from self" apart from "POST from LAN peer".
    """
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


def adapter_healthcheck() -> dict:
    """Lightweight self-test for /walker/init_sentinel to log at boot."""
    try:
        import psutil  # type: ignore
        psutil_version = getattr(psutil, "__version__", "unknown")
        psutil_ok = True
    except Exception:
        psutil_version = ""
        psutil_ok = False
    return {
        "psutil_ok": psutil_ok,
        "psutil_version": psutil_version,
        "own_ips": own_lan_ips(),
    }
