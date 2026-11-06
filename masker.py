from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None

# Only these PII types matter for GR-7 (personal information).
# A low-confidence hit on an unrelated type (e.g. a weak PERSON guess)
# must not fail the whole record.
_RELEVANT_TYPES = {"EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "CREDIT_CARD", "IBAN_CODE", "IP_ADDRESS"}
_MIN_SCORE = 0.4  # discard recognizer noise below this


def _engines():
    global _analyzer, _anonymizer
    if _analyzer is None:
        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()
    return _analyzer, _anonymizer


def mask_text(text: str) -> tuple[str, bool]:
    """Returns (masked_text, success). success=False -> caller quarantines (GR-7)."""
    if not text or not text.strip():
        return text, True

    analyzer, anonymizer = _engines()
    try:
        results = analyzer.analyze(text=text, language="en")
    except Exception:
        return text, False

    # Keep only relevant, reasonably confident hits.
    relevant = [r for r in results if r.entity_type in _RELEVANT_TYPES and r.score >= _MIN_SCORE]
    if not relevant:
        # No PII detected — masking "succeeded" trivially, no need to anonymize.
        return text, True

    operators = {
        "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}),
        "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE]"}),
        "PERSON": OperatorConfig("replace", {"new_value": "[NAME]"}),
        "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CARD]"}),
        "IBAN_CODE": OperatorConfig("replace", {"new_value": "[IBAN]"}),
        "IP_ADDRESS": OperatorConfig("replace", {"new_value": "[IP]"}),
    }
    try:
        anonymized = anonymizer.anonymize(text=text, analyzer_results=relevant, operators=operators)
        return anonymized.text, True
    except Exception:
        return text, False