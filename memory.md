# Inocula — Project Memory (source of truth, update as facts change)

> This file is the **ground truth** for the Inocula 3-machine lab. It exists
> to prevent hallucination across long sessions. Any agent or human working on
> Inocula reads this first. If a fact here is wrong, fix it here before
> writing code that depends on it.

---

## 1. Project identity

- **Official name**: Inocula (both attack and defense; no other brand names in UI)
- **Team**: Inocula (JacHacks 2026)
- **Upstream reference repos** (READ-ONLY — never modify):
  - `C:\Users\sudar\inocula\doppelganger\`       → current working attack
  - `C:\Users\sudar\inocula\doppelganger_poc\`   → earlier attack iteration + lab notes
  - `C:\Users\sudar\OneDrive\Desktop\inocula\ghostshield\` → **local clone** of
    `marcebd/inocula` defense app (source of truth for defense code + UI)
  - `.jac-venv` at `C:\Users\sudar\OneDrive\Desktop\inocula\.jac-venv\` → shared
    Jac runtime (jaclang 0.13.5, jac_client 0.3.11, bleak, winrt). **Use this
    venv's `jac.exe` to boot all Inocula apps — do not create a new venv.**
- **New work lives only in**: `C:\Users\sudar\inocula\Inocula_Final\`

## 2. High-level architecture (locked)

3 machines on the same WiFi (Marcela's hotspot OR Win11 Mobile Hotspot fallback):

```
[Laptop A — VICTIM]         [Laptop B — ATTACKER C2]       [Raspberry Pi — SCOUT]
Sentinel (Jac)              C2 + Orchestrator (Jac)        pi_agent.py + bt_clone
- Defense dashboard         - Attack dashboard             - Passive BLE scan
- BT sentinels (5)          - Track selector: noisy/stealth- Classic BT probe
- NEW NetworkSentinel       - run_operation walker chain   - Optional btmgmt MAC
- NEW ProcessSentinel       - Polls Scout, calls Victim      clone (noisy track only)
- HID payload landing
```

- **Chosen defense/attack strategy**: Option **C — Hybrid** (two parallel tracks)
  - **Track NOISY**: Pi clones a paired MAC (`btmgmt public-addr`) → GhostShield's existing **duplicate MAC** detector fires → Remediation walker reacts.
  - **Track STEALTH**: current network-trigger path (Pi HTTP → Victim listener → SendInput calc/notepad) → caught by **new NetworkSentinel + ProcessSentinel** only. Proves why defense had to be extended.
- **Laptop B role**: UI **AND** orchestrator. It runs the Jac walker chain itself. Laptop A never sees the attacker UI.
- **Language**: Jac-first (walkers, graphs, `by llm()`, `cl {}` UI). Python only for thin adapters that Jac cannot reach (WinRT PowerShell wrapper, SendInput, bleak). Every orchestration/decision step is a walker.
- **UI aesthetic**: identical to ghostshield's SOC-terminal `cl {}` components. Both defense dashboard (A) and attack dashboard (B) share the palette, fonts, and component library. No visual drift.

## 3. Multi-agent roster (the agents that build Inocula)

These are the Claude sub-agents I will spawn to parallelize work. Each one has a
narrow scope and reads this `memory.md` before acting. Naming convention is
`inocula-<role>`.

| Agent | Scope | Writes to | Reads |
|---|---|---|---|
| **scribe** | Keeps `memory.md`, `tasks.md`, `TASKS_COMPLETED.md` accurate. Runs after every phase. | `Inocula_Final/*.md` | everything |
| **sentinel-builder** | Builds Laptop A defense: `sentinel/` Jac app, ports GhostShield UI + 5 BT detectors. | `Inocula_Final/sentinel/` | `ghostshield/`, `doppelganger/system_utils.py` |
| **detector-smith** | Writes NEW NetworkSentinel + ProcessSentinel walkers + their `by llm()` abilities. | `Inocula_Final/sentinel/sentinels/` | `doppelganger/serve.py`, `doppelganger/system_utils.py` |
| **c2-builder** | Builds Laptop B attack C2: Jac walker chain, attack dashboard, track selector. | `Inocula_Final/c2/` | ghostshield UI components, `doppelganger/` |
| **scout-builder** | Adapts `pi_agent.py` to point at C2 instead of victim; writes `bt_clone.sh`. | `Inocula_Final/scout/` | `doppelganger/pi_agent.py` |
| **integrator** | Wires all three nodes over HTTP, auth headers, JSON contracts in `shared/protocol.md`. | `Inocula_Final/shared/` | all three app dirs |
| **tester** | Writes + runs `test_inocula.py`. Unit tests run locally; integration tests flag physical testing. | `Inocula_Final/tests/` | all |
| **reviewer** | Reads PR-sized diffs before finalization; flags mismatches vs this memory file. | nothing (read-only) | all |

**Parallelism rules**: `sentinel-builder` + `c2-builder` + `scout-builder` can run
in parallel after Phase 1 skeleton exists. `detector-smith` blocks on
`sentinel-builder`. `integrator` blocks on all three builders. `tester` runs after
each phase and before handoff. `scribe` runs at the end of every phase.
`reviewer` runs before declaring a phase done.

## 4. Network invariants

- **Primary transport**: Marcela's hotspot (SSID unknown — capture at bring-up time)
- **Fallback**: Windows 11 Mobile Hotspot on Laptop A, subnet `192.168.137.x`
  - Laptop A (hotspot host): `192.168.137.1`
  - Pi (current DHCP lease on that fallback): `192.168.137.86`
- **Known previous lab IPs** (from doppelganger_poc, may drift):
  - Laptop A Windows: `35.0.22.235`
  - Pi: `35.0.18.34`, hostname `raspberrypiinocula`
- Ethernet on Laptop A is upstream-only — unplugging it does not kill the lab
  because Mobile Hotspot AP stays up when upstream drops.
- **Ports**:
  - Laptop A Sentinel UI + API: `8787`
  - Laptop B C2 UI + API: `8788`
  - Legacy victim listener (for STEALTH track compatibility): `18765`
  - Pi reports outbound only (no inbound port on Pi)
- **Auth**: shared secret in header `X-Inocula-Token` on every inter-node POST.
  Value stored in `.env` (gitignored), never in code.

## 5. Devices + targets

- **Paired BT devices used in demo** (NOT hardcoded anywhere — detection is via
  WinRT ConnectionStatus; these are just what we test against):
  - Samsers KM01-M (BLE mouse) — MAC `E2:6A:42:48:E8:52`
  - OnePlus Nord Buds 2 (classic BT) — MAC `F6:72:2D:D0:3C:19`
- Mouse has TWO paired entries in Windows due to BLE random address rotation —
  `_get_connected_bt_info` in `doppelganger/system_utils.py` dedupes by (name, mac).
- Pi hardware: Raspberry Pi 4B, hostname `raspberrypiinocula`.

## 6. OODA tuning defaults (carry over from doppelganger, known-good)

- Idle threshold: `10s`
- Cooldown between payload fires: `90s`
- OODA tick: `2s` (background loop in serve.py)
- Pi liveness window: `45s` (if no scan received in 45s, OODA is disabled)
- Payload latency target: `idle_threshold + tick + payload_setup` ≈ `~13s`

## 7. Hard rules (violating any of these = bug)

1. **No edits** to `ghostshield/`, `doppelganger/`, or `doppelganger_poc/`. They
   are read-only upstream references.
2. Only the name **Inocula** appears in any user-facing string, title, header,
   log message, or dashboard. Never "doppelganger", "ghostshield", "T-VIRUS",
   "80085", etc. in the final UI. (Internal variable names can keep their
   upstream names for traceability.)
3. **Jac-first**: every decision/orchestration step is a walker. Python only
   for adapters where Jac cannot reach the OS API.
4. **UI parity**: Inocula defense dashboard and Inocula attack dashboard both
   reuse ghostshield's `cl {}` React components and palette. No visual drift.
5. **No Bluetooth adventures.** Allowed BT operations on the Pi: passive BLE
   scan (bleak), classic BT probe (`l2ping`), BLE GATT read (BleakClient),
   one-shot MAC clone (`btmgmt public-addr`). **Disallowed**: BlueZ HID
   peripheral stack, custom GATT server, pairing manipulation, advertising as
   HID. If anything fights us, we drop it and keep only network trigger.
6. **Python restart rule**: Python caches modules at import. After any edit to
   `.py` files used by a running Jac/FastAPI server, kill and restart it.
7. **Every phase** ends with: tester run → scribe updates `TASKS_COMPLETED.md`
   → reviewer pass. No "done" without those three.
8. **Physical testing** (plugging in Pi, switching WiFi, running the actual
   payload on the victim) is done by the user, not by agents. Agents notify
   the user and pause.

## 8. Known upstream gotchas (do NOT re-learn these)

- Windows 11 Notepad uses multi-process (`ApplicationFrameHost` for calc,
  separate `notepad.exe` per file). Window-matching must use both exact title
  and `EnumWindows` substring matching.
- `SendInput` typing on Windows counts as user input → resets the OS idle
  counter. Back-to-back fires need another full idle threshold of no real input.
- BLE random address rotation creates duplicate paired entries for the same
  device. Dedupe by (name, mac).
- Notepad typing triggers Windows 11's "AI generated" warning → current attack
  writes a file and opens it with `notepad.exe <path>` instead of typing. Keep
  that pattern.
- PnP-based BT enumeration (`Get-PnpDevice`) is unreliable — use WinRT
  `GetDeviceSelectorFromPairingState($true)` + `FromIdAsync` + `ConnectionStatus`.
  This is already in `doppelganger/system_utils.py::_BT_WINRT_PS`.
- WinRT PowerShell invocation takes ~600ms → cache results for 2.5s so the 2s
  OODA tick doesn't respawn PS every tick (`_BT_CACHE_TTL`).
- PowerShell must be launched with `-EncodedCommand` in STA apartment.
- `_force_foreground` burns the process's one-shot focus-steal grant → notepad
  must open BEFORE calc in the payload sequence.

## 9. How Jac apps run (verified Phase 1, 2026-04-05)

- **Runtime**: `jaclang` 0.13.5. There is NO `jac-cloud` and NO `byllm` in the
  shared venv. **Ghostshield itself uses zero `by llm()` calls** — all 5 BT
  detectors are deterministic (see `ghostshield/abilities/__init__.jac` and
  `main.jac::calc_threat_score`). We do NOT need byllm for defense parity.
- **Boot command** (verified): from inside an app dir,
  `"C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/jac.exe" start main.jac --port <PORT>`
- **Walkers-as-REST**: any walker annotated `walker:pub` is auto-served at
  `POST http://localhost:<PORT>/walker/<walker_name>`. Walker `has` fields are
  auto-deserialized from the JSON request body. Walker `report {...}` statements
  are collected and returned as `{"ok": true, "data": {"reports": [...]}}`.
- **UI transpilation**: `cl { def:pub app -> JsxElement { ... } }` blocks are
  transpiled to React by `jac_client` and served from the same port. Inside a
  `cl {}` block, `result = root spawn my_walker()` becomes a `fetch()` POST to
  `/walker/my_walker` at runtime, returning parsed `response.data`.
- **Entry point**: `with entry { root spawn init_live(); }` at the bottom of
  `main.jac` runs once at module load. Used to seed the graph.
- **jac.toml port fields**: `[plugins.client.vite.server] port = 3000` is the
  Vite dev server, NOT the API server. Use CLI `--port` or add
  `[serve] api_port = <PORT>` in jac.toml. CLI flag wins.
- **LLM calls later** (Phase 3+): `by llm()` is lazy — app boots fine without
  byllm, only the walker/ability that calls `by llm()` fails at first call. We
  can add byllm + Anthropic API later without touching core defense code.

## 10. Open questions (deferred to later phases)

- [ ] Marcela's hotspot SSID + current Pi DHCP lease on it — captured at first
      cross-host bring-up (end of Phase 1 or start of Phase 5).
- [ ] Anthropic API key for byllm — only needed if/when we add `by llm()`
      classification in Phase 3+. Not a Phase 1 blocker.
- [ ] `X-Inocula-Token` value — generated and stored in `.env` at Phase 1.

## 11. Decision log (append-only)

- **2026-04-05** — Chose Option C (hybrid noisy+stealth) over A (defense-only
  extension) and B (BT-heavy attack). Rationale: keeps working network trigger
  as reliable demo fallback AND exercises GhostShield's existing BT detectors
  via one-shot MAC clone. No BlueZ HID peripheral work.
- **2026-04-05** — Laptop B is UI + orchestrator (not UI-only proxy).
  Rationale: otherwise it's just a browser tab; we want real walker-driven C2.
- **2026-04-05** — Froze `ghostshield/`, `doppelganger/`, `doppelganger_poc/`
  as read-only. All new code under `Inocula_Final/`.
- **2026-04-05** — Verified Jac runtime: use shared `.jac-venv` at
  `C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/`. Boot apps with
  `jac.exe start main.jac --port <N>`. No byllm, no jac-cloud required.
- **2026-04-05** — Confirmed ghostshield has ZERO `by llm()` calls. Defense
  parity (Phase 2) does NOT need an Anthropic API key. LLM classification is
  optional polish for Phase 3+.
