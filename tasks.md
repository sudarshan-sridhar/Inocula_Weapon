# Inocula — Task Plan

> Phased plan for building the 3-machine Inocula lab. Status legend:
> `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked ·
> `[P]` needs physical testing by user
>
> **Source of truth for facts**: see `memory.md`.
> **Log of what is actually finished**: see `TASKS_COMPLETED.md` (created at
> end of Phase 1).

---

## Phase 0 — Ideation lock *(done)*

- [x] Read ghostshield repo end-to-end (`marcebd/inocula/ghostshield/`)
- [x] Read doppelganger + doppelganger_poc end-to-end
- [x] Identify GhostShield ↔ doppelganger detection gap
- [x] Propose Option A / B / C
- [x] User chose **Option C — Hybrid**
- [x] User chose **Laptop B = UI + Orchestrator**
- [x] Freeze upstream folders as read-only reference
- [x] Create `Inocula_Final/memory.md`
- [x] Create `Inocula_Final/tasks.md` (this file)

## Phase 1 — Skeleton *(done 2026-04-05 — see TASKS_COMPLETED.md)*

Goal: all three Jac apps boot to an empty dashboard on their target port
and can ping each other over HTTP. No detection logic yet.

- [x] Create folder tree (see §Tree below)
- [x] Write `shared/protocol.md` — JSON contracts for every inter-node call
- [x] Write `shared/auth.md` — `X-Inocula-Token` header spec, `.env` layout
- [x] `sentinel/main.jac` — boots on `:8787`, walker REST live
- [x] `c2/main.jac` — boots on `:8788`, walker REST live, OODA transitions
- [x] `scout/pi_agent.py` — live BLE scan, dry-run prints POST body
- [x] `sentinel/adapters/win_bt.py` — wraps `doppelganger/system_utils.py`
- [x] Smoke test each app standalone — all three green
- [x] Write `TASKS_COMPLETED.md` with Phase 1 log
- [ ] `[P]` **User action (carried into Phase 2)**: run the three apps on
      their target hosts and confirm LAN reachability — not required for
      Phase 1 exit, required for Phase 6 integration.

**Agents on this phase**: `sentinel-builder`, `c2-builder`, `scout-builder` in
parallel after tree is created. `scribe` at end. `reviewer` before declaring
done.

## Phase 2 — Defense parity (port GhostShield)

Goal: Laptop A's Inocula Sentinel dashboard looks and behaves identically to
current ghostshield, using `doppelganger/system_utils.py` as the live BT data
source instead of the old stub.

- [ ] Port `ghostshield/main.jac` graph schema → `sentinel/graph/`
- [ ] Port `ghostshield/abilities/__init__.jac` (ThreatAnalysis,
      AttackClassification, RiskAssessment, RemediationPlan) verbatim
- [ ] Port `ghostshield/response/__init__.jac` → `sentinel/response/`
      (Windows: `pnputil /remove-device`, `BlockInput`, `LockWorkStation`)
- [ ] Port the 5 BT sentinels (RSSI drift, reconnect timing, duplicate MAC,
      HID profile, sleep violation) → `sentinel/sentinels/bt.jac`
- [ ] Wire live data: replace ghostshield's simulated device feed with
      `win_bt.get_paired_devices_dict()` + `win_bt.get_idle_seconds()`
- [ ] Port the `cl {}` React UI verbatim → `sentinel/ui/`
- [ ] Rename every user-facing string from "GhostShield" to "Inocula" (UI only,
      internal var names may stay)
- [ ] Sanity test: mouse connect/disconnect flips the dashboard card
- [ ] `scribe` updates `TASKS_COMPLETED.md`

**Agents**: `sentinel-builder`, `scribe`, `reviewer`.

## Phase 3 — Gap closure (the new sentinels)

Goal: the two new detectors that catch the STEALTH track.

- [ ] `sentinel/sentinels/network.jac` — **NetworkSentinel** walker
  - [ ] Detect rogue inbound POST to `/trigger` from non-whitelisted LAN host
  - [ ] Detect unknown listener on port `18765` or `8787` opened locally
  - [ ] Detect unexpected LAN hosts scanning `:8787`
  - [ ] `by llm()` classification → `AttackClassification` object
- [ ] `sentinel/sentinels/process.jac` — **ProcessSentinel** walker
  - [ ] Detect `calc.exe` + `notepad.exe` co-spawn while idle >= threshold
  - [ ] Detect SendInput burst from non-interactive parent
  - [ ] `by llm()` classification → `AttackClassification` object
- [ ] `sentinel/response/kill_listener.py` — adapter to taskkill + netsh
      firewall block
- [ ] Add panels for both new sentinels to the dashboard (same `cl {}` palette)
- [ ] Unit tests in `tests/test_new_sentinels.py`
- [ ] `scribe` updates `TASKS_COMPLETED.md`

**Agents**: `detector-smith`, `tester`, `scribe`, `reviewer`.

## Phase 4 — C2 on Laptop B (the attack orchestrator)

Goal: Laptop B runs the full attack walker chain and hosts the attack UI.

- [ ] `c2/graph/` — `C2Node`, `ScoutEdge → PiNode`, `TargetEdge → VictimNode`
- [ ] `c2/walkers/run_operation.jac` — main chain:
      `poll_scout → decide → select_track → fire_track → report`
- [ ] `c2/tracks/track_stealth.jac` — POSTs to victim's existing listener
      (reuses doppelganger's proven HTTP → SendInput path as the last mile,
      but called FROM Laptop B instead of localhost)
- [ ] `c2/tracks/track_noisy.jac` — SSH-to-Pi + runs `bt_clone.sh` one-shot;
      then fires stealth track as the "payload" after MAC clone registers
- [ ] `c2/walkers/abort.jac` — kill switch
- [ ] `c2/walkers/status.jac` — live state for dashboard polling
- [ ] `c2/ui/` — attack dashboard, same ghostshield aesthetic:
  - [ ] Target card (which victim + which paired device)
  - [ ] Scout card (Pi liveness, last scan, RSSI)
  - [ ] Track selector (Noisy / Stealth / Both)
  - [ ] Big red "Run operation" button with cooldown UI
  - [ ] Live event stream (same log component as sentinel)
- [ ] `scribe` updates `TASKS_COMPLETED.md`

**Agents**: `c2-builder`, `scout-builder`, `scribe`, `reviewer`.

## Phase 5 — Scout (Pi side)

Goal: Pi runs one process that serves both tracks.

- [ ] `scout/pi_agent.py` — same scan loop as doppelganger, posts to C2 `:8788`
- [ ] `scout/bt_clone.sh` — `btmgmt public-addr <mac>` wrapper, idempotent,
      gated on arg from C2
- [ ] `scout/README.md` — bring-up steps for the Pi (systemd user service,
      no sudo surprises)
- [ ] `scout/requirements.txt` — bleak, requests
- [ ] `scribe` updates `TASKS_COMPLETED.md`
- [P] **User action**: deploy to Pi, run dry-run, confirm scan reaches C2

**Agents**: `scout-builder`, `scribe`, `reviewer`.

## Phase 6 — End-to-end integration

Goal: all three machines on the hotspot, both tracks fire, both defenses react.

- [ ] `shared/protocol.md` frozen — final JSON contract
- [ ] `integrator` wires cross-host auth + retries + timeouts
- [ ] `tests/test_inocula.py` — full suite mirroring `test_doppelganger.py`,
      but runs across the 3 hosts
- [ ] Demo scenario 1: STEALTH track → NetworkSentinel fires → remediation
      kills listener → dashboard shows red card + LLM analysis
- [ ] Demo scenario 2: NOISY track → duplicate MAC sentinel fires → device
      removed via `pnputil /remove-device` → dashboard shows red card
- [ ] Demo scenario 3: BOTH tracks back-to-back, cooldown honored
- [ ] `scribe` final update, `reviewer` final pass
- [P] **User action**: run the 3 scenarios on Marcela's hotspot; switch to Win11
      Mobile Hotspot as fallback if Marcela's drops

**Agents**: `integrator`, `tester`, `scribe`, `reviewer`.

## Phase 7 — Polish

- [ ] Per-hop `.env.example`
- [ ] Top-level `README.md` with bring-up guide for all 3 hosts
- [ ] Screenshots of both dashboards (same theme)
- [ ] Optional: auto-discover sibling hosts on the LAN to skip hardcoded IPs
- [ ] Final pass: every user-visible string is "Inocula" only

---

## Tree (created in Phase 1)

```
Inocula_Final/
├── memory.md                ← done
├── tasks.md                 ← done (this file)
├── TASKS_COMPLETED.md       ← created at end of Phase 1, appended every phase
├── README.md                ← Phase 7
├── .env.example             ← Phase 1
│
├── sentinel/                ← Laptop A (victim defense)
│   ├── main.jac
│   ├── graph/
│   ├── abilities/
│   ├── response/
│   ├── sentinels/
│   │   ├── bt.jac           ← 5 ported detectors
│   │   ├── network.jac      ← NEW
│   │   └── process.jac      ← NEW
│   ├── adapters/
│   │   └── win_bt.py        ← thin import of doppelganger/system_utils.py
│   └── ui/                  ← ported cl{} components from ghostshield
│
├── c2/                      ← Laptop B (attacker C2 + orchestrator)
│   ├── main.jac
│   ├── graph/
│   ├── walkers/
│   │   ├── run_operation.jac
│   │   ├── abort.jac
│   │   └── status.jac
│   ├── tracks/
│   │   ├── track_stealth.jac
│   │   └── track_noisy.jac
│   └── ui/                  ← same aesthetic, different layout
│
├── scout/                   ← Raspberry Pi
│   ├── pi_agent.py
│   ├── bt_clone.sh
│   ├── requirements.txt
│   └── README.md
│
├── shared/
│   ├── protocol.md          ← JSON contracts
│   ├── auth.md              ← X-Inocula-Token spec
│   └── types.jac            ← shared type defs if needed
│
└── tests/
    ├── test_sentinel.py
    ├── test_new_sentinels.py
    ├── test_c2.py
    └── test_inocula.py      ← e2e
```

## Testing policy

- **Unit tests**: every walker, every adapter, every `by llm()` object gets a
  test. Run locally on whichever host is building.
- **Integration tests**: mocked HTTP by default; real HTTP when all 3 hosts
  are up.
- **Physical tests** (`[P]`): agents pause and notify the user. User runs the
  physical step, reports back, agents resume.
- **Regression**: after every phase, the `tester` agent runs the full suite.
  No green → no phase completion.

## Non-goals (explicit)

- Not implementing a BlueZ HID peripheral on the Pi
- Not implementing custom GATT server
- Not implementing pairing manipulation or bond key extraction
- Not attempting "air-gap keystroke injection" — already proven infeasible in
  `doppelganger/TASKS_COMPLETED.md`
- Not modifying any file under `ghostshield/`, `doppelganger/`, `doppelganger_poc/`
- Not renaming internal variables in ported code (only user-visible strings
  get rebranded to Inocula)
