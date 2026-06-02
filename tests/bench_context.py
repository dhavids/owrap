#!/usr/bin/env python3
"""Benchmark context injection: compare orun --msg wall time with context_enabled=true vs false.

Requires an active owrap session (owrap start must have been run).
Run: python3 owrap/tests/bench_context.py
"""
import json
import subprocess
import time
from pathlib import Path

CONFIG = Path("/home/humble/marl/owrap/configs/owrap.json")
ORUN = Path("/home/humble/bin/orun")

# Fixed repeatable task — short enough to finish quickly, non-trivial enough to need context
TASK = (
    "List the 3 most important Python source files in "
    "/home/humble/marl/owrap/owrap/ by role. One sentence per file. No preamble."
)


def set_context_enabled(val: bool):
    data = json.loads(CONFIG.read_text())
    data["context_enabled"] = val
    CONFIG.write_text(json.dumps(data, indent=2) + "\n")


def run_once(label: str) -> float:
    print(f"\n{'─' * 52}", flush=True)
    print(f"  context_enabled = {label}", flush=True)
    print(f"{'─' * 52}", flush=True)
    t0 = time.monotonic()
    result = subprocess.run([str(ORUN), "--msg", TASK], text=True)
    elapsed = time.monotonic() - t0
    print(f"\n[bench] wall={elapsed:.1f}s  rc={result.returncode}", flush=True)
    return elapsed


original = json.loads(CONFIG.read_text()).get("context_enabled", True)
try:
    set_context_enabled(False)
    t_off = run_once("false  (no context injected)")
    set_context_enabled(True)
    t_on = run_once("true   (context injected as first instruction)")
finally:
    set_context_enabled(original)

print(f"\n{'=' * 52}")
print("  BENCHMARK RESULTS")
print(f"{'=' * 52}")
print(f"  context=off : {t_off:6.1f}s")
print(f"  context=on  : {t_on:6.1f}s")
delta = t_on - t_off
sign = "+" if delta >= 0 else ""
if abs(delta) <= 2:
    note = "within noise"
elif delta > 0:
    note = f"context adds ~{delta:.0f}s overhead"
else:
    note = f"context saves ~{abs(delta):.0f}s"
print(f"  delta       : {sign}{delta:.1f}s  ({note})")
print(f"{'=' * 52}")
