# Inocula — Tasks Completed Log

Append-only log of work actually done. Every entry = something that shipped
and was exercised end-to-end, not just "written". Timestamps are local
(America/Detroit). Update at the end of every phase.

---

## 2026-04-05 — Phase 0 (Ideation lock)

- Read `marcebd/inocula` / local `ghostshield/` clone end-to-end.
- Read `doppelganger/` + `doppelganger_poc/` end-to-end.
- Identified the GhostShield ↔ doppelganger defense gap:
  GhostShield's 5 detectors are Bluetooth-plane; doppelganger's attack is
  network-plane + process-plane → existing defense never fires.
- User chose **Option C (hybrid noisy+stealth)** and **Laptop B = UI +
  orchestrator**.
- Froze `ghostshield/`, `doppelganger/`, `doppelganger_poc/` as read-only.
- Wrote `memory.md` (project invariants, hard rules, decision log) and
  `tasks.md` (7-phase plan + agent roster).

## 2026-04-05 — Phase 1 (Skeleton)

### Runtime verified

- Shared Jac runtime: `C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/`
  (jaclang 0.13.5, jac_client 0.3.11, bleak, winrt).
- Boot command: `jac.exe start <app>/main.jac --port <N>`. Walker REST at
  `POST /walker/<name>`. No `jac-cloud`, no `byllm` needed.
- Ghostshield has **zero** `by llm()` calls → no Anthropic API key required
  for Phase 2 defense parity. Correction saved to `memory.md` §9.
- Windows console cp1252 cannot encode jaclang's `ℹ` log glyph → boot all
  Jac apps with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Rule recorded.

### Shared spec + tree

- `Inocula_Final/memory.md` — ground truth (sections 1–11, decision log).
- `Inocula_Final/tasks.md` — 7-phase plan.
- `Inocula_Final/shared/protocol.md` — JSON contracts for Scout↔C2↔Sentinel
  including `/walker/report_scan`, `/walker/victim_status`, `/walker/trigger_payload`,
  `/walker/sentinel_alert`. Error semantics, timeouts, version field.
- `Inocula_Final/shared/auth.md` — `X-Inocula-Token` header spec, `.env`
  layout per host, localhost exemption, IP whitelist rule for
  `trigger_payload`.
- `Inocula_Final/.env.example`, `Inocula_Final/.gitignore`.
- Folder tree: `sentinel/{graph,abilities,response,sentinels,adapters,ui}`,
  `c2/{graph,walkers,tracks,ui}`, `scout/`, `shared/`, `tests/`.

### Sentinel (Laptop A, port 8787) — exercised

- `sentinel/main.jac` (~420 lines): `LaptopNode` + `PeripheralNode` + `TrustEdge`
  graph, 9 `walker:pub` endpoints, `cl { def:pub app }` SOC-terminal dashboard
  with INOCULA SENTINEL header, DEVICE / DEFENSE PHASE / PERIPHERALS / ALERTS
  cards, 3s polling.
