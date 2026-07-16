from agent.metacognition_contract import (
    MIN_GROUNDED_CONFIDENCE,
    MAX_GROUNDED_CALIBRATION_ERROR,
    MetacognitiveSignal,
    evaluate_claim,
)


def test_grounded_claim_passes():
    signal = MetacognitiveSignal("I can read this file", True, 0.9, 0.1)
    verdict = evaluate_claim(signal)
    assert verdict.grounded is True


def test_out_of_capability_claim_is_not_grounded():
    signal = MetacognitiveSignal("I can control physical hardware", False, 0.9, 0.1)
    verdict = evaluate_claim(signal)
    assert verdict.grounded is False
    assert "capability" in verdict.reason


def test_low_confidence_claim_is_not_grounded():
    signal = MetacognitiveSignal("maybe this works", True, MIN_GROUNDED_CONFIDENCE - 0.1, 0.1)
    verdict = evaluate_claim(signal)
    assert verdict.grounded is False
    assert "belief_confidence" in verdict.reason


def test_poorly_calibrated_claim_is_not_grounded():
    signal = MetacognitiveSignal("this will work", True, 0.9, MAX_GROUNDED_CALIBRATION_ERROR + 0.1)
    verdict = evaluate_claim(signal)
    assert verdict.grounded is False
    assert "calibration_error" in verdict.reason


def test_signal_rejects_empty_claim():
    try:
        MetacognitiveSignal("", True, 0.9, 0.1)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_signal_rejects_out_of_range_confidence():
    try:
        MetacognitiveSignal("x", True, 1.5, 0.1)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_verdict_content_hash_is_deterministic():
    verdict = evaluate_claim(MetacognitiveSignal("x", True, 0.9, 0.1))
    assert verdict.content_hash() == verdict.content_hash()
    assert verdict.to_dict()["schema"] == "simplicio.metacognition/v1"
