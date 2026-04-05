# Inocula — Inter-Node HTTP Protocol

All walker-as-REST calls between Sentinel (Laptop A), C2 (Laptop B), and
Scout (Pi) use this contract. Freeze any changes here with a decision-log
entry in `memory.md`.

Transport: plain HTTP over LAN (no TLS — lab only).
Serialization: JSON, UTF-8.
Auth: `X-Inocula-Token: <shared_secret>` header on every request. See `auth.md`.
Response envelope (Jac default): `{"ok": true, "data": {"reports": [ ... ]}}`.
On walker-side failure: `{"ok": false, "error": "<message>"}`.

---

## Nodes and ports (verified defaults)

| Node     | Host             | Port  | Base URL                       |
|----------|------------------|-------|--------------------------------|
| Sentinel | Laptop A         | 8787  | `http://<laptop_a>:8787`       |
| C2       | Laptop B         | 8788  | `http://<laptop_b>:8788`       |
| Scout    | Raspberry Pi     | —     | outbound only, no inbound port |

`<laptop_a>` / `<laptop_b>` are discovered per-session and cached in `.env`.
Scout uses `INOCULA_C2_URL` env var; Sentinel uses `INOCULA_C2_URL` too (for
reverse-status pings during integration testing).

---

## 1. Scout → C2

### `POST /walker/report_scan` (C2)

Scout posts its BLE+classic-BT scan snapshot to C2. C2 evaluates its OODA
chain and may decide to fire a track.

**Headers:** `X-Inocula-Token`, `Content-Type: application/json`

**Request body**:
```json
{
  "pi_ip": "192.168.137.86",
  "scan_updated_utc": "2026-04-05T11:32:18.471Z",
  "rssi_min_dbm": -75,
  "scan_duration_s": 8,
  "devices": [
    {
      "mac": "E2:6A:42:48:E8:52",
      "name": "Samsers KM01-M",
      "rssi": -48,
      "addr_type": "ble",
      "adv_flags": 6,
      "tx_power": 0,
      "observed_count": 12,
      "last_seen_utc": "2026-04-05T11:32:17.902Z"
    }
  ],
  "classic": [
    { "mac": "F6:72:2D:D0:3C:19", "name": "OnePlus Nord Buds 2", "l2ping_ok": true }
  ]
}
```

**Response**:
```json
{
  "ok": true,
  "data": {
    "reports": [{
      "devices_received": 1,
      "c2_phase": "orient",
      "target": { "name": "Samsers KM01-M", "mac": "E2:6A:42:48:E8:52", "reason": "rssi close" },
      "next_poll_seconds": 10
    }]
  }
}
```

`c2_phase` is one of: `observe`, `orient`, `decide`, `act`.
Scout honors `next_poll_seconds` for its next scan interval.

---

## 2. C2 → Sentinel

### `POST /walker/victim_status` (Sentinel)

C2 polls Sentinel for victim idle time, connected BT devices, and current
defense posture. Used during `decide` to confirm target is real and user is idle.

**Headers:** `X-Inocula-Token`, `Content-Type: application/json`

**Request body**: `{}`

**Response**:
```json
{
  "ok": true,
  "data": {
    "reports": [{
      "device_id": "laptop-a-sudar",
      "os_type": "windows",
      "idle_seconds": 14.7,
      "idle_threshold": 10.0,
      "connected_bt_devices": [
        { "name": "Samsers KM01-M", "mac": "E2:6A:42:48:E8:52", "addr_type": "ble" }
      ],
      "defense_phase": "monitoring",
      "sentinel_alerts_last_30s": 0,
      "now_utc": "2026-04-05T11:32:19.001Z"
    }]
  }
}
```

`defense_phase` is one of: `monitoring`, `alerting`, `remediating`, `locked`.

### `POST /walker/trigger_payload` (Sentinel)

**STEALTH track only.** C2 tells Sentinel to run the HID payload on itself.
Sentinel respects its own cooldown and armed state. This is equivalent to
doppelganger's legacy `/trigger` path, but gated by `X-Inocula-Token` and
reachable only from Laptop B's IP (whitelisted in Sentinel config).

