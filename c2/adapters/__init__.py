"""Inocula C2 — Python adapter layer.

Phase 4 brings real orchestration: HTTP POSTs into the Sentinel and
SSH-dispatched shell calls to the Pi Scout. These live in Python so
the Jac walkers stay tiny and declarative, and so we can unit-test
the risky parts (subprocess, network) without booting a walker.
"""
