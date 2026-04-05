# Inocula C2 — Laptop B

Attacker control plane for the Inocula lab. Pure Jac orchestrator + operator
console UI, served together from a single Jac process.

**Phase 1 scope**: empty skeleton. All walkers mutate the in-memory C2 graph
and append event-log entries, but **no real Scout/Sentinel traffic is made**.
The `tracks/` files are stubs — real orchestration lands in Phase 4.

## Boot

```
cd C:\Users\sudar\inocula\Inocula_Final\c2
"C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/jac.exe" start main.jac --port 8788
```

- API base:  `http://localhost:8788/walker/<walker_name>`
- UI:        `http://localhost:8788/app`

## Walkers

All walkers are `walker:pub`, so they're auto-served at `POST /walker/<name>`
with a JSON body that matches the walker's `has` fields.

| Walker            | Purpose                                                            |
|-------------------|--------------------------------------------------------------------|
| `get_c2_state`    | Full dashboard snapshot (operator_id, OODA phase, target, scouts, victims, event_log[-50]). |
| `report_scan`     | Scout → C2 ingest (see `shared/protocol.md` §1). Find-or-creates a PiNode per `pi_ip`, updates last-scan, selects a target from `devices`, transitions OODA phase, returns `{devices_received, c2_phase, target, next_poll_seconds}`. |
| `run_operation`   | Operator pressed "RUN OPERATION". Validates `track in {stealth,noisy,both}`, sets `current_track`, arms the C2, appends event. Phase 1: does **NOT** actually fire — Phase 4 will call `tracks/track_*.jac`. |
| `abort_operation` | Kill switch. Sets `armed=False`, `auto=False`, appends event.       |
| `configure`       | Set `target_mac`, `target_name`, `current_track`, `cooldown_seconds`, `rssi_min_trigger`, `idle_required`. Each field uses a sentinel default so callers can update any subset. |
| `sentinel_alert`  | Sentinel → C2 webhook (see `shared/protocol.md` §4). Appends a `sentinel_alert` entry with `{sentinel, severity, summary, signals, at_utc}` to the event log. |

## Graph schema

```
root
  └── C2Node (operator_id, ooda_phase, current_track, armed, auto,
              target_mac, target_name, target_rssi, last_scan_utc,
              last_scan_device_count, trigger_count, last_trigger_utc,
              cooldown_seconds, event_log[<=200], rssi_min_trigger,
              idle_required)
       ├── ScoutEdge ──▶ PiNode(pi_id, last_seen_utc, last_ip, scan_count, alive)
       │                 (one per unique pi_ip seen via report_scan)
       └── TargetEdge ─▶ VictimNode(victim_id, sentinel_url, last_status_utc,
                                    idle_seconds, defense_phase,
                                    connected_device_count)
                         (seeded empty; populated from Sentinel status
                          polling in Phase 4)
```

## OODA state machine (Phase 1 simplified)

`report_scan` recomputes the phase on every ingest:

| Condition                                               | `ooda_phase` |
|---------------------------------------------------------|--------------|
| no target selected                                      | `observe`    |
| target selected, `armed=False`                          | `orient`     |
| target selected, `armed=True`, `trigger_count == 0`     | `decide`     |
| target selected, `armed=True`, `trigger_count > 0`      | `act`        |

Target selection (inside `report_scan`): walk `devices`, keep the highest-RSSI
entry whose `rssi >= rssi_min_trigger` (default `-55` dBm) and whose `name`
contains `mouse`, `keyboard`, or `buds` (case-insensitive). Real OODA tuning
(idle-gating, cooldown, auto-fire) is Phase 4.

## UI

`cl { def:pub app }` in `main.jac` serves the operator console at `/app`. It
polls `get_c2_state` every 2s. The aesthetic mirrors the Inocula Sentinel
dashboard (shared SOC-terminal palette). Only the name **Inocula** appears in
user-visible strings.

## Environment

Phase 1 runs with defaults and does not read `.env`. Phase 4 will read:

```
INOCULA_TOKEN=<shared_secret>
INOCULA_C2_HOST=0.0.0.0
INOCULA_C2_PORT=8788
INOCULA_SENTINEL_URL=http://<laptop_a_ip>:8787
INOCULA_PI_SSH_HOST=inocula@<pi_ip>
INOCULA_DEFAULT_TRACK=stealth
```

See `shared/auth.md` for the `X-Inocula-Token` header convention and
`.env` layout.

## Phase 4 bring-up plan (not yet implemented)

1. `tracks/track_stealth.jac` — POST to Sentinel `/walker/trigger_payload`
   with `X-Inocula-Token`. Sentinel runs the HID payload on itself.
2. `tracks/track_noisy.jac` — SSH to Pi, run `bt_clone.sh`, then chain into
   stealth as the impact phase.
3. Wire `run_operation` to call `fire_stealth` / `fire_noisy` instead of
   returning a stub response.
4. Add a 2s OODA tick walker that re-evaluates `decide → act` based on idle
   + cooldown (mirror `doppelganger/serve.py::ooda_tick`).
