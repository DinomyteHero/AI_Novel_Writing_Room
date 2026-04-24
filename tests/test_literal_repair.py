from src.quality.literal_repair import apply_literal_repairs


def test_apply_literal_repairs_applies_unique_pattern():
    result = apply_literal_repairs(
        "Sera said the public settlement was old.",
        [
            {
                "issue_type": "survivor_later_frame",
                "pattern": "the public settlement",
                "replacement": "the buried protocol",
                "reason": "remove later public frame from survivor dialogue",
            }
        ],
        max_changed_ratio=1.0,
    )

    assert result["changed"]
    assert result["prose"] == "Sera said the buried protocol was old."
    assert len(result["applied"]) == 1


def test_apply_literal_repairs_skips_duplicate_pattern():
    result = apply_literal_repairs(
        "public settlement / public settlement",
        [
            {
                "issue_type": "survivor_later_frame",
                "pattern": "public settlement",
                "replacement": "buried protocol",
            }
        ],
    )

    assert not result["changed"]
    assert result["skipped"][0]["reason"] == "pattern occurs 2 times"


def test_apply_literal_repairs_enforces_change_budget():
    result = apply_literal_repairs(
        "short target text",
        [
            {
                "issue_type": "budget",
                "pattern": "short",
                "replacement": "a replacement that is much too large",
            }
        ],
        max_total_changed_chars=8,
    )

    assert not result["changed"]
    assert result["skipped"][0]["reason"] == "change budget exceeded"
