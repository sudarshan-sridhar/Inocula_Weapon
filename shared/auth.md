# Inocula — Auth & Secrets

Lab-only auth. Not production. Just enough to stop casual LAN neighbors from
poking the walker endpoints.

---

## 1. Header

Every inter-node HTTP request carries:

```
X-Inocula-Token: <64-hex-char shared secret>
```

Missing header → `403 {"ok": false, "error": "auth_missing", "code": "auth_missing"}`
Wrong value   → `403 {"ok": false, "error": "auth_bad",     "code": "auth_bad"}`

UI requests from `cl {}` components running on the same host do NOT need the
header — they hit `localhost` which is exempted. Only **remote** LAN requests
are checked.

## 2. Secret generation

Generate once, at Phase 1 bring-up, on Laptop A:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the value into `.env` files on all three hosts (see §3). Rotate by
regenerating and redistributing — there's no key negotiation.

## 3. `.env` file layout

Every host gets its own `.env` in its app dir. `.env` is gitignored.

### Laptop A — `Inocula_Final/sentinel/.env`
```
INOCULA_TOKEN=<shared_secret>
INOCULA_SENTINEL_HOST=0.0.0.0
INOCULA_SENTINEL_PORT=8787
INOCULA_C2_URL=http://<laptop_b_ip>:8788
INOCULA_ALLOW_REMOTE_TRIGGER_FROM=<laptop_b_ip>
INOCULA_IDLE_THRESHOLD=10
INOCULA_COOLDOWN=90
```

### Laptop B — `Inocula_Final/c2/.env`
```
INOCULA_TOKEN=<shared_secret>
INOCULA_C2_HOST=0.0.0.0
INOCULA_C2_PORT=8788
INOCULA_SENTINEL_URL=http://<laptop_a_ip>:8787
INOCULA_PI_SSH_HOST=inocula@<pi_ip>
INOCULA_DEFAULT_TRACK=stealth
```

### Pi — `Inocula_Final/scout/.env`
```
INOCULA_TOKEN=<shared_secret>
INOCULA_C2_URL=http://<laptop_b_ip>:8788
INOCULA_SCAN_INTERVAL=10
INOCULA_RSSI_MIN=-75
INOCULA_SCAN_DURATION=8
```

Loaded via `python-dotenv` on Python code paths and via Jac `env` reads on
`.jac` code paths.

## 4. IP whitelist on Sentinel

`POST /walker/trigger_payload` is the only walker that actually fires the HID
payload remotely. It MUST reject any caller whose source IP is not equal to
`INOCULA_ALLOW_REMOTE_TRIGGER_FROM`, even if the token is valid. This gives us
two independent gates (token + source IP) for the one risky endpoint.

All other walkers check token only.

## 5. TLS / signing

Not in scope. This is a lab on a trusted LAN. If the lab moves to an untrusted
network, add a reverse proxy with TLS termination at each host; the walker
contract doesn't change.

## 6. Secret handling rules

- Never commit `.env` files.
- Never print the token in logs. Log the token's first 6 chars + "..." at most,
  and only at debug level.
- Never pass the token via query string. Header only.
- Regenerate if leaked. No revocation list.
