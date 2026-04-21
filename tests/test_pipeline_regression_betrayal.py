"""Parity regression scaffold for Legacy of the Force: Betrayal ch01 sc01.

Mirror of ``tests/test_pipeline_regression_ruusan.py``. The full pipeline
is too expensive to run in ``pytest -q``; live comparison is opt-in via
the ``PARITY_RUN_PATH`` env var. See that module's docstring for details.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


BASELINE = Path(__file__).parent / "baselines" / "betrayal_ch01_sc01.md"

PARITY_ENV_VAR = "PARITY_RUN_PATH"


def test_baseline_is_readable():
    assert BASELINE.exists(), (
        f"Baseline missing at {BASELINE}. Capture it from a committed "
        "flag-off Betrayal ch01 sc01 run before running parity tests."
    )
    content = BASELINE.read_text(encoding="utf-8")
    assert content.strip(), "Baseline file is empty"


def test_ch01_sc01_flag_off_parity():
    override = os.environ.get(PARITY_ENV_VAR)
    if not override:
        pytest.skip(
            f"Set {PARITY_ENV_VAR} to the chapter_01_scene_01.md produced by "
            "a fresh flag-off Betrayal run to enable the live comparison."
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
