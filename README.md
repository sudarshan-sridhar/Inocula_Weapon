# Inocula — 3-machine BLE attack/defense lab

## What this is

Inocula is a security-research lab that runs a hybrid **STEALTH + NOISY** attack
scenario across three hosts and measures how a BLE-centric defense reacts. The
premise: an existing ghostshield-style Bluetooth sentinel catches the NOISY leg
of the attack (a one-shot MAC clone on a Pi) but is blind to the STEALTH leg
(a network-borne HID payload trigger). To close that gap, Inocula ships two
new defense walkers — **NetworkSentinel** and **ProcessSentinel** — built in
Phase 3 on top of the ported 5-detector BT sentinel suite.

This repo is purely for **defense research in a private lab**. It is not
offensive tooling. Every track has a dry-run path, every destructive action
is gated by an allowlist, and every inter-node call is bounded by a shared
token and a lab-only LAN. Do not run it outside the lab.

## Architecture at a glance

```
                   ┌──────────────────────────┐
                   │   Laptop A — Sentinel    │
                   │   Defense, port 8787     │
                   │   BT x5 + Network + Proc │
                   └──────────────┬───────────┘
                        trigger_payload ▲
                                        │
                                        │ sentinel_alert
                                        ▼
 ┌──────────────────┐   report_scan    ┌──────────────────────────┐
 │   Pi — Scout     │ ───────────────▶ │   Laptop B — C2          │
 │   BLE + classic  │                  │   Attack orchestrator,   │
 │   (outbound)     │ ◀─ ssh bt_clone  │   port 8788              │
 └──────────────────┘                  └──────────────────────────┘
```

Scout has no inbound port; it only initiates outbound HTTP to C2. C2 calls
Sentinel for the STEALTH track and `ssh`s into the Pi for the NOISY track.
Sentinel optionally fires `sentinel_alert` webhooks back to C2 when its new
detectors trip, so the attacker dashboard can reflect the defender's view.

## Components

- **Sentinel** (Laptop A, Windows, `:8787`) — defense host. Ports the 5 BT
  sentinels (RSSI drift, reconnect timing, duplicate MAC, HID profile, sleep
  violation) from the upstream ghostshield reference plus the Phase 3
  NetworkSentinel (rogue inbound POST, unknown listener, LAN peer scan) and
  ProcessSentinel (calc+notepad co-spawn during idle, SendInput burst). The
  `sentinel/adapters/classify.py` module runs the attack classifier with an
  optional `by llm()` / LiteLLM backend and a rule-based fallback. Jac walker
  host plus a `cl {}` React dashboard served from the same port.
- **C2** (Laptop B, Windows, `:8788`) — attack orchestrator. Implements the
  observe/orient/decide/act `run_operation` walker chain, dispatches to
  `c2/adapters/track_ops.py` (pure Python), and hosts a `cl {}` operator
  console with a target lock card, Scout liveness card, stealth/noisy/both
  track selector, a cooldown-aware RUN OPERATION button, and a dry-run
  previewer.
- **Scout** (Raspberry Pi, outbound only) — passive BLE scanner that POSTs
  scan snapshots to C2. On the NOISY track, C2 SSHes in and runs
  `bt_clone.sh` to one-shot a paired MAC clone. See `scout/README.md` for
  the full Pi bring-up — this top-level README does not duplicate it.

## Repo tree

```
Inocula_Final/
├── README.md                 (this file)
├── .env.example              master env template — copy per host
├── memory.md                 project ground truth, ports, hosts
├── tasks.md                  phased plan
├── TASKS_COMPLETED.md        phase-by-phase build log
│
├── sentinel/                 Laptop A — defense (port 8787)
│   ├── main.jac              graph + 5 BT sentinels + walkers + cl{} UI
│   ├── jac.toml
│   ├── adapters/             Python adapters
│   │   ├── win_bt.py         WinRT BT enum via doppelganger/system_utils.py
│   │   ├── net_scan.py       NetworkSentinel data source
│   │   ├── proc_scan.py      ProcessSentinel data source
│   │   ├── classify.py       LLM + rule-based attack classifier
│   │   └── kill_listener.py  remediation: taskkill + netsh block
│   ├── abilities/            (reserved)
│   ├── graph/                (reserved)
│   ├── response/             (reserved)
│   ├── sentinels/            (reserved — code inline in main.jac)
│   └── ui/                   (reserved — cl{} blocks inline in main.jac)
│
├── c2/                       Laptop B — attack (port 8788)
│   ├── main.jac              C2Node graph + run_operation chain + cl{} console
│   ├── jac.toml
│   ├── adapters/
│   │   └── track_ops.py      fire_stealth / fire_noisy / plan_operation
│   ├── tracks/
│   │   ├── track_stealth.jac doc anchor for the stealth contract
│   │   └── track_noisy.jac   doc anchor for the noisy contract
│   ├── graph/                (reserved)
│   ├── walkers/              (reserved — code inline in main.jac)
│   └── ui/                   (reserved — cl{} blocks inline in main.jac)
│
├── scout/                    Raspberry Pi — BLE sensor
│   ├── README.md             Pi bring-up guide (systemd unit, flags)
│   ├── pi_agent.py
│   ├── bt_clone.sh
│   └── requirements.txt
│
├── shared/
│   ├── protocol.md           authoritative HTTP + JSON contracts
│   └── auth.md               X-Inocula-Token spec + per-host .env layout
│
└── tests/
    ├── test_new_sentinels.py Phase 3 — NetworkSentinel, ProcessSentinel, classify
    └── test_c2_tracks.py     Phase 4 — C2 track adapter (mocked HTTP + SSH)
```

