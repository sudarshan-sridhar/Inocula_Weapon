# Inocula Scout (Raspberry Pi)

## Overview

Scout is the Pi-side sensor in the Inocula 3-machine lab (Sentinel on Laptop A,
C2 on Laptop B, Scout on the Pi). It passively scans nearby BLE peripherals
and paired classic-BT devices around the victim, then POSTs each snapshot to
C2's `report_scan` walker. The operator uses the dashboard on Laptop B to pick
a target from those reports. On demand, C2 SSHes into the Pi and runs
`bt_clone.sh` to trip the Sentinel's duplicate-MAC detector (the "noisy"
track). Scout is a pure outbound client - it never opens a listening port.

## Hardware

- Raspberry Pi 4B (3B+ also works), Bluetooth 5 controller
- Debian / Raspberry Pi OS Bookworm (64-bit), Python 3.10+
- A user named `inocula` on the Pi (adjust paths below if yours differs)

## One-time install

On the Pi:

```bash
sudo apt update
sudo apt install -y bluez bluez-tools python3-venv python3-pip
cd /home/inocula/Inocula_Final/scout
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create the env file at `~/.config/inocula/.env` (matches the `EnvironmentFile=`
in the systemd unit below):

```bash
mkdir -p ~/.config/inocula
install -m 0600 /dev/null ~/.config/inocula/.env
```

Then fill it in - values come from Laptop A's one-time secret generator and
from Laptop B's network address:

```
INOCULA_TOKEN=<64-hex-char shared secret>
INOCULA_C2_URL=http://<laptop_b_ip>:8788
INOCULA_SCAN_INTERVAL=10
INOCULA_RSSI_MIN=-75
INOCULA_SCAN_DURATION=8
```

`pi_agent.py` reads these directly from the process environment - no
`python-dotenv` dependency. The systemd unit below injects them via
`EnvironmentFile=`.

Mark the MAC-clone script executable:

```bash
chmod +x /home/inocula/Inocula_Final/scout/bt_clone.sh
```

## Dry run

Run one scan, print the POST body as JSON, exit. Does not need a token and
does not hit the network - useful for verifying BLE works on the Pi before
bringing up C2:

```bash
source .venv/bin/activate
python pi_agent.py --dry-run --once
```

You should see a JSON object with `pi_ip`, `scan_updated_utc`, `devices[]`,
and `classic[]`. If the devices list is empty, re-run while a Bluetooth
peripheral is nearby and advertising.

## Live run (foreground)

Export the env (or source it) and run:

```bash
set -a; source ~/.config/inocula/.env; set +a
python pi_agent.py
```

One-shot mode is handy for integration tests - one scan, one POST, exit:

```bash
python pi_agent.py --once
```

All CLI flags override env vars:

| Flag         | Env                     | Default  |
|--------------|-------------------------|----------|
| `--c2-url`   | `INOCULA_C2_URL`        | required |
| `--token`    | `INOCULA_TOKEN`         | required |
| `--interval` | `INOCULA_SCAN_INTERVAL` | `10`     |
| `--dry-run`  | -                       | off      |
| `--once`     | -                       | off      |

Other env-only config: `INOCULA_RSSI_MIN` (default `-75`),
`INOCULA_SCAN_DURATION` (default `8`), `INOCULA_PI_ID` (default hostname).

## Behaviour notes

- **Adaptive polling.** If C2 returns `data.reports[0].next_poll_seconds`,
  Scout uses it as the next sleep interval. Otherwise it uses
  `INOCULA_SCAN_INTERVAL`.
- **Backoff.** On `ConnectionError` / timeout / HTTP non-200, Scout doubles
  its interval (capped at 60s) until C2 replies again.
- **Exception safety.** A crashed scan cycle is logged and the loop continues.
  One bad cycle will not take the daemon down.
- **Clean shutdown.** SIGINT / SIGTERM set a flag that breaks the sleep loop
  and stops the bleak scanner. The process exits 0.
- **Token safety.** The token is never logged in full - only its first 6
  chars + `...`, matching `shared/auth.md` §6.

## Systemd user service

Drop this into `~/.config/systemd/user/inocula-scout.service`:

```ini
[Unit]
Description=Inocula Scout - BLE sensor posting to C2
After=network-online.target bluetooth.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/Inocula_Final/scout
EnvironmentFile=%h/.config/inocula/.env
ExecStart=%h/Inocula_Final/scout/.venv/bin/python %h/Inocula_Final/scout/pi_agent.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Enable, start, and tail logs:

