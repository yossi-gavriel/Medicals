from app.services.clinical_explanation_service import ClinicalExplanationService


def test_deterministic_explanation() -> None:
    text = ClinicalExplanationService.explain("aspirin", "warfarin", "bleeding", "D")
    assert "Aspirin" in text
    assert "Warfarin" in text
    assert "bleeding" in text
