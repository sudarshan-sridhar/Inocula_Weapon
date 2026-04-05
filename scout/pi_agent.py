#!/usr/bin/env python3
"""Inocula Scout - Pi-side BLE/classic scanner + C2 poster.

Runs on the Raspberry Pi. Passively scans nearby BLE peripherals (and, best
effort, paired classic BT devices), then POSTs the snapshot to the Inocula C2
at POST {INOCULA_C2_URL}/walker/report_scan. Honors next_poll_seconds from the
C2 response so the operator can throttle Scout without restarting it.

Contract:   ../shared/protocol.md section 1
Auth:       ../shared/auth.md (X-Inocula-Token header)
Deployment: ../scout/README.md (systemd --user unit)

Not a server. Pure outbound client. One process, one loop, cleanly exits on
SIGINT / SIGTERM.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

try:
    from bleak import BleakScanner
except ImportError:  # pragma: no cover - bleak may be absent on dev host
    BleakScanner = None  # type: ignore[assignment]

try:
    import requests
except ImportError:  # pragma: no cover - fall back to urllib
    requests = None  # type: ignore[assignment]

import urllib.error
import urllib.request


LOG_PREFIX = "[INOCULA SCOUT]"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s %(levelname)s {LOG_PREFIX} %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("inocula.scout")


# --- Config ---------------------------------------------------------


def load_config() -> dict[str, Any]:
    """Pull Scout config from env (see shared/auth.md section 3)."""

    def _f(key: str, default: float) -> float:
        raw = os.environ.get(key, "")
        if raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            log.warning("bad %s=%r, using default %s", key, raw, default)
            return default

    return {
        "token": os.environ.get("INOCULA_TOKEN", ""),
        "c2_url": os.environ.get("INOCULA_C2_URL", ""),
        "scan_interval": _f("INOCULA_SCAN_INTERVAL", 10.0),
        "rssi_min": _f("INOCULA_RSSI_MIN", -75.0),
        "scan_duration": _f("INOCULA_SCAN_DURATION", 8.0),
        "pi_id": os.environ.get("INOCULA_PI_ID", socket.gethostname()),
    }


# --- Utilities ------------------------------------------------------


def detect_local_ip() -> str:
    """Return the primary LAN IP via UDP-dummy-connect; fallback 127.0.0.1."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and ip != "0.0.0.0":
                return ip
        finally:
            s.close()
    except Exception:
        pass
    return "127.0.0.1"


