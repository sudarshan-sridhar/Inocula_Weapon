# Inocula Sentinel (Laptop A)

Defense posture monitor for the Inocula lab. Phase 1 is a boot-only
skeleton: the server starts, the dashboard renders, and every walker
returns stub data shaped per `../shared/protocol.md`. Real detectors
land in Phase 2.

## Run

```
cd C:\Users\sudar\inocula\Inocula_Final\sentinel
"C:/Users/sudar/OneDrive/Desktop/inocula/.jac-venv/Scripts/jac.exe" start main.jac --port 8787
```

- UI + walker API: `http://localhost:8787/`
- Boot banner: `=== Inocula Sentinel Ready ===`

## Walkers (all stubs in Phase 1)

| Walker | Purpose |
|---|---|
| `get_graph` | Full defense graph (device + peripherals + defense_phase) |
| `refresh_scan` | Trigger BT re-scan (Phase 2 will call adapters/win_bt.py) |
| `run_sentinel` | Run all BT/Network/Process detectors once |
| `victim_status` | Idle seconds, connected BT, defense_phase — called by C2 |
| `trigger_payload` | HID payload landing — STUB, refuses in Phase 1 |
| `configure` | Set armed / idle_threshold / cooldown |
| `reset_devices` | Reset demo state |
| `sentinel_alert_receive` | Reserved Sentinel→C2 echo endpoint |

## Layout

- `main.jac` — graph + walkers + `cl {}` dashboard
- `adapters/win_bt.py` — thin import wrapper around upstream
  `doppelganger/system_utils.py` (no code copied)
- `abilities/`, `graph/`, `sentinels/`, `response/`, `ui/` — reserved for
  Phase 2 modularization
