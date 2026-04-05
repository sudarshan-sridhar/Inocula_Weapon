"""Phase 4 unit tests for the C2 track adapter (``c2/adapters/track_ops.py``).

Run from the repo root with the shared venv's python::

    C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/python.exe \
        -m unittest tests/test_c2_tracks.py -v

These tests exercise the pure-Python adapter layer directly. No real
network, no real subprocess: ``urllib.request.urlopen`` is mocked and
every ``fire_noisy`` call runs in ``dry_run=True`` mode so the ssh
client is never invoked. Env vars are isolated per-test via
``unittest.mock.patch.dict`` so no state leaks across cases.
"""
from __future__ import annotations

import importlib.util
import io
import os
import socket
import sys
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock

# Load track_ops directly from file to avoid a package-name collision with
# sentinel/adapters/ when both test modules run in the same unittest session
# (``from adapters import X`` would resolve to whichever package got imported
# first). This isolation keeps the Phase 4 test suite independent of Phase 3's.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRACK_OPS_PATH = _REPO_ROOT / "c2" / "adapters" / "track_ops.py"
_spec = importlib.util.spec_from_file_location("inocula_c2_track_ops", _TRACK_OPS_PATH)
track_ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(track_ops)


# ─── helpers ──────────────────────────────────────────────────────────