def utc_now_iso() -> str:
    """UTC time as ISO8601 with 3-digit ms and trailing Z (protocol.md §1)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def redact_token(tok: str) -> str:
    """Show first 6 chars + '...' — never log full token (auth.md §6)."""
    if not tok:
        return "<empty>"
    return (tok[:6] + "...") if len(tok) > 6 else "***"


# --- BLE scan -------------------------------------------------------


async def scan_ble(duration_s: float, rssi_min_dbm: float) -> list[dict]:
    """Run a passive BLE scan for duration_s; return protocol §1 device dicts.

    Uses BleakScanner's detection_callback so we capture RSSI on every
    advertisement, not just the post-scan snapshot. Aggregates observed_count
    across the whole scan window and filters out devices below rssi_min_dbm.
    """
    if BleakScanner is None:
        raise RuntimeError("bleak is not installed; cannot run BLE scan")

    seen: dict[str, dict[str, Any]] = {}

    def on_detected(device: Any, adv: Any) -> None:
        addr = getattr(device, "address", None)
        if not addr:
            return
        mac = addr.upper()
        rssi = getattr(adv, "rssi", None)
        if rssi is None:
            rssi = getattr(device, "rssi", None)
        name = (
            getattr(adv, "local_name", None)
            or getattr(device, "name", None)
            or ""
        )
        raw_flags = getattr(adv, "flags", None)
        adv_flags = raw_flags if isinstance(raw_flags, int) else None
        tx_power = getattr(adv, "tx_power", None)

        entry = seen.get(mac)
        if entry is None:
            seen[mac] = {
                "mac": mac,
                "name": name,
                "rssi": rssi,
                "addr_type": "ble",
                "adv_flags": adv_flags,
                "tx_power": tx_power,
                "observed_count": 1,
                "last_seen_utc": utc_now_iso(),
            }
            return
        entry["observed_count"] = int(entry.get("observed_count", 0)) + 1
        if rssi is not None:
            entry["rssi"] = rssi
        if name and not entry.get("name"):
            entry["name"] = name
        if adv_flags is not None:
            entry["adv_flags"] = adv_flags
        if tx_power is not None:
            entry["tx_power"] = tx_power
        entry["last_seen_utc"] = utc_now_iso()

    scanner = BleakScanner(detection_callback=on_detected)
    await scanner.start()
    try:
        await asyncio.sleep(duration_s)
    finally:
        try:
            await scanner.stop()
        except Exception as e:
            log.debug("scanner.stop() raised: %s", e)

    filtered = [
        d for d in seen.values()
        if d.get("rssi") is None or float(d["rssi"]) >= float(rssi_min_dbm)
    ]
    filtered.sort(key=lambda d: (d.get("rssi") is None, -(d.get("rssi") or -999)))
    return filtered


# --- Classic BT probe -----------------------------------------------


def scan_classic() -> list[dict]:
    """Best-effort classic-BT discovery via `bluetoothctl devices`.

    Does NOT run an aggressive inquiry — reads the already-known/paired device
    list and returns it shaped per protocol §1. If bluetoothctl is missing or
    slow, returns []. Hard cap ~2s.
    """
    try:
        proc = subprocess.run(
            ["bluetoothctl", "devices"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        log.debug("classic scan skipped: %s", e)
        return []

    if proc.returncode != 0:
        log.debug("bluetoothctl exit=%s stderr=%s", proc.returncode, proc.stderr[:120])
        return []

    out: list[dict] = []
    for line in proc.stdout.splitlines():
        # format: "Device AA:BB:CC:DD:EE:FF Some Name"
        parts = line.strip().split(" ", 2)
        if len(parts) < 2 or parts[0] != "Device":
            continue
        mac = parts[1].upper()
        if len(mac) != 17:
            continue
        name = parts[2] if len(parts) >= 3 else ""
        out.append({"mac": mac, "name": name, "l2ping_ok": False})
    return out


# --- Build POST body (protocol.md §1) -------------------------------


def build_report_body(
    pi_ip: str,
    devices: list[dict],
    classic: list[dict],
    rssi_min_dbm: float,
    scan_duration_s: float,
) -> dict:
    """Assemble /walker/report_scan body exactly per protocol.md §1."""
    return {
        "pi_ip": pi_ip,
        "scan_updated_utc": utc_now_iso(),
        "rssi_min_dbm": int(rssi_min_dbm),
        "scan_duration_s": int(scan_duration_s),
        "devices": devices,
        "classic": classic,
    }


# --- POST to C2 -----------------------------------------------------


def post_scan(
    session: Any,
    c2_url: str,
    token: str,
    body: dict,
    timeout_s: float = 15.0,
) -> dict | None:
    """POST a scan report to C2. Returns parsed response dict or None on error.

    Uses requests.Session if `session` is non-None, else falls back to urllib.
    Timeout budget matches protocol.md §7 (Scout -> C2 connect 3s, read 10s).
    """
    url = f"{c2_url.rstrip('/')}/walker/report_scan"
    headers = {
        "X-Inocula-Token": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if session is not None:
        try:
            resp = session.post(url, headers=headers, json=body, timeout=(3.0, 10.0))
        except Exception as e:
            log.warning("C2 POST failed: %s", e)
            return None
        if resp.status_code != 200:
            log.error("C2 HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        try:
            return resp.json()
        except ValueError as e:
            log.error("C2 response not JSON: %s", e)
            return None

    # urllib fallback
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        log.error("C2 HTTP %s: %s", e.code, e.reason)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        log.warning("C2 POST failed: %s", e)
        return None


def extract_next_poll(parsed: dict | None, default: float) -> float:
    """Pull data.reports[0].next_poll_seconds from C2 response, else default."""
    if not parsed:
        return default
    try:
        data = parsed.get("data") or {}
        reports = data.get("reports") or []
        if not reports:
            return default
        nps = (reports[0] or {}).get("next_poll_seconds")
        return float(nps) if nps is not None else default
    except (AttributeError, TypeError, ValueError):
        return default


# --- Signals & main loop --------------------------------------------


_shutdown = False


def _install_signal_handlers() -> None:
    def _handler(signum: int, _frame: Any) -> None:
        global _shutdown
        _shutdown = True
        log.info("signal %s received, stopping", signum)

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError, AttributeError):
            pass


async def _run_once(cfg: dict[str, Any], pi_ip: str) -> dict:
    """Run one scan cycle and return the fully-built POST body."""
    try:
        devices = await scan_ble(cfg["scan_duration"], cfg["rssi_min"])
    except Exception:
        log.exception("BLE scan failed")
        devices = []
    classic = scan_classic()
    return build_report_body(
        pi_ip=pi_ip,
        devices=devices,
        classic=classic,
        rssi_min_dbm=cfg["rssi_min"],
        scan_duration_s=cfg["scan_duration"],
    )


async def main_loop(args: argparse.Namespace) -> int:
    cfg = load_config()
    # CLI overrides win over env.
    if args.c2_url:
        cfg["c2_url"] = args.c2_url
    if args.token:
        cfg["token"] = args.token
    if args.interval is not None:
        cfg["scan_interval"] = args.interval

    pi_ip = detect_local_ip()
    log.info("scout starting pi_ip=%s pi_id=%s", pi_ip, cfg["pi_id"])
    log.info(
        "config scan=%.1fs every %.1fs rssi_min=%.0f",
        cfg["scan_duration"], cfg["scan_interval"], cfg["rssi_min"],
    )
    log.info("c2_url=%s token=%s", cfg["c2_url"] or "<unset>", redact_token(cfg["token"]))

    # Dry-run: one scan, print body, exit. No network, no token required.
    if args.dry_run:
        body = await _run_once(cfg, pi_ip)
        log.info("dry-run complete: %d ble device(s), %d classic",
                 len(body["devices"]), len(body["classic"]))
        print(json.dumps(body, indent=2))
        return 0

    if not cfg["c2_url"]:
        log.error("INOCULA_C2_URL (or --c2-url) required in live mode")
        return 2
    if not cfg["token"]:
        log.error("INOCULA_TOKEN (or --token) required in live mode")
        return 2

    session = requests.Session() if requests is not None else None
    _install_signal_handlers()

    base_interval = float(cfg["scan_interval"])
    next_interval = base_interval

    while not _shutdown:
        try:
            body = await _run_once(cfg, pi_ip)
            log.info("scan: %d ble, %d classic", len(body["devices"]), len(body["classic"]))
            parsed = post_scan(session, cfg["c2_url"], cfg["token"], body)
            if parsed is None:
                next_interval = min(base_interval * 2.0, 60.0)
                log.warning("POST failed, backing off to %.1fs", next_interval)
            else:
                next_interval = extract_next_poll(parsed, base_interval)
                reports = (parsed.get("data") or {}).get("reports") or []
                if reports:
                    r0 = reports[0] or {}
                    log.info(
                        "c2 ack phase=%s recv=%s next=%.1fs",
                        r0.get("c2_phase", "?"),
                        r0.get("devices_received", "?"),
                        next_interval,
                    )
        except Exception:
            log.exception("scan cycle crashed (continuing)")
            next_interval = base_interval

        if args.once:
            break

        # Chunked sleep so SIGINT is responsive.
        slept = 0.0
        while slept < next_interval and not _shutdown:
            step = min(0.5, next_interval - slept)
            time.sleep(step)
            slept += step

    if session is not None:
        try:
            session.close()
        except Exception:
            pass
    log.info("scout stopped")
    return 0


# --- CLI ------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="pi_agent.py",
        description="Inocula Scout - passive BLE/classic scanner, posts to C2",
    )
    p.add_argument("--c2-url", default=None,
                   help="C2 base URL, e.g. http://<laptop_b>:8788 (env INOCULA_C2_URL)")
    p.add_argument("--token", default=None,
                   help="X-Inocula-Token shared secret (env INOCULA_TOKEN)")
    p.add_argument("--interval", type=float, default=None,
                   help="Seconds between scans (env INOCULA_SCAN_INTERVAL)")
    p.add_argument("--dry-run", action="store_true",
                   help="Run one scan, print JSON body, exit. No network call.")
    p.add_argument("--once", action="store_true",
                   help="Run one scan + one POST, exit.")
    return p.parse_args(argv)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_loop(parse_args())))
    except KeyboardInterrupt:
        log.info("scout stopped (KeyboardInterrupt)")
        sys.exit(0)
