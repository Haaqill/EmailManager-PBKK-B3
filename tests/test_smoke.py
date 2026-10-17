"""Tes paling dasar: repo bisa di-import dan pytest jalan."""
import app.contracts as contracts

def test_contracts_importable():
    assert contracts.PlanItem is not None
    assert contracts.ReviewDecision is not None
    assert contracts.ErrorCode.VALIDATION.value == "validation"

def test_plan_item_promosi_selalu_nanti():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        contracts.PlanItem(
            thread_id="t1", summary="x", category="Promosi",
            priority="Mendesak", action="keep", needs_reply=False,
            reason="test",
        )