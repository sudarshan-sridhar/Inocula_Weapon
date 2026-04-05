"""Inocula Sentinel — attack classification adapter.

Produces an `AttackClassification` dict from a features dict. Two
backends:

1. **LLM backend** (preferred): used when `ANTHROPIC_API_KEY` is set in
   the environment. Shells out to the `litellm` client that `byllm`
   already pulled into the shared venv, so there's no extra dep.
2. **Rule-based fallback**: pure-Python scoring. Used when no key is
   present or the LLM call fails. The walker is unaware of which
   backend answered — both return the same dict shape.

Shape of AttackClassification dict:

```
{
    "kind": "STEALTH_NETWORK" | "STEALTH_PROCESS" | "NOISY_BT"
            | "BENIGN" | "UNKNOWN",
    "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
    "confidence": float 0..1,
    "indicators": list[str],
    "recommended_actions": list[str],   # sentinel-runnable tokens
    "summary": str,                      # human-readable, <= 200 chars
    "backend": "llm" | "rules",
    "elapsed_ms": float,
}
```

`recommended_actions` is a tokenised list the walker can dispatch to
kill_listener.py — e.g. `"kill_listener:8787"`, `"block_ip:192.168.1.42"`,
`"kill_process:notepad.exe"`, `"quarantine_device:<mac>"`. The walker
does the actual dispatch; the classifier only advises.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

_DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
_SYSTEM_PROMPT = """You are the Inocula Sentinel attack classifier.
You receive a JSON features object describing suspicious activity on a
Windows victim host that is part of a 3-machine security lab. Classify
the activity and return ONLY a JSON object with these keys:
  kind: one of STEALTH_NETWORK, STEALTH_PROCESS, NOISY_BT, BENIGN, UNKNOWN
  severity: one of CRITICAL, HIGH, MEDIUM, LOW, INFO
  confidence: float between 0 and 1
  indicators: array of short strings naming the specific signals
  recommended_actions: array of tokens from {kill_listener:<port>,
    block_ip:<ip>, kill_process:<name>, quarantine_device:<mac>, none}
  summary: short human sentence, max 200 chars.

Rules:
- STEALTH_NETWORK if an unexpected inbound POST or a new local listener
  is present on a control port.
- STEALTH_PROCESS if interactive apps (calc/notepad/cmd) spawned while
  the user was idle above the threshold.