Each Jac app grows a `.jac/cache/` folder on first boot holding compiled JIR
bytecode. Do not commit it. Clear it (`rm -rf <app>/.jac/cache`) after editing
`.jac` sources if a new walker is not picked up by `/walkers`.

## One-time bring-up per host

Every host follows the same shape: clone the repo, activate the shared Jac
venv, copy `.env.example` to `<app>/.env`, fill in the host-specific values,
and boot the walker server. The shared venv lives at
`C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/` and already has
`jaclang`, `jac-client`, `byllm`, `litellm`, and `psutil` installed.

### Laptop A — Sentinel (`:8787`)

```powershell
# PowerShell
cd C:\Users\sudar\inocula\Inocula_Final
copy .env.example sentinel\.env
# Edit sentinel\.env: set INOCULA_TOKEN, INOCULA_C2_URL, INOCULA_ALLOW_REMOTE_TRIGGER_FROM
cd sentinel
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
C:\Users\sudar\OneDrive\Desktop\inocula\.jac-venv\Scripts\jac.exe start main.jac --port 8787
```

```bash
# Git Bash equivalent
cd /c/Users/sudar/inocula/Inocula_Final
cp .env.example sentinel/.env
# edit sentinel/.env
cd sentinel
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
    "/c/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/jac.exe" \
    start main.jac --port 8787
```

`node` and `npm` must be on `PATH` for the `cl {}` bundle build — `jac-client`
shells out to `npm install` and `vite build` on first boot. Phase 2 replaced
the original `bun` path with `npm` via a `vite_bundler` patch, so `bun` is no
longer required.

### Laptop B — C2 (`:8788`)

```powershell
cd C:\Users\sudar\inocula\Inocula_Final
copy .env.example c2\.env
# Edit c2\.env: set INOCULA_TOKEN, INOCULA_SENTINEL_URL, INOCULA_PI_SSH_HOST
cd c2
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
C:\Users\sudar\OneDrive\Desktop\inocula\.jac-venv\Scripts\jac.exe start main.jac --port 8788
```

```bash
cd /c/Users/sudar/inocula/Inocula_Final
cp .env.example c2/.env
cd c2
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
    "/c/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/jac.exe" \
    start main.jac --port 8788
```

On boot, C2 prints its track-adapter healthcheck:

```
=== Inocula C2 track adapter: {'ssh_ok': True, 'has_sentinel_url': True,
                               'has_token': True, 'has_pi_ssh_host': True}
=== Inocula C2 Ready (port 8788) ===
```

Any `False` there points at a missing env var — fix the `.env` and restart.

### Raspberry Pi — Scout

See `scout/README.md` for the complete guide (systemd unit, flags, backoff
behaviour). The one-line live-mode command once the Pi `.env` is in place:

```bash
python3 /home/inocula/Inocula_Final/scout/pi_agent.py
```

## Generating the shared token

Run this once on any host and paste the result into `INOCULA_TOKEN` on all
three `.env` files:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Never commit `.env` files. The token is a lab convenience, not a secure auth
mechanism. Rotate it by regenerating and redistributing — there is no key
negotiation. Full details in `shared/auth.md`.

## Running the demo (Phase 6 scenarios)

All three apps must be live, on the same LAN, and each host's `.env` must
point at the other two. The scenarios mirror `tasks.md` Phase 6.

1. **Scenario 1 — STEALTH only.** On C2, select `stealth` in the track
   dropdown, lock a target, click **RUN OPERATION**. C2 POSTs to
   Sentinel's `/walker/trigger_payload`. Expected: Sentinel's
   `NetworkSentinel` flags the rogue POST, `classify_and_respond`
   emits `STEALTH_NETWORK / CRITICAL` with a `block_ip` action, the
   defense dashboard lights up red, and C2 receives a `sentinel_alert`
   webhook.