class _FakeResponse:
    """Minimal context-manager stand-in for urllib.request.urlopen."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


# ─── validation helpers ───────────────────────────────────────────────

class TrackOpsValidationTests(unittest.TestCase):
    def test_valid_mac_accepts_canonical(self) -> None:
        self.assertTrue(track_ops._valid_mac("AA:BB:CC:DD:EE:FF"))

    def test_valid_mac_rejects_no_colons(self) -> None:
        self.assertFalse(track_ops._valid_mac("AABBCCDDEEFF"))

    def test_valid_mac_rejects_empty(self) -> None:
        self.assertFalse(track_ops._valid_mac(""))

    def test_valid_ssh_host_accepts_user_at_ip(self) -> None:
        self.assertTrue(track_ops._valid_ssh_host("inocula@192.168.1.50"))

    def test_valid_ssh_host_accepts_user_at_hostname(self) -> None:
        self.assertTrue(track_ops._valid_ssh_host("user@pi.local"))

    def test_valid_ssh_host_rejects_missing_user(self) -> None:
        self.assertFalse(track_ops._valid_ssh_host("pi.local"))

    def test_valid_ssh_host_rejects_injection(self) -> None:
        self.assertFalse(track_ops._valid_ssh_host("user@host;rm -rf /"))

    def test_now_iso_is_utc_z_suffixed(self) -> None:
        ts = track_ops._now_iso()
        self.assertTrue(ts.endswith("Z"), f"expected Z suffix, got {ts!r}")
        # Must be parseable after stripping the Z.
        parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        self.assertIsNotNone(parsed)


# ─── fire_stealth: dry-run paths ──────────────────────────────────────

class FireStealthDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        # Snapshot env so nothing leaks across tests.
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def test_dryrun_no_network_call(self) -> None:
        with mock.patch("urllib.request.urlopen") as m_open:
            res = track_ops.fire_stealth(
                sentinel_url="http://192.168.137.42:8787",
                token="tok",
                operation_id="op_test",
                dry_run=True,
            )
        self.assertTrue(res["ok"])
        self.assertTrue(res["dry_run"])
        self.assertIn("would_post", res["response"])
        m_open.assert_not_called()

    def test_dryrun_uses_given_sentinel_url(self) -> None:
        res = track_ops.fire_stealth(
            sentinel_url="http://1.2.3.4:8787/",
            dry_run=True,
        )
        # rstrip('/') is applied
        self.assertEqual(res["sentinel_url"], "http://1.2.3.4:8787")
        self.assertEqual(res["track"], "stealth")

    def test_dryrun_missing_sentinel_url_env_and_arg(self) -> None:
        # env already cleared in setUp
        res = track_ops.fire_stealth(dry_run=True)
        self.assertFalse(res["ok"])
        self.assertIn("unset", res["error"])

    def test_dryrun_invalid_url_scheme(self) -> None:
        res = track_ops.fire_stealth(sentinel_url="ftp://foo", dry_run=True)
        self.assertFalse(res["ok"])
        self.assertIn("invalid", res["error"])

    def test_dryrun_default_operation_id_populated(self) -> None:
        res = track_ops.fire_stealth(
            sentinel_url="http://1.2.3.4:8787",
            dry_run=True,
        )
        self.assertTrue(res["operation_id"].startswith("op_"))

    def test_dryrun_force_flag_propagates(self) -> None:
        res = track_ops.fire_stealth(
            sentinel_url="http://1.2.3.4:8787",
            force=True,
            dry_run=True,
        )
        self.assertIs(res["response"]["would_post"]["force"], True)


# ─── fire_stealth: HTTP paths (mocked urlopen) ────────────────────────

class FireStealthHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def test_live_post_200_success(self) -> None:
        body = (
            b'{"ok":true,"data":{"reports":[{"fired":false,"logged":true}]}}'
        )
        fake = _FakeResponse(body, status=200)
        with mock.patch("urllib.request.urlopen", return_value=fake) as m_open:
            res = track_ops.fire_stealth(
                sentinel_url="http://1.2.3.4:8787",
                token="tok",
                operation_id="op_live",
            )
        m_open.assert_called_once()
        self.assertTrue(res["ok"])
        self.assertEqual(res["http_status"], 200)
        self.assertFalse(res["fired"])

    def test_live_post_401_auth_failure(self) -> None:
        err = urllib.error.HTTPError(
            url="http://1.2.3.4:8787/walker/trigger_payload",
            code=401,
            msg="unauth",
            hdrs={},
            fp=io.BytesIO(b"{}"),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            res = track_ops.fire_stealth(
                sentinel_url="http://1.2.3.4:8787",
                token="bad",
            )
        self.assertFalse(res["ok"])
        self.assertEqual(res["http_status"], 401)
        self.assertTrue(res["error"].startswith("http_error"))

    def test_live_post_url_error(self) -> None:
        err = urllib.error.URLError("unreachable")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            res = track_ops.fire_stealth(
                sentinel_url="http://1.2.3.4:8787",
                token="tok",
            )
        self.assertFalse(res["ok"])
        self.assertTrue(res["error"].startswith("url_error"))

    def test_live_post_timeout(self) -> None:
        with mock.patch(
            "urllib.request.urlopen", side_effect=socket.timeout()
        ):
            res = track_ops.fire_stealth(
                sentinel_url="http://1.2.3.4:8787",
                token="tok",
            )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "timeout")


# ─── fire_noisy: dry-run paths ────────────────────────────────────────

class FireNoisyDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def test_dryrun_valid_inputs(self) -> None:
        res = track_ops.fire_noisy(
            target_mac="AA:BB:CC:DD:EE:FF",
            pi_ssh_host="inocula@192.168.1.50",
            dry_run=True,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["stage"], "dry_run")
        self.assertIsInstance(res["planned_command"], list)
        self.assertEqual(res["planned_command"][0], "ssh")
        self.assertEqual(res["track"], "noisy")

    def test_dryrun_rejects_bad_mac(self) -> None:
        res = track_ops.fire_noisy(
            target_mac="NOT:A:MAC",
            pi_ssh_host="inocula@192.168.1.50",
            dry_run=True,
        )
        self.assertFalse(res["ok"])
        self.assertIn("invalid mac", res["error"])

    def test_dryrun_rejects_missing_ssh_host(self) -> None:
        # env is already cleared in setUp, so INOCULA_PI_SSH_HOST is unset.
        res = track_ops.fire_noisy(
            target_mac="AA:BB:CC:DD:EE:FF",
            pi_ssh_host="",
            dry_run=True,
        )
        self.assertFalse(res["ok"])
        self.assertIn("INOCULA_PI_SSH_HOST unset", res["error"])

    def test_dryrun_chains_stealth_closure(self) -> None:
        res = track_ops.fire_noisy(
            target_mac="AA:BB:CC:DD:EE:FF",
            pi_ssh_host="inocula@192.168.1.50",
            dry_run=True,
            then_stealth=lambda: {"ok": True, "chained": "yes"},
        )
        self.assertEqual(res["stealth_chain"], {"ok": True, "chained": "yes"})

    def test_dryrun_chains_stealth_exception_safe(self) -> None:
        def _boom() -> dict:
            raise RuntimeError("boom")

        res = track_ops.fire_noisy(
            target_mac="AA:BB:CC:DD:EE:FF",
            pi_ssh_host="inocula@192.168.1.50",
            dry_run=True,
            then_stealth=_boom,
        )
        self.assertIsNotNone(res["stealth_chain"])
        self.assertFalse(res["stealth_chain"]["ok"])
        self.assertIn("boom", res["stealth_chain"]["error"])

    def test_dryrun_planned_cmd_contains_sudo_by_default(self) -> None:
        res = track_ops.fire_noisy(
            target_mac="AA:BB:CC:DD:EE:FF",
            pi_ssh_host="inocula@192.168.1.50",
            dry_run=True,
        )
        joined = " ".join(res["planned_command"])
        self.assertIn("sudo", joined)

    def test_dryrun_no_sudo_when_disabled(self) -> None:
        res = track_ops.fire_noisy(
            target_mac="AA:BB:CC:DD:EE:FF",
            pi_ssh_host="inocula@192.168.1.50",
            use_sudo=False,
            dry_run=True,
        )
        joined = " ".join(res["planned_command"])
        self.assertNotIn("sudo", joined)


# ─── plan_operation ───────────────────────────────────────────────────

class PlanOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        # plan_operation's stealth step needs INOCULA_SENTINEL_URL to pass
        # validation; noisy step needs INOCULA_PI_SSH_HOST. Provide both.
        self._env_patcher = mock.patch.dict(
            os.environ,
            {
                "INOCULA_SENTINEL_URL": "http://1.2.3.4:8787",
                "INOCULA_PI_SSH_HOST": "inocula@192.168.1.50",
            },
            clear=True,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def test_plan_stealth_single_step(self) -> None:
        plan = track_ops.plan_operation("stealth")
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["kind"], "stealth")

    def test_plan_both_has_two_steps(self) -> None:
        plan = track_ops.plan_operation("both", target_mac="AA:BB:CC:DD:EE:FF")
        self.assertEqual(len(plan["steps"]), 2)
        kinds = {s["kind"] for s in plan["steps"]}
        self.assertEqual(kinds, {"stealth", "noisy"})

    def test_plan_noisy_placeholder_mac_when_blank(self) -> None:
        plan = track_ops.plan_operation("noisy", target_mac="")
        self.assertEqual(len(plan["steps"]), 1)
        noisy = plan["steps"][0]
        self.assertEqual(noisy["kind"], "noisy")
        self.assertEqual(noisy["result"]["target_mac"], "AA:BB:CC:DD:EE:FF")


# ─── adapter_healthcheck ──────────────────────────────────────────────

class AdapterHealthcheckTests(unittest.TestCase):
    def test_healthcheck_keys_present(self) -> None:
        # Don't clear env — just make sure all 4 keys are returned regardless.
        with mock.patch("subprocess.run") as m_run:
            m_run.return_value = mock.Mock(returncode=0)
            hc = track_ops.adapter_healthcheck()
        self.assertEqual(
            set(hc.keys()),
            {"ssh_ok", "has_sentinel_url", "has_token", "has_pi_ssh_host"},
        )

    def test_healthcheck_has_sentinel_url_reflects_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"INOCULA_SENTINEL_URL": "http://1.2.3.4:8787"},
            clear=True,
        ):
            with mock.patch("subprocess.run") as m_run:
                m_run.return_value = mock.Mock(returncode=0)
                hc = track_ops.adapter_healthcheck()
            self.assertTrue(hc["has_sentinel_url"])

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("subprocess.run") as m_run:
                m_run.return_value = mock.Mock(returncode=0)
                hc = track_ops.adapter_healthcheck()
            self.assertFalse(hc["has_sentinel_url"])

    def test_healthcheck_ssh_ok_is_bool(self) -> None:
        with mock.patch("subprocess.run") as m_run:
            m_run.return_value = mock.Mock(returncode=0)
            hc = track_ops.adapter_healthcheck()
        self.assertIsInstance(hc["ssh_ok"], bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
