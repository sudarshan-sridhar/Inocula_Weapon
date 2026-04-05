"""
win_bt.py - Inocula Sentinel adapter for Windows BT + idle state.

Thin wrapper around doppelganger/system_utils.py (the source of truth).
Do not copy upstream code here - import it. memory.md rule #1 forbids
editing doppelganger/; importing is fine.

Upstream data shapes (from C:/Users/sudar/inocula/doppelganger/system_utils.py):
  get_paired_devices_dict() -> list[{
      "name": str,
      "address": str,
      "active": bool,        # True when ConnectionStatus == Connected
      "addr_type": str,      # "ble" | "classic"
  }]
  The upstream function is already pre-filtered to currently connected
  devices, so every row has active=True.

This adapter normalizes upstream rows to the Inocula protocol shape used
by sentinel/main.jac walkers (protocol.md §2 `connected_bt_devices`):
  {name, mac, addr_type, device_type, last_seen_utc}
"""
from __future__ import annotations

import datetime
import os
import sys
from typing import Any

_DEFAULT_UPSTREAM = r"C:\Users\sudar\inocula\doppelganger"
_UPSTREAM = os.environ.get("INOCULA_DOPPEL_DIR", _DEFAULT_UPSTREAM)

if _UPSTREAM not in sys.path:
    sys.path.insert(0, _UPSTREAM)

try:
    import system_utils as _su  # type: ignore[import-not-found]
    _IMPORT_ERROR = ""
except Exception as e:  # pragma: no cover - only hits on broken install
    _su = None  # type: ignore[assignment]
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def get_os_type() -> str:
    if "win32" in sys.platform:
        return "windows"
    if "darwin" in sys.platform:
        return "macos"
    return "linux"


def get_idle_seconds() -> float:
    if _su is None:
        return 0.0
    try:
        return float(_su.get_idle_seconds())
    except Exception:
        return 0.0


def _infer_device_type(name: str) -> str:
    n = (name or "").lower()
    if "mouse" in n or "trackpad" in n or "km0" in n:
        return "MOUSE"
    if "keyboard" in n or "kbd" in n:
        return "KEYBOARD"
    if any(k in n for k in ("buds", "airpods", "headset", "headphone", "audio")):
        return "HEADSET"
    if "phone" in n or "iphone" in n:
        return "PHONE"
    return "UNKNOWN"


def get_connected_bt_devices() -> list[dict[str, Any]]:
    """Return the currently connected BT devices in Inocula protocol shape."""
    if _su is None:
        return []
    try:
        raw = _su.get_paired_devices_dict() or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    now = _now_iso()
    seen_macs: set[str] = set()
    for d in raw:
        # Upstream filters to active/connected already, but guard anyway.
        if not d.get("active", True):
            continue
        mac = (d.get("address") or d.get("mac") or "").upper()
        if not mac or mac in seen_macs:
            continue
        seen_macs.add(mac)
        name = d.get("name") or "unknown_device"
        out.append({
            "name": name,
            "mac": mac,
            "addr_type": d.get("addr_type") or "unknown",
            "device_type": _infer_device_type(name),
            "last_seen_utc": now,
        })
    return out


def adapter_healthcheck() -> dict[str, Any]:
    return {
        "upstream_dir": _UPSTREAM,
        "import_ok": _su is not None,
        "import_error": _IMPORT_ERROR,
        "functions_present": {
            "get_idle_seconds": _su is not None and hasattr(_su, "get_idle_seconds"),
            "get_paired_devices_dict": _su is not None and hasattr(_su, "get_paired_devices_dict"),
        },
        "os_type": get_os_type(),
    }


__all__ = [
    "get_os_type",
    "get_idle_seconds",
    "get_connected_bt_devices",
    "adapter_healthcheck",
]
