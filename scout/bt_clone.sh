#!/usr/bin/env bash
# Inocula Scout - MAC clone one-shot.
# Usage: sudo bt_clone.sh <target_mac>
# Exit:  0 = clone applied (or already in effect)
#        2 = not running as root
#        3 = bad argument
#        4 = btmgmt missing or failed
set -euo pipefail

LOG_PREFIX="[INOCULA SCOUT]"

die_json() {
    # $1 = exit code, $2 = error string
    local code="$1"
    local msg="$2"
    printf '{"ok":false,"error":%s,"ts":"%s"}\n' \
        "$(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$msg")" \
        "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
    exit "$code"
}

# --- 1. Arg check ---------------------------------------------------
if [ "$#" -ne 1 ]; then
    echo "$LOG_PREFIX usage: sudo $0 <target_mac>" >&2
    die_json 3 "usage: sudo bt_clone.sh <target_mac>"
fi

TARGET_MAC="$1"
if ! [[ "$TARGET_MAC" =~ ^[0-9A-Fa-f:]{17}$ ]]; then
    echo "$LOG_PREFIX bad mac: $TARGET_MAC" >&2
    die_json 3 "bad mac format"
fi
TARGET_MAC_UPPER="$(printf '%s' "$TARGET_MAC" | tr '[:lower:]' '[:upper:]')"

# --- 2. Root check --------------------------------------------------
if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "$LOG_PREFIX must be run as root" >&2
    die_json 2 "must be run as root"
fi

# --- 3. btmgmt available? -------------------------------------------
if ! command -v btmgmt >/dev/null 2>&1; then
    echo "$LOG_PREFIX btmgmt not found (install bluez-tools)" >&2
    die_json 4 "btmgmt not found"
fi

# --- 4. Read current controller address -----------------------------
# `btmgmt info` prints lines like: "	addr AA:BB:CC:DD:EE:FF version ..."
CURRENT_ADDR="$(btmgmt info 2>/dev/null \
    | grep -Eo 'addr[[:space:]]+[0-9A-Fa-f:]{17}' \
    | head -n1 \
    | awk '{print $2}' \
    | tr '[:lower:]' '[:upper:]' || true)"

if [ -z "${CURRENT_ADDR:-}" ]; then
    echo "$LOG_PREFIX could not read current controller address" >&2
    die_json 4 "btmgmt info unreadable"
fi

# --- 5. Idempotent short-circuit ------------------------------------
if [ "$CURRENT_ADDR" = "$TARGET_MAC_UPPER" ]; then
    TS="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
    printf '{"ok":true,"mac":"%s","previous":"%s","already_cloned":true,"ts":"%s"}\n' \
        "$TARGET_MAC_UPPER" "$CURRENT_ADDR" "$TS"
    echo "$LOG_PREFIX already cloned to $TARGET_MAC_UPPER" >&2
    exit 0
fi

# --- 6. Apply clone -------------------------------------------------
# Per bluez-tools: `btmgmt public-addr <mac>` stages the new public address;
# the change only takes effect after the controller is re-powered, which a
# bluetooth service restart handles cleanly.
if ! btmgmt public-addr "$TARGET_MAC_UPPER" >/dev/null 2>&1; then
    echo "$LOG_PREFIX btmgmt public-addr failed" >&2
    die_json 4 "btmgmt public-addr failed"
fi

# --- 7. Restart bluetooth so the new addr takes effect --------------
if command -v systemctl >/dev/null 2>&1; then
    systemctl restart bluetooth >/dev/null 2>&1 || true
elif [ -x /etc/init.d/bluetooth ]; then
    /etc/init.d/bluetooth restart >/dev/null 2>&1 || true
else
    echo "$LOG_PREFIX warning: no known init system to restart bluetoothd" >&2
fi

# --- 8. Structured stdout line for C2 log capture -------------------
TS="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
printf '{"ok":true,"mac":"%s","previous":"%s","ts":"%s"}\n' \
    "$TARGET_MAC_UPPER" "$CURRENT_ADDR" "$TS"
echo "$LOG_PREFIX cloned $CURRENT_ADDR -> $TARGET_MAC_UPPER" >&2
exit 0