**Request body**:
```json
{ "force": false, "origin": "c2_stealth", "operation_id": "op_20260405_113218" }
```

**Response**:
```json
{
  "ok": true,
  "data": {
    "reports": [{
      "fired": true,
      "payload": "calc+notepad",
      "fired_at_utc": "2026-04-05T11:32:20.512Z",
      "cooldown_remaining_s": 90
    }]
  }
}
```

On cooldown: `{"fired": false, "reason": "cooldown", "cooldown_remaining_s": 42}`.
On not-armed: `{"fired": false, "reason": "not_armed"}`.

---

## 3. C2 → Scout (via SSH, not HTTP)

Scout has no inbound port. The **noisy track** runs `bt_clone.sh` on the Pi
over SSH from C2. No JSON contract — it's a subprocess call.

Command shape (executed by `c2/tracks/track_noisy.jac`):

```bash
ssh -o StrictHostKeyChecking=accept-new inocula@<pi_host> \
    'sudo /home/inocula/Inocula_Final/scout/bt_clone.sh <target_mac>'
```

Exit code 0 = clone registered. Non-zero = failure; C2 falls back to stealth
track automatically (configurable).

---

## 4. Sentinel → C2 (status webhook, optional)

### `POST /walker/sentinel_alert` (C2)

When Sentinel's NetworkSentinel or ProcessSentinel fires a HIGH-severity
alert, it notifies C2 so the attack dashboard can reflect reality. Optional —
if C2 is unreachable, Sentinel logs locally and continues.

**Headers:** `X-Inocula-Token`

**Request body**:
```json
{
  "sentinel": "process",
  "severity": "HIGH",
  "summary": "calc+notepad co-spawn during 15s idle — matches Inocula stealth payload",
  "signals": ["proc.calc_spawn", "proc.notepad_spawn", "idle.over_threshold"],
  "at_utc": "2026-04-05T11:32:20.902Z"
}
```

**Response**: `{"ok": true, "data": {"reports": [{"ack": true}]}}`

---

## 5. All walkers (by node)

### Sentinel (Laptop A, port 8787)
| Walker | Purpose | Callers |
|---|---|---|
| `get_graph` | Full defense graph + UI state | Sentinel UI |
| `refresh_scan` | Trigger BT re-scan + RSSI refresh | Sentinel UI |
| `run_sentinel` | Run all 5 BT detectors + network + process sentinels once | Sentinel UI, self-tick |
| `victim_status` | Idle + connected BT + defense phase | C2 |
| `trigger_payload` | Fire HID payload (stealth track landing) | C2 only (IP-whitelisted) |
| `configure` | Set armed / idle threshold / cooldown | Sentinel UI |
| `reset_devices` | Reset demo state | Sentinel UI |

### C2 (Laptop B, port 8788)
| Walker | Purpose | Callers |
|---|---|---|
| `get_c2_state` | Full attack dashboard state | C2 UI |
| `report_scan` | Scout posts BLE scan, triggers OODA | Scout |
| `run_operation` | Start a new attack operation (track selector) | C2 UI |
| `abort_operation` | Kill switch | C2 UI |
| `sentinel_alert` | Receive sentinel alerts for live correlation | Sentinel |
| `configure` | Set target, track, cooldown | C2 UI |

### Scout (Pi)
No walkers — it is a client, not a server. Runs `scout/pi_agent.py` which POSTs
to C2.

---

## 6. Error semantics

- All errors return `{"ok": false, "error": "<human_readable>", "code": "<machine_code>"}`.
- Codes: `auth_missing`, `auth_bad`, `rate_limit`, `cooldown`, `not_armed`,
  `peer_unreachable`, `validation_error`, `internal`.
- Callers retry on `peer_unreachable` up to 3x with 2s backoff. All other
  errors are terminal.

## 7. Timeouts

| From → To  | Connect | Read | Total |
|---|---|---|---|
| Scout → C2 | 3s      | 10s  | 15s   |
| C2 → Sentinel | 3s   | 5s   | 8s    |
| Sentinel → C2 | 3s   | 3s   | 6s    |

## 8. Versioning

This protocol is v1. Every request may include `"protocol_version": 1` in its
body for forward compatibility. Nodes must accept requests without this field
and assume v1.