- NOISY_BT if a duplicate BT identity or HID profile mismatch is reported.
- BENIGN if indicators are empty or all-clean.
Return ONLY valid JSON, no prose."""

# What an empty/unknown result looks like. Used as the floor for
# merging partial outputs.
_EMPTY: dict[str, Any] = {
    "kind": "UNKNOWN",
    "severity": "INFO",
    "confidence": 0.0,
    "indicators": [],
    "recommended_actions": ["none"],
    "summary": "",
    "backend": "rules",
    "elapsed_ms": 0.0,
}


def _rule_based(features: dict) -> dict:
    """Deterministic classifier. Mirrors the LLM prompt logic."""
    ind: list[str] = []
    actions: list[str] = []
    kind = "BENIGN"
    severity = "INFO"
    confidence = 0.4
    summary_bits: list[str] = []

    # Network-plane signals
    rogue_post = features.get("rogue_post")
    if isinstance(rogue_post, dict) and rogue_post.get("source_ip"):
        ip = rogue_post["source_ip"]
        ind.append(f"unauthorized POST from {ip}")
        actions.append(f"block_ip:{ip}")
        kind = "STEALTH_NETWORK"
        severity = "CRITICAL"
        confidence = max(confidence, 0.9)
        summary_bits.append(f"rogue inbound POST from {ip}")

    new_listeners = features.get("new_listeners") or []
    for lst in new_listeners:
        port = lst.get("port")
        proc = lst.get("process", "")
        if port in (18765, 8787, 8788):
            ind.append(f"unexpected listener on :{port} ({proc})")
            actions.append(f"kill_listener:{port}")
            kind = "STEALTH_NETWORK"
            severity = "CRITICAL"
            confidence = max(confidence, 0.85)
            summary_bits.append(f"new listener on :{port}")

    unexpected_peers = features.get("unexpected_peers") or []
    for peer in unexpected_peers:
        ip = peer.get("remote_ip", "")
        if ip:
            ind.append(f"unexpected LAN peer {ip}")
            summary_bits.append(f"unexpected peer {ip}")
            if severity not in ("CRITICAL", "HIGH"):
                kind = "STEALTH_NETWORK"
                severity = "HIGH"
                confidence = max(confidence, 0.7)
            elif severity == "HIGH" and kind == "BENIGN":
                kind = "STEALTH_NETWORK"

    # Process-plane signals
    idle_cohort = features.get("idle_cohort") or []
    if idle_cohort:
        names = sorted({e.get("name", "") for e in idle_cohort if e.get("name")})
        for e in idle_cohort:
            if e.get("name"):
                actions.append(f"kill_process:{e['name']}")
        ind.append(f"interactive cohort spawned while idle: {','.join(names)}")
        if kind == "BENIGN":
            kind = "STEALTH_PROCESS"
        elif kind == "STEALTH_NETWORK":
            # Both planes → this is the full hybrid attack
            kind = "STEALTH_NETWORK"  # keep network since action set is the same
        severity = "CRITICAL"
        confidence = max(confidence, 0.9)
        summary_bits.append(f"idle-spawn cohort: {','.join(names)}")

    sendinput_burst = features.get("sendinput_burst")
    if isinstance(sendinput_burst, dict) and sendinput_burst.get("burst_keys"):
        ind.append(
            f"SendInput burst: {sendinput_burst['burst_keys']} keys"
            f" @ {sendinput_burst.get('last_ts', '?')}"
        )
        kind = "STEALTH_PROCESS" if kind == "BENIGN" else kind
        severity = "CRITICAL"
        confidence = max(confidence, 0.95)
        summary_bits.append("SendInput burst marker fresh")

    # BT-plane signals (for hybrid scenarios)
    bt_alerts = features.get("bt_alerts") or []
    for a in bt_alerts:
        if a.get("severity") == "CRITICAL":
            mac = a.get("mac", "")
            ind.append(f"BT: {a.get('message', '')}")
            if mac:
                actions.append(f"quarantine_device:{mac}")
            if kind == "BENIGN":
                kind = "NOISY_BT"
                severity = "CRITICAL"
                confidence = max(confidence, 0.85)

    if not ind:
        kind = "BENIGN"
        severity = "INFO"
        confidence = 0.6
        summary_bits.append("no suspicious indicators")
        actions = ["none"]

    # Dedup actions while preserving order
    seen: set[str] = set()
    uniq_actions: list[str] = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            uniq_actions.append(a)

    summary = "; ".join(summary_bits)[:200] or "no indicators"
    return {
        "kind": kind,
        "severity": severity,
        "confidence": round(confidence, 2),
        "indicators": ind,
        "recommended_actions": uniq_actions or ["none"],
        "summary": summary,
        "backend": "rules",
        "elapsed_ms": 0.0,
    }


def _llm_based(features: dict, model: str, timeout: float) -> dict | None:
    """Try an LLM call via litellm (already in the shared venv via byllm)."""
    try:
        import litellm  # type: ignore
    except Exception:
        return None
    start = time.time()
    try:
        resp = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(features, default=str)},
            ],
            temperature=0.2,
            max_tokens=512,
            timeout=timeout,
        )
        content = resp["choices"][0]["message"]["content"].strip()
        # Strip accidental ``` fences
        if content.startswith("```"):
            content = content.strip("`")
            # drop leading "json" tag if present
            if content.lower().startswith("json"):
                content = content[4:]
            content = content.strip()
        parsed = json.loads(content)
        # Merge over empty template so missing keys default sanely.
        out = dict(_EMPTY)
        out.update({k: v for k, v in parsed.items() if k in _EMPTY or k == "kind"})
        out["backend"] = "llm"
        out["elapsed_ms"] = round((time.time() - start) * 1000.0, 1)
        # Coerce types defensively
        out["confidence"] = float(out.get("confidence", 0.0) or 0.0)
        out["indicators"] = list(out.get("indicators") or [])
        out["recommended_actions"] = list(out.get("recommended_actions") or ["none"])
        out["summary"] = str(out.get("summary", ""))[:200]
        return out
    except Exception:
        return None


def classify(features: dict, *, timeout: float = 8.0) -> dict:
    """Classify the feature set.

    Prefers LLM when ANTHROPIC_API_KEY is set; otherwise rules.
    Always returns a full AttackClassification dict — never raises.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        model_name = os.getenv("INOCULA_LLM_MODEL", _DEFAULT_MODEL)
        llm_result = _llm_based(features, model=model_name, timeout=timeout)
        if llm_result is not None:
            return llm_result
    # Fallback (no key, or LLM failed)
    return _rule_based(features)


def adapter_healthcheck() -> dict:
    has_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    litellm_ok = False
    try:
        import litellm  # type: ignore  # noqa: F401
        litellm_ok = True
    except Exception:
        litellm_ok = False
    return {
        "llm_ready": has_key and litellm_ok,
        "has_key": has_key,
        "litellm_ok": litellm_ok,
        "rules_always_available": True,
        "default_model": _DEFAULT_MODEL,
    }