```bash
systemctl --user daemon-reload
systemctl --user enable --now inocula-scout
journalctl --user -u inocula-scout -f
```

If `systemctl --user` complains about DBus at login, run
`loginctl enable-linger inocula` so user services start at boot without a
login session.

If your BlueZ build insists on `CAP_NET_RAW` for passive scans, you can either
run the unit as a system service under `/etc/systemd/system/` with
`User=inocula`, or grant caps to the venv Python:

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' \
    /home/inocula/Inocula_Final/scout/.venv/bin/python3.*
```

## bt_clone.sh deployment

The noisy track fires when C2 runs `bt_clone.sh` over SSH to clone the
victim's Bluetooth MAC onto the Pi's controller, tripping the Sentinel's
duplicate-MAC detector. Install it at
`/home/inocula/Inocula_Final/scout/bt_clone.sh`, make it executable, and
give the `inocula` user a targeted password-less sudo line so C2 can invoke
it unattended. Add this to `/etc/sudoers.d/inocula-scout` (use `visudo -f`):

```
inocula ALL=(root) NOPASSWD: /home/inocula/Inocula_Final/scout/bt_clone.sh
```

Test it locally first:

```bash
sudo /home/inocula/Inocula_Final/scout/bt_clone.sh AA:BB:CC:DD:EE:FF
```

The script prints a single JSON line to stdout on success, for example:

```json
{"ok":true,"mac":"AA:BB:CC:DD:EE:FF","previous":"DC:A6:32:...","ts":"..."}
```

It is idempotent: if the controller address already matches the target, it
exits 0 with `"already_cloned":true`. Exit codes: `0` = applied / no-op,
`2` = not root, `3` = bad argument, `4` = btmgmt missing or failed.

## Troubleshooting

**`bleak.exc.BleakError: org.bluez.Error.NotReady`**
BlueZ is up but the adapter is soft-blocked. Run
`rfkill unblock bluetooth && sudo systemctl restart bluetooth`.

**`Permission denied (publickey)` when C2 SSHes in**
Copy Laptop B's public key to `~inocula/.ssh/authorized_keys` on the Pi
with mode `600`. Verify with `ssh -v inocula@<pi_ip> true` from Laptop B.

**`Operation not permitted` from bleak**
The venv Python lacks raw HCI caps. Use `setcap` as shown in the systemd
section, or run Scout as a system service.

**`bluetoothd` not running**
`sudo systemctl status bluetooth` - if dead, `sudo systemctl enable --now
bluetooth`. The dbus service must be up before Scout starts (the unit's
`After=bluetooth.target` handles this on normal boots).

**C2 unreachable**
From the Pi, confirm the URL is dialable:
`curl -sS -H "X-Inocula-Token: $INOCULA_TOKEN" $INOCULA_C2_URL/walker/get_c2_state`.
If that fails with "connection refused" the C2 process isn't up; if it fails
with `auth_bad` / `auth_missing` the token in `.env` does not match Laptop B.

**Token mismatch**
Regenerate the secret on Laptop A with
`python -c "import secrets; print(secrets.token_hex(32))"`, paste it into
`.env` on all three hosts, and restart each service.

**Nothing in `devices[]`**
Run `bluetoothctl scan on` in another shell - if you see no peripherals
there either, the issue is the radio, not Scout. Check `dmesg | grep -i
bluetooth` for firmware load failures on Pi 4B.
