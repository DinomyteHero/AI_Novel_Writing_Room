"""Back-compat re-export shim.

The canonical location for the scene-card translator is
``workflows/_shared/scene_card_translator.py`` as of Phase 4. This module
preserves the historical import path
``src.concept_workshop.scene_card_translator`` for callers that have not
yet been updated. Phase 8 cleanup retires this shim.
"""

from workflows._shared.scene_card_translator import *  # noqa: F401,F403
from workflows._shared.scene_card_translator import (  # noqa: F401
    ARC_PHASE_PREFIX,
    UPPERCASE_MARKERS,
    build_scene_card_notes,
    derive_structural_phase,
    translate_scene_card,
)