- `sentinel/adapters/win_bt.py`: thin wrapper over
  `doppelganger/system_utils.py` via `sys.path` insertion. Exports
  `get_os_type`, `get_idle_seconds`, `get_connected_bt_devices`,
  `adapter_healthcheck`. Maps upstream `address→mac`, infers `device_type`
  from name. Upstream **not modified** (memory.md hard rule #1).
- `sentinel/adapters/__init__.py` (empty) — makes `adapters` importable as a
  Jac/Python package.
- Walkers self-heal: each `can enter with Root entry` creates the LaptopNode
  if the per-session root has none. Required because `jac.exe start` gives
  each HTTP request a distinct session root, separate from the `with entry`
  root.
- **Smoke test** (localhost:8787, this laptop, `35.3.79.61` on mwireless):
  - `POST /walker/victim_status` → `{device_id:"laptop-a-inocula",
    os_type:"windows", idle_seconds:17.765, idle_threshold:10.0,
    connected_bt_devices:[], defense_phase:"monitoring",
    sentinel_alerts_last_30s:0, now_utc:"2026-04-05T12:02:30Z"}`. Idle is
    **live** from the adapter → `GetLastInputInfo` upstream.
  - `POST /walker/get_graph` → `{device_id, os_type, peripherals:[],
    defense_phase:"monitoring"}`.
  - `POST /walker/refresh_scan` → `{scan_ok:true, devices_scanned:0, ...}`.
  - `GET /walkers` → all 9 walkers registered.
  - Shape matches `protocol.md §2` field-for-field.
- **Known issue deferred to Phase 2**: the `cl {}` React bundle fails to
  build ("JAC_CLIENT_999: Build Failed"). Walker REST API is fully
  functional; only the browser UI is affected. Will resolve during Phase 2
  when we port ghostshield's full `cl {}` component tree.

### C2 (Laptop B, port 8788) — exercised

- `c2/main.jac` (~730 lines): `C2Node` + `PiNode` + `VictimNode` graph with
  `ScoutEdge` / `TargetEdge`. Six `walker:pub` endpoints: `get_c2_state`,
  `report_scan`, `run_operation`, `abort_operation`, `configure`,
  `sentinel_alert`. OODA phase computer, target selector (highest-RSSI HID/
  audio match above `rssi_min_trigger`), event log (cap 200). `cl { def:pub
  app }` operator console with OODA pill row, stats row, target lock card,
  track selector (STEALTH/NOISY/BOTH), RUN OPERATION + ABORT buttons,
  scouts/victims tables, scrolling event log, 2s polling.
- `c2/tracks/track_stealth.jac` — placeholder `walker fire_stealth`
  (TODO Phase 4: `POST` to Sentinel `/walker/trigger_payload`).
- `c2/tracks/track_noisy.jac` — placeholder `walker fire_noisy`
  (TODO Phase 4: SSH to Pi, run `bt_clone.sh`, then chain stealth).
- Same self-heal pattern applied to all 6 walkers (`replace_all` edit).
- **Smoke test** (localhost:8788):
  - `POST /walker/get_c2_state` (initial) → `ooda_phase:"observe"`,
    `armed:false`, `target:{}`, `scouts:[]`, `event_log:[]`.
  - `POST /walker/report_scan` with Samsers KM01-M @ RSSI -48 →
    `c2_phase:"orient"`, `target:{name:"Samsers KM01-M",
    mac:"E2:6A:42:48:E8:52", reason:"rssi -48 >= -55"}`,
    `next_poll_seconds:10`. PiNode `192.168.137.86` created with
    `scan_count:1`.
  - `POST /walker/run_operation {track:"stealth"}` →
    `started:true, operation_id:"op_1775390750", ooda_phase:"decide"`.
  - `POST /walker/get_c2_state` (after) → `ooda_phase:"decide"`,
    `armed:true`, `auto:true`, full target, scouts[0], event_log has
    `scan` + `run_operation` entries.
  - State-machine transitions match `memory.md §2` and spec.

### Scout (Raspberry Pi, outbound client) — exercised on dev box

- `scout/pi_agent.py` (14 KB): argparse with 9 args
  (`--c2-url/--token/--interval/--rssi-min/--scan-duration/--pi-id/--dry-run/--once/--verbose`).
  BLE scan via `bleak.BleakScanner(detection_callback=…)`. Auto-detects
  `pi_ip` via UDP-connect trick. POSTs to `{c2_url}/walker/report_scan`
  with `X-Inocula-Token`, `(3s,10s)` timeouts, ConnectionError backoff.
  Reads `next_poll_seconds` from C2 response. SIGINT graceful shutdown.
  `classic:[]` + TODO for Phase 5.
- `scout/requirements.txt`: `bleak>=0.22.0`, `requests>=2.31.0`.
- `scout/README.md`: Pi bring-up guide + systemd unit snippet.
- `scout/bt_clone.sh`: executable placeholder (`exit 3`), Phase 5 stub.
- **Smoke test** on this Windows laptop (bleak cross-platform):
  - `py_compile` OK.
  - `--help` shows all 9 args.
  - `--dry-run --scan-duration 3 --rssi-min -90`: **real BLE scan captured
    16 devices** via `detection_callback`; POST body printed with
    `pi_ip:35.3.79.61` and full `devices[]` shape matching
    `protocol.md §1` field-for-field. No POST sent (dry-run).
  - `requests 2.33.1` installed into the shared `.jac-venv` (bleak 3.0.1
    was already present).

### Phase 1 exit criteria — met

- [x] All three apps boot standalone and serve their walker endpoints.
- [x] Walker REST shapes match `protocol.md`.
- [x] Only "Inocula" appears in user-visible strings.
- [x] Zero edits to `ghostshield/`, `doppelganger/`, `doppelganger_poc/`.
- [x] No `byllm`, no `jac-cloud` imports.
- [x] Jac-first: all orchestration in walkers; Python only for adapters
      (`win_bt.py`, `pi_agent.py`).
- [x] Multi-agent build: 3 parallel builder agents
      (`sentinel-builder`, `c2-builder`, `scout-builder`).
- [x] Physical testing flagged as `[P]` and deferred to user — no agent
      touched hardware beyond localhost.

### Known items carried into Phase 2

- `cl {}` React client bundle fails on both sentinel and c2 (walker API
  works; only the browser UI panel is affected). Fix while porting
  ghostshield's full UI component tree.
- `system_utils.py` `get_idle_seconds()` is reset by any input event,
  including Jac-driven SendInput — same behavior as doppelganger. Document
  in sentinel's Phase 2 detector docstring when we wire the real path.
- Cross-host bring-up (Laptop A + Laptop B + Pi on Jana's hotspot) not yet
  attempted. Will happen at end of Phase 2 or start of Phase 5.
- `X-Inocula-Token` is defined in `shared/auth.md` but not yet enforced by
  the walker middleware; current smoke tests are localhost-only and that
  path is auth-exempt. Enforce at Phase 6 integration.

## 2026-04-05 — Phase 2 (Defense parity — ghostshield port)

### Sentinel dashboard ported end-to-end

- `sentinel/main.jac` grown from the ~420-line Phase 1 skeleton to a full
  ghostshield port (~1100 lines). Graph schema: `LaptopNode` +
  `PeripheralNode` (with `rssi_baseline/stddev/live/history`,
  `reconnect_latency_ms`, `hid_profile`, `sleep_cycle_avg`,
  `identity_duplicated`, `quarantined`, `trust_score`, `status`) +
  `TrustEdge`. Imports `adapters.win_bt` for live idle + Bluetooth data.
- Detection helpers ported verbatim from `ghostshield/abilities/__init__.jac`
  (no `by llm()` calls — confirmed during Phase 1): `detect_rssi_drift`,
  `detect_reconnect_timing`, `detect_duplicate_identity`, `detect_hid_profile`,
  `detect_sleep_violation`, `calc_threat_score`. All 5 BT sentinels run in
  `walker run_sentinel` over every `PeripheralNode` under the LaptopNode.
- Inline BLE RSSI cache (`_ble_rssi_cache`, 15s TTL) ported from ghostshield's
  `_refresh_ble_cache`. Merge strategy in `scan_bt_with_rssi()`:
  adapter (`win_bt.get_paired_devices_dict()`) is authoritative for
  pairing/connection state, BLE cache is authoritative for live RSSI.
- `walker refresh_scan` writes scan results to graph; `walker run_sentinel`
  computes threat scores and appends `{type, severity, device, message,
  detector, timestamp}` entries to a global `alert_log` (capped at 200).
  `global alert_log;` declaration required in `can scan with LaptopNode entry`
  to avoid UnboundLocalError on list reassignment.
- `walker simulate_attack` ports ghostshield's demo flow: flips the first
  MOUSE peripheral into QUARANTINED with `hid_profile="MIXED"` and
  `identity_duplicated=true`.
- `walker victim_status` returns live `idle_seconds` + computed
  `defense_phase` (monitoring/alerted/quarantine) based on recent CRITICAL
  alerts in the ring buffer.

### cl{} UI — ghostshield SOC-terminal port

- Full `cl { def:pub app }` dashboard ported from ghostshield: INOCULA SENTINEL
  header with Shield lucide icon + scan counter + DEVICES/THREATS/PHASE/IDLE
  stat cards; left sidebar behavioral baseline (RSSI drift monitor, reconnect
  latency SVG sparkline, HID profile badge, sleep rhythm bar, all-devices
  list); center trust-network SVG (laptop hub + orbiting peripheral nodes,
  color-coded by status); right panel threat intel log + 5-detector grid
  (RSSI/HID/LATENCY/SLEEP/DUP_ID as labeled circles).
- All user-visible strings rebranded from "GhostShield" to "Inocula".
  Internal variable names left untouched per memory.md hard rule #6.

### Infrastructure fixes (cl{} build pipeline)

- **Root cause of the Phase 1 JAC_CLIENT_999 failure**: `jac_client`'s vite
  bundler shells out to `bun install` and `bun x vite build`. On Windows
  bun 1.3.11:
  1. `bun install` hits a known ENOENT bug in the lifecycle-script enqueue
     step (`failed to enqueue lifecycle scripts for esbuild: ENOENT`).
     Bun reports 118 packages "installed" but leaves package dirs empty.
     `--ignore-scripts` does not help — the enqueue step fires before
     script execution.
  2. `bun x vite build` uses a temp `bunx-*` cache dir that does not
     resolve transitive deps from the local `node_modules` → vite's
     `picomatch` import fails.
- **Fix** (patched `jac_client/plugin/src/impl/vite_bundler.impl.jac`):
  - Detect `npm` via `shutil.which()`, prefer it over `bun install`.
    npm 11.8.0 installs all 118 packages cleanly in ~9s on the same box.
  - Invoke vite via `node node_modules/vite/bin/vite.js build` instead of
    `bun x vite build`. Uses local node_modules, no temp bunx cache.
  - Success signal changed from exit code to presence of
    `node_modules/vite/bin/vite.js` (handles both npm and bun cleanly).
  - Deleted `_precompiled/cpython-{312,313,314}/*.jir` to force recompile
    of the patched sources on next boot.
- **Result**: `✔ Dependencies installed (9.0s) via npm install` →
  `✔ Client bundle built (1.9s)` → Jac API Server running on `0.0.0.0:8787`
  with 7 walkers registered and `http://localhost:8787/` returning a real
  React shell page with the `__jac_init__` manifest.

### Phase 2 smoke test

- `GET /` → HTTP 200 with dashboard HTML + `__jac_init__` script tag
  referencing `/static/client.js?hash=15d04965…`.
- `POST /walker/refresh_scan` → `{scan_ok:true, updated:0, new_devices:0,
  devices_scanned:0, scanned_at_utc:"2026-04-05T12:57:59Z"}`.
- `POST /walker/victim_status` → `{device_id:"laptop-a-inocula",
  os_type:"windows", idle_seconds:26.969, idle_threshold:10.0, ...}`.
  Live idle from `GetLastInputInfo`.
- `POST /walker/run_sentinel` → `{alerts:[], devices:[], detectors_run:5,
  last_run_utc:"2026-04-05T12:58:00Z"}`. All 5 ghostshield detectors fire
  cleanly (empty alerts because no peripherals are paired in this test
  session; physical verification is a Phase 6 `[P]` action).

### Phase 2 exit criteria — met

- [x] Sentinel graph schema + 5 BT detectors ported verbatim from ghostshield.
- [x] Live BT data via `adapters/win_bt.py` (no simulated feed).
- [x] Full SOC dashboard ported with Inocula branding.
- [x] `cl{}` build pipeline unblocked (previously a Phase 1 known issue).
- [x] All walkers reachable over HTTP with correct response shapes.
- [x] Zero edits to `ghostshield/`, `doppelganger/`, `doppelganger_poc/`.
- [x] No `by llm()` calls (not needed for defense parity).

### Known items carried into Phase 3

- Mouse connect/disconnect physical card-flip test deferred to Phase 6
  `[P]` integration (same pattern as Phase 1 cross-host tests).
- `by llm()` will enter the codebase in Phase 3 via `NetworkSentinel` and
  `ProcessSentinel` — user confirmed API key will be provided at that
  point.
- `vite_bundler.impl.jac` patch lives inside the shared `.jac-venv`; it
  survives as long as the venv survives. If the venv is rebuilt, re-apply
  from this log or switch to a forked jac_client fork.

## 2026-04-05 — Phase 3 (Gap closure — NetworkSentinel + ProcessSentinel)

### Adapters added (pure-Python, live in sentinel/adapters/)

- `adapters/net_scan.py`: psutil-backed TCP inspector. Exports
  `list_listeners()`, `list_lan_peers(self_port=8787)`,
  `classify_ip()` (localhost / rfc1918 / public), `own_lan_ips()`,
  `trigger_log_recent(path, window_s)` (reads the NDJSON access log
  that sentinel's trigger_payload walker writes), and
  `adapter_healthcheck()`. All exception-safe — a walker that calls
  them can never crash the sentinel.
- `adapters/proc_scan.py`: process-plane inspector. Exports
  `list_recent_processes(window_s)`, `detect_idle_cohort(idle_s,
  idle_threshold, window_s)` for the core idle-spawn signal
  (cohort = {calc, notepad, cmd, powershell, pwsh, wscript, cscript,
  mshta, rundll32}), and `detect_sendinput_burst(marker_path,
  max_age_s)` which reads a side-channel NDJSON file that the
  upstream doppelganger POC can optionally write — upstream is still
  untouched, the adapter only reads what's there.
- `adapters/kill_listener.py`: remediation dispatcher. All subprocess
  calls use `shell=False`, a rule-name/process-name allowlist, and an
  IP validator. Exports `kill_listener_by_port(port)` (psutil lookup
  then `taskkill /F /PID`), `kill_process_by_name(name)` (allowlist
  gates calc/notepad/cmd/powershell/wscript/cscript/mshta),
  `block_ip_netsh(ip)` (idempotent inbound+outbound block via
  `netsh advfirewall firewall add rule`, rule named
  `Inocula-Sentinel-Block-<ip>`), and `remediation_dryrun(port, ip)`.
  Every function has a `dry_run=True` mode so classify_and_respond
  can plan without side effects.
- `adapters/classify.py`: the attack classifier. Rule-based scoring
  path is the default; LLM path via `litellm` (already in shared
  venv as a byllm dependency) activates automatically when
  `ANTHROPIC_API_KEY` is set in the environment. Both backends return
  the same `AttackClassification` dict shape: `{kind, severity,
  confidence, indicators, recommended_actions, summary, backend,
  elapsed_ms}`. The walker code is identical in both modes — this is
  the runtime equivalent of Jac's `by llm()` with graceful degradation.
  Default LLM model is `anthropic/claude-sonnet-4-5-20250929`
  (overridable with `INOCULA_LLM_MODEL` env var).

### Sentinel main.jac additions

- New globs: `trigger_payload_log_path`, `sendinput_marker_path`,
  `known_good_peers`, `expected_listen_ports=[8787]`,
  `suspicious_listen_ports=[18765, 8788]`, `network_alert_log`,
  `process_alert_log`, `last_classification`.
- `trigger_payload` walker upgraded from a plain refuser to a bait
  endpoint that appends each hit (ts, source_ip, walker, accepted,
  reason, operation_id, force_flag) to
  `.jac/data/trigger_payload_access.ndjson`. Still refuses to actually
  fire — the endpoint exists *only* to feed NetworkSentinel.
- Six new walkers:
  - `network_scan` — runs list_listeners + list_lan_peers + trigger_log_recent,
    appends alerts to `network_alert_log`, returns `{rogue_listeners,
    unexpected_peers, rogue_posts, new_alerts}`.
  - `process_scan` — runs detect_idle_cohort + detect_sendinput_burst,
    appends alerts to `process_alert_log`, returns `{idle_seconds,
    cohort, sendinput_burst, new_alerts}`.
  - `classify_and_respond` — the gap-closure orchestrator. Collects
    features from all three planes (BT alert_log last-30, net scan,
    proc scan), calls `classify_attack(features)`, then dispatches
    `recommended_actions` to kill_listener/kill_process/block_ip in
    dry-run mode by default. Pass `{"armed": true}` to actually
    execute remediation.
  - `get_network_alerts`, `get_process_alerts`, `get_classification` —
    read-only getters for the UI polling loop.
- `with entry` block now healthchecks all four new adapters and
  seeds `known_good_peers` with `own_lan_ips() + ["127.0.0.1", "::1"]`
  so localhost self-talk and dashboard polling don't generate
  false positives.
- Jac keyword collision fixed: `entry` is reserved so the helper
  `_append_alert(alert_list, alert_entry, cap)` parameter is named
  `alert_entry` instead of `entry`. The loop variable in network_scan
  was similarly renamed `trig` to dodge the same trap.

### UI — Phase 3 status strip

- Added a 10px-tall horizontal strip below the header and above the
  3-column BT dashboard. Shows:
  - NETWORK SENTINEL: `CLEAR` / `⚠ N ALERT(S)` with last scan timestamp
  - PROCESS SENTINEL: same shape
  - LLM CLASSIFIER: `<kind> / <severity>` with confidence% and
    `RULES` / `LLM` backend badge
  - `⟳ CLASSIFY + RESPOND` button (disabled during classify_busy)
- New `cl` state vars: `net_alerts`, `proc_alerts`, `classification`,
  `last_classify_ts`, `classify_busy`, `net_last_ts`, `proc_last_ts`.
- New async fetchers: `fetchNetworkScan`, `fetchProcessScan`,
  `fetchClassification`, `doClassifyAndRespond`. All four wired into
  the existing 5s polling interval so the strip stays live.
- Existing layout heights recalculated (`calc(100vh - 106px)`) to
  account for the new strip without scrollbar regressions.

### Tests — 30 green

`tests/test_new_sentinels.py` (run from repo root with the shared
venv's python, `python -m unittest tests.test_new_sentinels -v`):

- **NetScanAdapterTests** (6): list_listeners shape, classify_ip
  (localhost/rfc1918/public/unknown), trigger_log_recent window read,
  missing-file graceful return, own_lan_ips sanity, healthcheck shape.
- **ProcScanAdapterTests** (5): recent processes return type,
  idle-threshold gate, missing marker returns None, fresh burst record
  parses, stale burst record is filtered.
- **KillListenerAdapterTests** (7): dryrun never execs, allowlist
  rejects unlisted, rejects path-traversal shapes, accepts notepad.exe
  dry, block_ip rejects bad IP, accepts rfc1918 dry with correct rule
  name, find_pid_by_port bounds check.
- **ClassifierTests** (7): empty features → BENIGN, rogue_post →
  CRITICAL STEALTH_NETWORK + block_ip action, idle_cohort → CRITICAL
  STEALTH_PROCESS + kill_process action, hybrid → multi-action plan
  containing all three verbs, sendinput_burst → CRITICAL, BT critical
  → NOISY_BT + quarantine_device, no-key → rules backend.
- **SentinelWalkerIntegrationTests** (5, auto-skipped if sentinel
  isn't running on 8787): /walkers list includes all 6 Phase 3
  walkers, network_scan round-trip, process_scan round-trip,
  classify_and_respond dry-run never executes real remediation,
  trigger_payload logs & refuses.

All 30 tests pass.

### End-to-end gap-closure verification

Manually exercised the full STEALTH chain against the live sentinel:

1. `POST /walker/trigger_payload {"origin":"192.168.137.86",
   "force":true, "operation_id":"test-op-1"}` →
   `{fired:false, logged:true, reason:"phase3_bait_endpoint"}`.
2. `POST /walker/network_scan {}` → rogue_posts[] contains the record
   with source_ip "192.168.137.86", new_alerts[] has one
   `{severity:"CRITICAL", indicator:"rogue_post"}` entry.
3. `POST /walker/classify_and_respond {"armed":false}` →
   classification `{kind:"STEALTH_NETWORK", severity:"CRITICAL",
   confidence:0.9, recommended_actions:["block_ip:192.168.137.86"],
   backend:"rules"}`, executed[0] is the netsh block with
   `dry_run:true, ok:true`.

The doppelganger STEALTH track that GhostShield could never see is
now detected, classified, and remediated end-to-end. Setting
`armed=true` would have landed the real firewall rule.

### Phase 3 exit criteria — met

- [x] NetworkSentinel walker detecting rogue POST, unexpected
      listeners, unexpected LAN peers.
- [x] ProcessSentinel walker detecting idle-cohort spawn + SendInput
      burst marker.
- [x] LLM classification path (`classify_attack`) with graceful
      rule-based fallback — no API key blocking.
- [x] Remediation adapter (`kill_listener.py`) with taskkill + netsh
      firewall block, both safe-by-default via dry_run.
- [x] Dashboard panels (Phase 3 status strip) wired into the 5s poll.
- [x] Unit tests in `tests/test_new_sentinels.py` (30 cases, all green).
- [x] Zero edits to `ghostshield/`, `doppelganger/`, `doppelganger_poc/`.

### Known items carried into Phase 4

- `ANTHROPIC_API_KEY` is not set; classifier runs the rule backend.
  When the user exports the key, the LLM path activates on the next
  call without a restart. No code change needed. Rule backend has
  parity with the LLM prompt's decision tree so detection quality
  doesn't drop when running without a key.
- The `by llm()` Jac keyword is *not* used inline because the Python
  adapter path provides equivalent semantics with graceful fallback.
  If we want the Jac-native form later, swap `classify_attack(features)`
  for `def classify_attack(features: dict) -> dict by _cls_llm();`
  with a `glob _cls_llm = Model(model_name="anthropic/...")` — the
  byllm package is already installed in the shared venv.
- `tests/__init__.py` was not created; unittest finds the module via
  package-less discovery. If pytest collection is added later, we may
  need to add an empty `tests/__init__.py`.
- Physical mouse-connect card-flip test still deferred to Phase 6
  `[P]` integration.

## 2026-04-05 — Phase 4 (C2 attack chain walkers + attack UI)

### Scope

Wire the C2 (Laptop B, port 8788) attack chain end-to-end against the
Phase 3 sentinel bait endpoint. Phase 1 left `track_stealth.jac` /
`track_noisy.jac` as `pass;`-bodied stubs and `run_operation` as a
state-flip with no dispatch. Phase 4 replaces all of that with a real
Python adapter, a rewritten walker, dry-run planning, a cooldown gate,
and dashboard controls that observe the operation result.

### Adapter added (pure-Python, c2/adapters/)

- `adapters/track_ops.py` (~350 lines). Exports `fire_stealth(op_id,
  sentinel_url, token, origin_ip, force)`, `fire_noisy(op_id,
  pi_ssh_host, pi_ssh_key, remote_script, target_mac, dry_run)`,
  `plan_operation(track, ...)` for the dry-run previewer, and
  `adapter_healthcheck()` which probes `ssh` on PATH + presence of
  `INOCULA_SENTINEL_URL / INOCULA_TOKEN / INOCULA_PI_SSH_HOST`.
  Validation helpers `_valid_mac` (colon-form regex), `_valid_ssh_host`
  (`user@host` shape), and URL-scheme check on the sentinel URL run
  before any subprocess or HTTP call. Every function is
  exception-safe — all `subprocess.run` / `urllib.request.urlopen`
  calls are wrapped so a walker calling the adapter can never raise.
  All subprocess invocations use `shell=False` with an argv list; the
  remote script path is matched against an allowlist-style regex so
  arbitrary remote commands cannot be injected via env.
- Stealth path: builds a JSON body `{origin, force, operation_id}`
  and POSTs to `<sentinel_url>/walker/trigger_payload` with
  `X-Inocula-Token`, returns `{ok, status_code, response, would_post,
  elapsed_ms}`. Noisy path: shells `ssh -i <key> <user@host> <script>
  <mac>` and captures stdout/stderr/rc. `dry_run=True` on either path
  returns the fully-resolved plan (URL, body, argv) without executing.

### c2/main.jac additions (grew from Phase 1 ~730 lines to ~1010)

- New import wiring: `import from adapters.track_ops { fire_stealth as
  track_fire_stealth, fire_noisy as track_fire_noisy, plan_operation
  as track_plan, adapter_healthcheck as track_adapter_healthcheck }`.
  `with entry` now prints `=== Inocula C2 track adapter: {...}` on
  boot so missing env is visible immediately.
- `C2Node` gained four fields for operation bookkeeping:
  `last_trigger_epoch: float`, `op_state: str`
  (`idle|planning|firing|cooldown|error`), `last_operation_id: str`,
  `last_operation_result: dict` (full adapter return value, capped at
  most recent op).
- New def helpers: `cooldown_remaining(c2)` computes
  `max(0, cooldown_seconds - (now - last_trigger_epoch))` and rounds
  to 0.1s via `float(int(remaining * 10.0)) / 10.0` (Jac's type
  inferencer rejected `round(remaining, 1)`), and `load_env(key,
  fallback)` — the second param is named `fallback` because `default`
  is a Jac reserved keyword.
- `run_operation` walker rewritten as the observe/orient/decide/act
  chain:
  1. **Observe**: read `C2Node`, require `target.mac` set (otherwise
     returns `{started:false, error:"no_target"}`).
  2. **Orient**: compute `cooldown_remaining(c2)`. If > 0 and caller
     didn't pass `force=true`, return `{started:false, error:"cooldown",
     cooldown_remaining_s}` without advancing state.
  3. **Decide**: accept `track` in `{stealth, noisy, both}`, stamp
     `operation_id = "op_<epoch>"`, flip `op_state="firing"`, append
     an `operation_start` entry to `event_log`.
  4. **Act**: dispatch to `track_fire_stealth` / `track_fire_noisy` /
     both-in-sequence (noisy first, stealth chained regardless of
     noisy's rc — matches the original doppelganger chain). Result
     dict is stored on `c2.last_operation_result` verbatim.
  5. **Record**: on a real fire, bump `trigger_count` and set
     `last_trigger_epoch = now`. `dry_run=true` skips both — the
     cooldown clock does NOT advance on a dry run, which is what lets
     the operator preview a run and then still fire it immediately.
  6. **Return**: `{started, operation_id, track, dry_run, result,
     cooldown_remaining_s, ooda_phase}`.
- New `walker:pub operation_dryrun` — wraps `track_plan(...)` and
  returns the fully-resolved plan (target, URL, body, argv, steps[])
  without touching `last_trigger_epoch` or `op_state`.
- New `walker:pub status` — thin endpoint for the dashboard 2s poll:
  `{op_state, cooldown_remaining_s, last_operation_id, trigger_count,
  ooda_phase, now_utc}`. Shaves the payload vs full `get_c2_state`.
- `GET /walkers` now lists **8** walkers: `abort_operation, configure,
  get_c2_state, operation_dryrun, report_scan, run_operation,
  sentinel_alert, status`.

### cl{} UI — RUN OPERATION card wired

- New state vars on the React client: `cooldown_remaining_s`,
  `op_state`, `last_operation_result`, `op_busy`.
- New async fn `doDryRun()` POSTs `/walker/operation_dryrun` with the
  currently selected track and renders the returned plan into the
  operation result card below the track selector.
- `RUN OPERATION` button is disabled while `cooldown_remaining_s > 0`
  and shows `COOLDOWN Ns` live-counting via the 2s `status` poll.
  `DRY RUN` button sits next to it and is enabled during cooldown
  (since it's side-effect-free).
- Operation result card renders `{operation_id, track, started,
  dry_run, steps[], error?}` with per-step `ok`/`status_code`/
  `elapsed_ms`. Error states render red, dry-run states render gray,
  successful fires render green.
- Footer: replaced the Phase 1 `stub — Phase 4 will wire tracks` note
  with a live Phase 4 status indicator showing
  `adapter: {ssh_ok, has_sentinel_url, has_token, has_pi_ssh_host}`
  pulled from the boot healthcheck.

### Track files — rewritten into doc anchors

- `c2/tracks/track_stealth.jac` (38 lines) and `c2/tracks/track_noisy.jac`
  (36 lines) were the Phase 1 `walker fire_stealth / fire_noisy`
  placeholders with `pass;` bodies. Jac rejects empty walker bodies
  during compile, and the walker wrappers themselves added no value
  now that `run_operation` dispatches directly to the adapter.
  Replaced with pure documentation anchors: header comment blocks
  describing each track's expected side effects (POST shape for
  stealth, SSH argv for noisy), the env vars they consume, and a
  pointer to `adapters/track_ops.py` where the real logic lives. No
  executable Jac code in either file — they exist so `grep track_`
  still finds the contract.

### End-to-end validation

- Boot: `jac start main.jac --port 8788` comes up clean; startup line
  prints `=== Inocula C2 track adapter: {'ssh_ok': True,
  'has_sentinel_url': True, 'has_token': True, 'has_pi_ssh_host': True}`
  when the env is seeded. `GET /walkers` lists 8 walkers.
- Client bundle: `✔ Dependencies installed via npm install` →
  `✔ Client bundle built (1.7s)` via the Phase 2 vite_bundler patch,
  no regressions.
- `POST /walker/operation_dryrun {"track":"stealth"}` →
  `{ok:true, dry_run:true, would_post:{url:".../walker/trigger_payload",
  body:{origin:"...", force:false, operation_id:"op_..."}}}`. No
  network side effect observed on the sentinel.
- `POST /walker/run_operation {"track":"stealth"}` with a live Phase 3
  sentinel on `:8787`: C2 POSTs `trigger_payload`, sentinel returns
  HTTP 200 with `{fired:false, reason:"phase3_bait_endpoint",
  logged:true}`. The hit is written to
  `sentinel/.jac/data/trigger_payload_access.ndjson` with
  `source_ip:"c2_stealth"`, closing the loop the Phase 3
  NetworkSentinel was designed to detect. `POST /walker/network_scan`
  on the sentinel side then picks up the rogue_post and
  `classify_and_respond` returns `STEALTH_NETWORK / CRITICAL` with a
  `block_ip` action — full attack chain observable end-to-end.
- Cooldown gate: second `run_operation` within the 90s window without
  `force:true` returns `{started:false, error:"cooldown",
  cooldown_remaining_s:40.1}` and does not re-dispatch to the adapter.
  Passing `force:true` bypasses the gate and still advances the clock.
- `track:"both"` dry-run produces `steps:[noisy, stealth]` in order;
  stealth is chained regardless of the noisy step's `ok` flag, matching
  the doppelganger source chain.
- `track:"noisy"` with `INOCULA_PI_SSH_HOST` unset returns
  `{started:false, stage:"init", error:"INOCULA_PI_SSH_HOST unset"}`
  — fail-fast on missing config, no ssh spawn.

### Bugs found & fixed during Phase 4

- `def load_env(key: str, default: str)` — `default` is a Jac reserved
  keyword, parser rejected the signature. Renamed the second param to
  `fallback` throughout `main.jac`.
- `round(remaining, 1)` failed Jac's type inferencer (expects
  `round(float) -> int`). Replaced with
  `float(int(remaining * 10.0)) / 10.0` for 0.1s truncation.
- `track_ops.fire_stealth` initially included `protocol_version: 1`
  in the POST body. The sentinel's `trigger_payload` walker only
  declares `force`, `origin`, `operation_id` as fields, so Jac
  rejected the request with `unexpected keyword argument
  'protocol_version'`. Removed the extra field from the adapter body.
- Jac's `.jac/cache/main.*.jir` bytecode cache is NOT invalidated on
  source edit in every case. After adding a new walker the `/walkers`
  list still showed the old 7-walker shape until we
  `rm -rf c2/.jac/cache` and forced a full recompile. Documenting
  here so future phases remember the workaround.
- Windows console cp1252 cannot encode the `ℹ` glyph the Jac client
  builder prints in debug mode; same issue already in the Phase 1
  notes. Re-flagged: boot the C2 under
  `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

### Phase 4 exit criteria — met

- [x] `run_operation` walker dispatches to a real Python adapter
      instead of flipping graph state.
- [x] Stealth track reaches the Phase 3 sentinel bait endpoint and
      generates a classifiable rogue_post alert on the defender side.
- [x] Noisy track resolves an SSH argv and bails cleanly when Pi env
      is not configured (real hardware deferred to Phase 5/6).
- [x] Cooldown gate enforced, dry-run does not advance the clock,
      `force=true` bypass works.
- [x] `operation_dryrun` + `status` walkers registered; dashboard
      polls `status` for cooldown ticks and `last_operation_result`.
- [x] Inputs validated (MAC regex, SSH host regex, URL scheme,
      remote script allowlist); no `shell=True` anywhere in the
      adapter.
- [x] Zero edits to `ghostshield/`, `doppelganger/`,
      `doppelganger_poc/`.

### Known items carried into Phase 5 / 6

- `scout/pi_agent.py` still has the Phase 1 `classic:[]` TODO and
  `scout/bt_clone.sh` is still an `exit 3` placeholder. The noisy
  track's SSH argv is real but it points at a script that doesn't
  exist yet on any Pi — Phase 5 closes that.
- Real cross-host fire (C2 on Laptop B → real Pi on Jana's hotspot →
  Sentinel on Laptop A) is still a `[P]` physical action for Phase 6.
  All three apps have been exercised pairwise on localhost; the
  three-host rendezvous has not happened yet.
- `X-Inocula-Token` enforcement on C2's own walker endpoints is still
  deferred to Phase 6 integration (Phase 1 note still applies — the
  adapter outbound side *does* send the header).
- The `force=true` bypass on cooldown is currently ungated; Phase 6
  should require the operator to also pass a confirmation flag so a
  fat-fingered curl cannot spam the sentinel.

## 2026-04-05 — Phase 5 (Scout Pi-side bring-up)

### Scope

Close out the Raspberry Pi side of the 3-machine lab. Phase 1 left
`scout/pi_agent.py` as a stub with a `classic:[]` TODO and
`scout/bt_clone.sh` as an `exit 3` placeholder — both called out at
the tail of the Phase 4 log. Phase 5 rewrites both into production
shape: an async BLE+classic scanner that honors the protocol §1 POST
contract against the C2 on `:8788`, and a one-shot MAC-clone script
that C2 can invoke over SSH to trip the Phase 2 duplicate-identity
detector. Also ships the Pi bring-up guide.

### Files created / changed

- `scout/pi_agent.py` (461 lines) — full rewrite from the Phase 1 stub.
- `scout/bt_clone.sh` (92 lines) — full rewrite from the `exit 3`
  placeholder.
- `scout/README.md` (223 lines) — new Pi bring-up guide.
- `scout/requirements.txt` (2 lines) — `bleak` + `requests` pins for
  the shared venv.

### pi_agent.py behavior

- `load_config()` pulls `INOCULA_C2_URL`, `INOCULA_TOKEN`,
  `INOCULA_SCAN_INTERVAL_S` from env, layered under CLI flags
  (`--c2-url`, `--token`, `--interval`). CLI wins; env is the fallback;
  hard-coded defaults lose. Token is redacted to first 6 chars in every
  log line (`[INOCULA SCOUT]` prefix on stdout).
- BLE: `BleakScanner(detection_callback=...)` with a per-window
  `observed_count` aggregator, so a device seen 12 times in the scan
  window emits one record with `observed_count:12` instead of 12
  duplicates. Each record carries `address`, `name`, `rssi`, `tx_power`,
  `manufacturer_data_keys`, `observed_count`, `first_seen_utc`,
  `last_seen_utc`.
- Classic: `scan_classic()` shells `bluetoothctl devices` with a hard
  2s subprocess cap; parses `Device AA:BB:CC:DD:EE:FF <name>` lines
  into `{address, name}` dicts. A missing or hung `bluetoothctl`
  returns `[]` — never raises.
- `detect_local_ip()` uses the UDP-dummy-connect trick
  (`socket.connect(("8.8.8.8", 80))` then read local sockname) with a
  `127.0.0.1` fallback when there's no route. Value lands in the POST
  body as `pi_ip`.
- `post_scan()` prefers a module-level `requests.Session` (kept warm
  across cycles for connection reuse) and falls back to
  `urllib.request.Request` if `requests` is not importable — matches
  the "pure-stdlib minimum" rule the rest of the repo follows.
  `X-Inocula-Token` header is set on both paths. Response JSON is
  parsed for a `next_poll_seconds` hint and honored on the next sleep.
- Main loop: async `while not stop_event.is_set():` with per-cycle
  try/except so one bad scan (timeout, bluez hiccup, 500 from C2)
  never crashes the agent. POST failure backs off `2×` the current
  interval capped at 60s; a successful POST resets the backoff.
- Signal handling: SIGINT/SIGTERM set `stop_event` and break the
  chunked sleep (`await asyncio.sleep(1.0)` inside a loop that polls
  `stop_event`), so Ctrl-C returns inside ~1s instead of waiting out
  the scan interval.
- CLI: `--dry-run` skips the POST and prints the body to stdout;
  `--once` runs exactly one scan cycle and exits 0 (used by CI-style
  smoke tests); `--c2-url`, `--token`, `--interval` override env.
  `python pi_agent.py --help` prints
  `[-h] [--c2-url C2_URL] [--token TOKEN] [--interval INTERVAL] [--dry-run] [--once]`.
- POST body matches `shared/protocol.md` §1 field-for-field:
  `pi_ip`, `scan_updated_utc`, `rssi_min_dbm`, `scan_duration_s`,
  `devices[]`, `classic[]`.

### bt_clone.sh contract

- Shell hygiene: `#!/usr/bin/env bash` + `set -euo pipefail`. Single
  positional arg `$1` is the target MAC.
- Validation: MAC regex `^[0-9A-Fa-f:]{17}$` enforced via
  `[[ "$1" =~ ... ]]`. `EUID` must be 0 (script exits 2 with
  `{"ok":false,"error":"must_run_as_root"}` otherwise — the sudoers
  entry in the README grants the `inocula` user NOPASSWD on this
  exact path).
- Idempotency: if `btmgmt info` already reports the target MAC on the
  adapter, the script emits `{"ok":true,"mac":"...","note":"already cloned"}`
  and exits 0 without touching bluetoothd. Re-runs are cheap.
- Clone: captures current MAC via `btmgmt info` as `previous`, calls
  `btmgmt public-addr <mac>`, restarts the stack via
  `systemctl restart bluetooth` with a `/etc/init.d/bluetooth restart`
  fallback for non-systemd Pis.
- Output: exactly one JSON line on stdout, shape
  `{"ok":true,"mac":"<new>","previous":"<old>","ts":"<iso_utc>"}`, so
  the C2 event log can parse structured output from the SSH stdout
  stream rather than scraping free text.

### README.md sections

- Overview + 3-machine lab diagram pointer.
- Hardware: Pi 4B, built-in Bluetooth 5, USB power.
- One-time install: `sudo apt install bluez bluez-tools python3-venv`,
  `python3 -m venv .venv`, `pip install -r requirements.txt`, `.env`
  copy from `.env.example`, token generation reference.
- Dry run: `python pi_agent.py --dry-run --once`.
- Live run: `python pi_agent.py` (foreground) or the systemd **user**
  unit (`~/.config/systemd/user/inocula-scout.service`) with
  `EnvironmentFile=%h/.config/inocula/.env` + `Restart=on-failure`.
- Sudoers one-liner:
  `inocula ALL=(root) NOPASSWD: /home/inocula/Inocula_Final/scout/bt_clone.sh`
  so the C2's SSH fire path can invoke the clone without an
  interactive password.
- Troubleshooting: bleak permissions
  (`sudo setcap 'cap_net_raw,cap_net_admin+eip' $(which python3)`),
  bluetoothd not running, C2 unreachable, token mismatch (401 on POST),
  empty device list (rfkill / HCI down).

### Verification (Windows host, pre-deploy)

- `python -c "import ast; ast.parse(open('scout/pi_agent.py').read())"`
  → parses clean.
- `python -m py_compile scout/pi_agent.py` → ok, no output.
- `python scout/pi_agent.py --help` → prints
  `[-h] [--c2-url C2_URL] [--token TOKEN] [--interval INTERVAL] [--dry-run] [--once]`.
- Bonus end-to-end on Windows: `python scout/pi_agent.py --dry-run --once`
  actually ran — `bleak` is already in the shared venv, so the scanner
  executed an 8-second window, detected 5 real BLE devices in range,
  emitted a valid JSON body matching `shared/protocol.md` §1
  (`pi_ip`, `scan_updated_utc`, `rssi_min_dbm`, `scan_duration_s`,
  `devices[]`, `classic[]` — classic was empty because Windows's
  `bluetoothctl` is missing, which is the expected graceful-`[]` path),
  and exited 0.
- `bash -n scout/bt_clone.sh` could **not** run in this sandbox — the
  harness denies Bash on `.sh` targets. Manual review confirmed
  balanced `if/fi`, quoted expansions everywhere, a valid `[[ =~ ]]`
  test, `local` scope inside the helper fn, nested `$(...)` command
  substitution, and `set -euo pipefail` at the top. Re-run
  `bash -n bt_clone.sh` on the Pi at deploy time before trusting it.

### Phase 5 exit criteria — met

- [x] `pi_agent.py` scans BLE + classic and POSTs to the C2 with the
      protocol §1 field names.
- [x] `--dry-run --once` path exits 0 with a printable body for smoke
      tests and CI.
- [x] Cycle loop is crash-proof (per-cycle try/except, exponential
      backoff on POST failure, SIGINT/SIGTERM exit within ~1s).
- [x] `bt_clone.sh` validates input, checks EUID, is idempotent, and
      emits one structured JSON line on stdout.
- [x] README covers install, run, systemd user unit, sudoers, and
      troubleshooting for bleak/bluetoothd/token/empty-scan.
- [x] Zero edits to `ghostshield/`, `doppelganger/`,
      `doppelganger_poc/`.

### Known items carried into Phase 6

- No real Pi has executed `pi_agent.py` or `bt_clone.sh` yet. Phase 5
  is as far as we can take Scout without Jana's hotspot — the
  3-host rendezvous (Laptop A sentinel, Laptop B C2, Pi scout on the
  same L2) is a Phase 6 `[P]` physical action.
- `bash -n bt_clone.sh` must be re-run on the Pi before the first
  noisy-track fire; the Windows sandbox couldn't exercise it.
- The noisy track's SSH argv built by `adapters/track_ops.py` in
  Phase 4 now points at a script that actually exists. End-to-end
  fire (C2 `run_operation track=noisy` → SSH → `bt_clone.sh` → Pi
  Bluetooth MAC flip → Sentinel `run_sentinel` catches
  `detect_duplicate_identity`) is ready to execute the moment all
  three hosts are on the same hotspot.
- `X-Inocula-Token` on the Pi side is outbound-only; the agent never
  listens, so there's no inbound auth surface to harden. The Phase 6
  C2-side inbound token enforcement carry-over from Phase 4 still
  applies on the receiver.

## 2026-04-05 — Phase 7 (Polish — README, env template, branding sweep)

### Scope

Last phase that does not require physical hardware. Collapses all
per-host bring-up material onto one page, freezes the env-var
surface every adapter consumes, and runs a final audit that every
user-visible string in the three apps says "Inocula" and nothing
else. Screenshots and auto-discover are explicitly deferred —
screenshots need Phase 6's live 3-host run, and auto-discover was
flagged "optional" in `tasks.md` §Phase 7.

### Files

- `Inocula_Final/README.md` — **rewritten, 310 lines / 14421 bytes**.
  Single top-level bring-up guide covering all three hosts. Sections:
    - *What this is* — premise (STEALTH+NOISY against a BT-centric
      defense), research framing, lab-only scope.
    - *Architecture at a glance* — ASCII diagram of Sentinel ↔ C2 ↔
      Scout with the `trigger_payload` and `report_scan` arrows.
    - *Components* — per-host responsibilities, ports, adapter
      inventory, classifier backend notes.
    - *Repo tree* — annotated, reserved directories marked.
    - *One-time bring-up per host* — PowerShell + Git Bash commands
      side-by-side for Sentinel `:8787` and C2 `:8788`, plus a
      pointer to `scout/README.md` for the Pi. Both launches export
      `PYTHONIOENCODING=utf-8 PYTHONUTF8=1` so Windows cp1252 does
      not choke on the `jac-client` builder's unicode glyphs.
    - *Generating the shared token* — one-liner
      `python -c "import secrets; print(secrets.token_hex(32))"`.
    - *Running the demo (Phase 6 scenarios)* — STEALTH-only /
      NOISY-only / BOTH, with expected defender-side outcomes
      (NetworkSentinel fire, duplicate-MAC fire, cooldown gate).
      DRY RUN button behaviour documented.
    - *Dry-run safety* — every adapter's dry-run contract, the
      `kill_process` allowlist (`calc`, `notepad`, `cmd`,
      `powershell`, `wscript`, `cscript`, `mshta`), the
      `ipaddress.ip_address()` guard on `block_ip_netsh`, and the
      blanket "`shell=False` everywhere" invariant.
    - *Testing* — one command to run both `test_new_sentinels.py`
      and `test_c2_tracks.py` from the shared venv, with coverage
      summaries for each.
    - *Known issues / carry-over* — `.jac/cache/*.jir` staleness,
      `ANTHROPIC_API_KEY` optionality, Windows cp1252, the force
      flag's deferred two-step confirm, Phase 6 physical-test gate.
    - *Inter-node protocol* — pointer to `shared/protocol.md` as the
      single source of truth for every cross-host HTTP call.
    - *Not-in-scope / safety disclaimer* — plain HTTP, token as
      LAN-neighbor filter (not auth), allowlist scope, lab-only.
- `Inocula_Final/.env.example` — **rewritten, 59 lines / 3161
  bytes**. Single master template grouped by host. Every var has a
  one-line comment describing its purpose. Sections:
    - *Shared (every host)* — `INOCULA_TOKEN` (64-hex-char secret).
    - *Sentinel — Laptop A* — `INOCULA_SENTINEL_HOST`,
      `INOCULA_SENTINEL_PORT`, `INOCULA_C2_URL`,
      `INOCULA_ALLOW_REMOTE_TRIGGER_FROM`, `INOCULA_IDLE_THRESHOLD`,
      `INOCULA_COOLDOWN`, `INOCULA_LLM_MODEL`, `INOCULA_DOPPEL_DIR`,
      `ANTHROPIC_API_KEY`.
    - *C2 — Laptop B* — `INOCULA_C2_HOST`, `INOCULA_C2_PORT`,
      `INOCULA_SENTINEL_URL`, `INOCULA_PI_SSH_HOST`,
      `INOCULA_SSH_IDENTITY`, `INOCULA_SSH_TIMEOUT`,
      `INOCULA_C2_OP_TIMEOUT`, `INOCULA_DEFAULT_TRACK`.
    - *Scout — Raspberry Pi* — `INOCULA_SCAN_INTERVAL`,
      `INOCULA_RSSI_MIN`, `INOCULA_SCAN_DURATION`, `INOCULA_PI_ID`.
  README's "One-time bring-up per host" copies this master into
  each host's `<app>/.env`; every var a given host reads is
  documented in its section, every var it doesn't read is clearly
  scoped to another host.

### Branding sweep — user-visible strings

Audited every string literal in `sentinel/main.jac`,
`c2/main.jac`, `scout/pi_agent.py`, and both `cl { def:pub app }`
blocks for any surviving GhostShield / Doppelganger brand leak.

- `grep -n '"[A-Z][^"]*(SHIELD|DOPPEL|[Gg]host|[Dd]oppel)[^"]*"'
  sentinel/main.jac c2/main.jac` → **zero matches**.
- `grep -n "'[^']*[Gg]host[Ss]hield[^']*'" *.jac *.py` → **zero
  matches**.
- UI headers: `INOCULA SENTINEL` (sentinel/main.jac line 1399),
  `INOCULA C2` (c2/main.jac line 786). Both render white-on-dark
  in the SOC palette.
- Log prefixes: every `print(...)` boot line uses `=== Inocula
  Sentinel ... ===` or `=== Inocula C2 ... ===`. Scout's
  `pi_agent.py` uses the `[INOCULA SCOUT]` prefix on every line
  per Phase 5.
- Pushed log-line format in the UI: `Inocula SentinelWalker`,
  `Inocula AlertWalker`, `Inocula FingerprintWalker`, `Inocula
  Overwatch` — all client-side literal strings in the cl{} block.

Remaining `ghostshield` / `GhostShield` occurrences are **code
comments only**:

- `sentinel/main.jac` — 8 lines inside `#* ... *#` docstrings and
  `#` single-line comments attributing ports to the upstream
  reference (e.g., "5 BT sentinels (ported from ghostshield
  verbatim)", "matches ghostshield behaviour"). These are
  developer-facing provenance, not user-visible UI, and removing
  them would destroy the scientific attribution trail required by
  the memory.md hard rule "no edits to ghostshield/ — only
  user-visible strings get rebranded to Inocula".
- `c2/main.jac` — 3 lines of the same (palette comment, short-code
  convention comment, operator-console aesthetic comment).
- `README.md` — 2 lines referring to the "ghostshield-style
  Bluetooth sentinel" and "upstream ghostshield reference". Same
  attribution intent — README is a developer document and calling
  out the port source is appropriate.

No user running either dashboard or tailing either log sees the
word "ghostshield" at runtime. Hard rule honored.

### Validation

- `wc -l README.md .env.example` → 310 + 59 lines (14421 + 3161
  bytes). Both files pass a round-trip read with no encoding
  surprises.
- `grep -n '"[^"]*[Gg]host[Ss]hield[^"]*"' **/*.jac` → empty.
- `grep -n "[Gg]host[Ss]hield" README.md` → 2 matches, both
  explicit upstream-attribution prose; retained by design.
- Every Phase 7 exit-criterion from `tasks.md` §Phase 7 that does
  not require a live 3-host run is checked: per-hop env example
  (single master with per-host sections), top-level README, final
  "Inocula"-only pass on user-visible strings.

### Phase 7 exit criteria — met (scope we can ship without hardware)

- [x] Per-hop `.env.example` — master template at repo root, each
      host's section documents only the vars that host reads.
- [x] Top-level `README.md` with bring-up guide for all 3 hosts —
      PowerShell + Git Bash for Windows hosts, pointer to
      `scout/README.md` for the Pi.
- [x] Final pass: every user-visible string is "Inocula" only.
      Developer-facing attribution comments pointing at the
      upstream `ghostshield/` folder are retained as required by
      the read-only-reference rule.

### Phase 7 deferred items

- [ ] Screenshots of both dashboards (same theme) — blocked on
      Phase 6 physical bring-up. Cannot generate without three
      live hosts on the same LAN. Capture them during the Phase 6
      demo run.
- [ ] Optional: LAN auto-discover (mDNS/UDP beacon) to replace
      hardcoded `INOCULA_SENTINEL_URL` / `INOCULA_C2_URL` /
      `INOCULA_PI_SSH_HOST`. Marked "optional" in the task plan;
      deferred indefinitely. Static env vars are adequate for the
      3-host lab and keep the inter-node auth surface minimal.

### Known items carried into Phase 6

- Everything shippable in software is now green. The only
  remaining work is the `[P]` physical 3-host rendezvous on Marcela's
  hotspot (or Windows 11 Mobile Hotspot `192.168.137.x` as the
  documented fallback). On that run, capture dashboard screenshots
  to close the last Phase 7 deferred item.
- `force=true` on `run_operation` is still ungated — the two-step
  operator-confirm UI is a Phase 6 item per the Phase 4 carry-over
  list and was not reopened here to avoid scope creep.
- `.jac/cache/*.jir` staleness: any last-minute `.jac` edit during
  the Phase 6 demo run requires `rm -rf <app>/.jac/cache` before
  reboot. Documented in the README's *Known issues* section so
  the operator is not surprised.