2. **Scenario 2 — NOISY only.** Select `noisy` on C2 and run. C2 SSHes
   into the Pi and runs `bt_clone.sh <target_mac>`. The Pi clones the
   paired MAC for ~1s. Expected: Sentinel's duplicate-MAC BT detector
   fires, the remediation walker removes the offending device via
   `pnputil /remove-device`, and the BT card flips to red on the
   dashboard.
3. **Scenario 3 — BOTH.** Select `both`. Noisy runs first (trips the BT
   sentinel), stealth chains immediately after (trips NetworkSentinel)
   regardless of the noisy step's return code. Back-to-back runs are
   rejected until the cooldown clock (default 90s) expires; the
   RUN OPERATION button live-counts `COOLDOWN Ns` during the wait.

Each scenario is also available as a dry-run via the **DRY RUN** button,
which calls `/walker/operation_dryrun` and renders the resolved plan
(URL, body, argv, steps) without touching the cooldown clock or firing
the adapter.

## Dry-run safety

- Every track function accepts `dry_run: true`; when set, the adapter
  returns the fully-resolved plan (URL, body, ssh argv) without executing
  anything. The C2 cooldown clock does **not** advance on a dry run, so an
  operator can preview a fire and then still execute it immediately.
- `kill_process` in `sentinel/adapters/kill_listener.py` is guarded by a
  hardcoded allowlist: `calc`, `notepad`, `cmd`, `powershell`, `wscript`,
  `cscript`, `mshta`. Any other target name is refused before `taskkill`
  runs.
- `block_ip_netsh` validates the target via `ipaddress.ip_address()`
  before constructing the `netsh advfirewall` command.
- No subprocess in either adapter uses `shell=True`. Every call passes
  an argv list with validated components (MAC regex, SSH host regex,
  URL scheme check, remote-script path allowlist).

## Testing

From the repo root, using the shared venv's Python:

```bash
cd C:/Users/sudar/inocula/Inocula_Final
C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/python.exe \
    -m unittest discover tests -v
```

- `tests/test_new_sentinels.py` — Phase 3 coverage. Unit tests for the
  NetworkSentinel and ProcessSentinel data-source adapters, the rule
  backend of `classify_attack` (with and without `ANTHROPIC_API_KEY`),
  and `kill_listener.py` in dry-run mode. Includes one optional
  integration case that hits a live sentinel on `:8787` if one is
  already running; it skips cleanly otherwise.
- `tests/test_c2_tracks.py` — Phase 4 coverage. Unit tests for
  `c2/adapters/track_ops.py`: stealth POST body shape, cooldown gate,
  SSH argv construction, MAC/host/URL validators, and `plan_operation`
  dry-run dispatch. `urllib.request.urlopen` is mocked and every noisy
  call runs with `dry_run=True`, so no network traffic and no real ssh.

## Known issues / carry-over

See `TASKS_COMPLETED.md`, Phase 4 "Known items carried into Phase 5 / 6"
for the authoritative list. Highlights:

- `ANTHROPIC_API_KEY` is optional. Unset = classifier runs the rule
  backend with decision-tree parity to the LLM prompt. Set the key and
  the LLM path activates on the next call without a restart.
- Jac's `.jac/cache/*.jir` bytecode cache is not invalidated on every
  source edit. If a newly-added walker does not appear in `/walkers`
  after an edit, `rm -rf <app>/.jac/cache` and reboot.
- Windows console cp1252 cannot encode some glyphs the Jac client
  builder prints at boot. Always launch under
  `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.
- The force-bypass flag on `run_operation` is currently ungated and
  deferred to Phase 6 for a two-step confirmation.
- Cross-host physical validation (Laptop A + Laptop B + Pi on Marcela's
  hotspot, or the Win11 Mobile Hotspot fallback at `192.168.137.x`) is
  still a `[P]` action for Phase 6.

## Inter-node protocol

One authoritative contract for every HTTP call, every JSON envelope,
every timeout, and every error code: `shared/protocol.md`. Start there
before modifying anything that crosses a host boundary.

## Not-in-scope / safety disclaimer

This is lab-only research code. There is no TLS — every inter-node call
is plain HTTP. The `X-Inocula-Token` header is a casual-LAN-neighbor
filter, not a secure authentication mechanism. The `kill_process`
allowlist is scoped to the specific binaries the demo scenarios spawn
(`calc`, `notepad`, and a handful of scripting hosts) and is not a
general-purpose endpoint defense. The network-block path edits the
local Windows firewall via `netsh advfirewall` and assumes operator
supervision. Do not deploy any of this outside a private, trusted LAN
under direct human control.
