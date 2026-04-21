"""Parity regression scaffold for Ruusan ch01 sc01.

Slice 1 guards against inadvertent prose drift when runtime flags are OFF.
The baseline at ``tests/baselines/ruusan_ch01_sc01.md`` was captured before
Slice 1 landed; a live flag-off pipeline run should produce byte-identical
output because every new code path is gated.

The full pipeline is too expensive to run in ``pytest -q``. Instead, this
test opts in to live comparison only when ``PARITY_RUN_PATH`` is set to the
chapter file produced by a fresh flag-off run (e.g. via
``bench_prose_models.py``). CI / pre-flag-flip flows set this explicitly;
normal unit runs just validate the baseline is present and readable.

See ``docs/architecture/architecture_upgrade_spec.md`` §11.6.3–§11.6.4.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


BASELINE = Path(__file__).parent / "baselines" / "ruusan_ch01_sc01.md"

PARITY_ENV_VAR = "PARITY_RUN_PATH"


def test_baseline_is_readable():
    assert BASELINE.exists(), (
        f"Baseline missing at {BASELINE}. Capture it from a committed "
        "flag-off Ruusan ch01 sc01 run before running parity tests."
    )
    content = BASELINE.read_text(encoding="utf-8")
    assert content.strip(), "Baseline file is empty"


def test_ch01_sc01_flag_off_parity():
    """Byte-equality check against an explicitly supplied flag-off run."""
    override = os.environ.get(PARITY_ENV_VAR)
    if not override:
        pytest.skip(
            f"Set {PARITY_ENV_VAR} to the chapter_01_scene_01.md produced by "
            "a fresh flag-off Ruusan run to enable the live comparison."
        )
    live = Path(override)
    if not live.exists():
        pytest.fail(f"{PARITY_ENV_VAR}={override!r} does not exist on disk.")
    baseline_text = BASELINE.read_text(encoding="utf-8")
    live_text = live.read_text(encoding="utf-8")
    assert live_text == baseline_text, (
        f"Prose drift detected: {live} differs from baseline {BASELINE}. "
        "If intentional, refresh the baseline with human sign-off per "
        "tests/baselines/README.md."
    )
