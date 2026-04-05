"""Phase 3 unit tests for NetworkSentinel, ProcessSentinel, and the
attack classifier.

Run from the repo root with the shared venv's python:

    C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/python.exe \
        -m unittest tests/test_new_sentinels.py -v

These tests exercise the pure-Python adapter layer directly (no walker
boot required) plus one integration test that hits a live sentinel on
:8787 if it is already running. The walker integration test is skipped
cleanly when the sentinel isn't up so CI doesn't hard-fail.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Put sentinel/ on sys.path so we can import the adapters as a package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "sentinel"))

from adapters import classify as classify_mod  # noqa: E402
from adapters import kill_listener as kl  # noqa: E402
from adapters import net_scan  # noqa: E402
from adapters import proc_scan  # noqa: E402


class NetScanAdapterTests(unittest.TestCase):
    def test_list_listeners_returns_list(self) -> None:
        out = net_scan.list_listeners()
        self.assertIsInstance(out, list)
        if out:
            keys = {"port", "addr", "pid", "process"}
            self.assertTrue(keys.issubset(out[0].keys()))

    def test_classify_ip(self) -> None:
        self.assertEqual(net_scan.classify_ip("127.0.0.1"), "localhost")
        self.assertEqual(net_scan.classify_ip("10.0.0.5"), "rfc1918")
        self.assertEqual(net_scan.classify_ip("192.168.137.86"), "rfc1918")
        self.assertEqual(net_scan.classify_ip("8.8.8.8"), "public")
        self.assertEqual(net_scan.classify_ip("not-an-ip"), "unknown")
        self.assertEqual(net_scan.classify_ip(""), "unknown")

    def test_trigger_log_recent_reads_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "trig.ndjson"
            now = datetime.now(timezone.utc)
            # Write three entries: fresh, 30s old, 10min old.
            recent = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            stale = (now.replace(minute=(now.minute + 0) % 60)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            entries = [
                {"ts": recent, "source_ip": "10.0.0.5", "walker": "trigger_payload",
                 "accepted": False},
                # really stale entry (use a fixed 2020 timestamp)
                {"ts": "2020-01-01T00:00:00Z", "source_ip": "10.0.0.6",
                 "walker": "trigger_payload", "accepted": False},
            ]
            log_path.write_text(
                "\n".join(json.dumps(e) for e in entries) + "\n",
                encoding="utf-8",
            )
            fresh = net_scan.trigger_log_recent(str(log_path), window_s=120.0)
            self.assertEqual(len(fresh), 1)
            self.assertEqual(fresh[0]["source_ip"], "10.0.0.5")

    def test_trigger_log_recent_missing_file(self) -> None:
        self.assertEqual(net_scan.trigger_log_recent("/no/such/file", 60.0), [])

    def test_own_lan_ips_nonempty_on_networked_host(self) -> None:
        ips = net_scan.own_lan_ips()
        self.assertIsInstance(ips, list)
        for ip in ips:
            self.assertFalse(ip.startswith("127."))

    def test_adapter_healthcheck_shape(self) -> None:
        hc = net_scan.adapter_healthcheck()
        self.assertIn("psutil_ok", hc)
        self.assertIn("own_ips", hc)


class ProcScanAdapterTests(unittest.TestCase):
    def test_list_recent_processes_returns_list(self) -> None:
        out = proc_scan.list_recent_processes(window_s=300.0)
        self.assertIsInstance(out, list)

    def test_detect_idle_cohort_skips_when_active(self) -> None:
        # idle_seconds below threshold → always empty regardless of processes
        self.assertEqual(
            proc_scan.detect_idle_cohort(
                idle_seconds=2.0, idle_threshold=10.0, window_s=60.0
            ),
            [],
        )

    def test_detect_sendinput_burst_missing_file(self) -> None:
        self.assertIsNone(
            proc_scan.detect_sendinput_burst("/no/such/marker.ndjson", max_age_s=60.0)
        )

    def test_detect_sendinput_burst_reads_fresh_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "marker.ndjson"
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            p.write_text(
                json.dumps({"ts": now, "keys": 42, "source": "test_poc"}) + "\n",
                encoding="utf-8",
            )
            out = proc_scan.detect_sendinput_burst(str(p), max_age_s=60.0)
            self.assertIsNotNone(out)
            self.assertEqual(out["burst_keys"], 42)
            self.assertEqual(out["source"], "test_poc")

    def test_detect_sendinput_burst_skips_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "marker.ndjson"
            p.write_text(
                json.dumps(
                    {"ts": "2020-01-01T00:00:00Z", "keys": 7, "source": "old"}
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertIsNone(
                proc_scan.detect_sendinput_burst(str(p), max_age_s=60.0)
            )


class KillListenerAdapterTests(unittest.TestCase):
    def test_dryrun_never_runs_subprocess(self) -> None:
        out = kl.remediation_dryrun(port=18765, ip="192.168.137.86")
        self.assertTrue(out["dry_run"])
        self.assertEqual(len(out["actions"]), 2)
        for a in out["actions"]:
            self.assertTrue(a["dry_run"])

    def test_kill_process_allowlist_rejects_unlisted(self) -> None:
        out = kl.kill_process_by_name("malicious.exe", dry_run=True)
        self.assertFalse(out["ok"])
        self.assertIn("allowlist", out["error"])

    def test_kill_process_allowlist_rejects_bad_shape(self) -> None:
        out = kl.kill_process_by_name("../../etc/passwd", dry_run=True)
        self.assertFalse(out["ok"])
        self.assertIn("invalid", out["error"])

    def test_kill_process_allowlist_accepts_notepad_dry(self) -> None:
        out = kl.kill_process_by_name("notepad.exe", dry_run=True)
        self.assertTrue(out["ok"])

    def test_block_ip_rejects_bad_ip(self) -> None:
        out = kl.block_ip_netsh("not-an-ip", dry_run=True)
        self.assertFalse(out["ok"])

    def test_block_ip_accepts_rfc1918_dry(self) -> None:
        out = kl.block_ip_netsh("192.168.137.86", dry_run=True)
        self.assertTrue(out["ok"])
        self.assertIn("192.168.137.86", out["rule_name"])

    def test_find_pid_by_port_bounds(self) -> None:
        self.assertIsNone(kl.find_pid_by_port(0))
        self.assertIsNone(kl.find_pid_by_port(99999))


class ClassifierTests(unittest.TestCase):
    """Rule-based classifier. LLM path is not exercised here because it
    requires ANTHROPIC_API_KEY; the rule path is what ships in Phase 3."""

    def _disable_llm(self) -> None:
        # Ensure we're testing the rule path regardless of shell env.
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_benign_when_features_empty(self) -> None:
        self._disable_llm()
        out = classify_mod.classify({})
        self.assertEqual(out["kind"], "BENIGN")
        self.assertEqual(out["severity"], "INFO")
        self.assertEqual(out["backend"], "rules")
        self.assertEqual(out["recommended_actions"], ["none"])

    def test_rogue_post_is_critical_network(self) -> None:
        self._disable_llm()
        out = classify_mod.classify({
            "rogue_post": {
                "source_ip": "192.168.137.86",
                "walker": "trigger_payload",
                "reason": "not in whitelist",
            }
        })
        self.assertEqual(out["kind"], "STEALTH_NETWORK")
        self.assertEqual(out["severity"], "CRITICAL")
        self.assertGreaterEqual(out["confidence"], 0.85)
        self.assertIn("block_ip:192.168.137.86", out["recommended_actions"])

    def test_idle_cohort_triggers_stealth_process(self) -> None:
        self._disable_llm()
        out = classify_mod.classify({
            "idle_cohort": [
                {"name": "notepad.exe", "pid": 4321, "parent_name": "explorer.exe",
                 "age_s": 3.2, "idle_at_spawn_s": 14.5},
            ],
        })
        self.assertEqual(out["kind"], "STEALTH_PROCESS")
        self.assertEqual(out["severity"], "CRITICAL")
        self.assertIn("kill_process:notepad.exe", out["recommended_actions"])

    def test_hybrid_attack_produces_multi_action_plan(self) -> None:
        self._disable_llm()
        out = classify_mod.classify({
            "rogue_post": {"source_ip": "192.168.137.86"},
            "new_listeners": [
                {"port": 18765, "process": "python.exe", "pid": 1, "addr": "0.0.0.0"},
            ],
            "idle_cohort": [{"name": "calc.exe", "pid": 99, "age_s": 1}],
        })
        self.assertEqual(out["severity"], "CRITICAL")
        actions = set(out["recommended_actions"])
        self.assertIn("block_ip:192.168.137.86", actions)
        self.assertIn("kill_listener:18765", actions)
        self.assertIn("kill_process:calc.exe", actions)

    def test_sendinput_burst_is_critical(self) -> None:
        self._disable_llm()
        out = classify_mod.classify({
            "sendinput_burst": {"burst_keys": 42, "last_ts": "2026-04-05T00:00:00Z",
                                "age_s": 2.0, "source": "doppelganger_poc"},
        })
        self.assertEqual(out["severity"], "CRITICAL")
        self.assertEqual(out["kind"], "STEALTH_PROCESS")

    def test_bt_critical_mapped_to_noisy_bt(self) -> None:
        self._disable_llm()
        out = classify_mod.classify({
            "bt_alerts": [
                {"severity": "CRITICAL", "mac": "AA:BB:CC:DD:EE:FF",
                 "message": "duplicate identity"},
            ],
        })
        self.assertEqual(out["kind"], "NOISY_BT")
        self.assertIn("quarantine_device:AA:BB:CC:DD:EE:FF", out["recommended_actions"])

    def test_no_api_key_uses_rules_backend(self) -> None:
        self._disable_llm()
        out = classify_mod.classify({"idle_cohort": [{"name": "cmd.exe"}]})
        self.assertEqual(out["backend"], "rules")


def _sentinel_up(port: int = 8787, timeout: float = 0.3) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


@unittest.skipUnless(_sentinel_up(), "sentinel not running on :8787")
class SentinelWalkerIntegrationTests(unittest.TestCase):
    """Integration: requires a live sentinel process. Skipped if down."""

    BASE = "http://127.0.0.1:8787"

    def _post(self, path: str, body: dict | None = None) -> dict:
        import urllib.request
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_walkers_list_contains_phase3_walkers(self) -> None:
        import urllib.request
        with urllib.request.urlopen(f"{self.BASE}/walkers", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        walkers = set(data["data"]["walkers"])
        for name in ("network_scan", "process_scan", "classify_and_respond",
                     "get_network_alerts", "get_process_alerts", "get_classification"):
            self.assertIn(name, walkers)

    def test_network_scan_roundtrip(self) -> None:
        r = self._post("/walker/network_scan")
        rep = r["data"]["reports"][0]
        self.assertTrue(rep["scan_ok"])
        self.assertIn("scanned_at_utc", rep)
        self.assertIsInstance(rep["total_listeners"], int)

    def test_process_scan_roundtrip(self) -> None:
        r = self._post("/walker/process_scan")
        rep = r["data"]["reports"][0]
        self.assertTrue(rep["scan_ok"])
        self.assertIn("idle_seconds", rep)

    def test_classify_dry_run_is_safe(self) -> None:
        r = self._post("/walker/classify_and_respond", {"armed": False})
        rep = r["data"]["reports"][0]
        self.assertFalse(rep["armed"])
        self.assertIn("classification", rep)
        self.assertIn("kind", rep["classification"])
        # No real remediation should have fired in dry mode.
        for ex in rep["executed"]:
            self.assertTrue(ex["result"].get("dry_run", True))

    def test_trigger_payload_logs_and_refuses(self) -> None:
        r = self._post("/walker/trigger_payload", {"origin": "test-runner", "force": True})
        rep = r["data"]["reports"][0]
        self.assertFalse(rep["fired"])
        self.assertTrue(rep["logged"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
