import re
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None

# Only these PII types matter for GR-7 (personal information).
_RELEVANT_TYPES = {"EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "CREDIT_CARD", "IBAN_CODE", "IP_ADDRESS"}
_MIN_SCORE = 0.4

# A hardcoded list of common country codes to safely extract without greedy matching
KNOWN_COUNTRY_CODES = [
    "+1", "+7", "+20", "+27", "+30", "+31", "+32", "+33", "+34", "+36", "+39", "+40", "+41", "+43", "+44", "+45", "+46", "+47", "+48", "+49",
    "+51", "+52", "+53", "+54", "+55", "+56", "+57", "+58", "+60", "+61", "+62", "+63", "+64", "+65", "+66", "+81", "+82", "+84", "+86", "+90",
    "+91", "+92", "+93", "+94", "+95", "+98", "+212", "+213", "+216", "+218", "+220", "+221", "+222", "+223", "+224", "+225", "+226", "+227", "+228", "+229",
    "+230", "+231", "+232", "+233", "+234", "+235", "+236", "+237", "+238", "+239", "+240", "+241", "+242", "+243", "+244", "+245", "+246", "+248", "+249", "+250",
    "+251", "+252", "+253", "+254", "+255", "+256", "+257", "+258", "+260", "+261", "+262", "+263", "+264", "+265", "+266", "+267", "+268", "+269", "+290", "+291",
    "+297", "+298", "+299", "+350", "+351", "+352", "+353", "+354", "+355", "+356", "+357", "+358", "+359", "+370", "+371", "+372", "+373", "+374", "+375", "+376",
    "+377", "+378", "+379", "+380", "+381", "+382", "+383", "+385", "+386", "+387", "+389", "+420", "+421", "+423", "+500", "+501", "+502", "+503", "+504", "+505",
    "+506", "+507", "+508", "+509", "+590", "+591", "+592", "+593", "+594", "+595", "+596", "+597", "+598", "+599", "+670", "+672", "+673", "+674", "+675", "+676",
    "+677", "+678", "+679", "+680", "+681", "+682", "+683", "+685", "+686", "+687", "+688", "+689", "+690", "+691", "+692", "+850", "+852", "+853", "+855", "+856",
    "+880", "+886", "+960", "+961", "+962", "+963", "+964", "+965", "+966", "+967", "+968", "+970", "+971", "+972", "+973", "+974", "+975", "+976", "+977", "+992",
    "+993", "+994", "+995", "+996", "+998"
]
KNOWN_COUNTRY_CODES.sort(key=len, reverse=True)


def mask_phone_keep_country_code(phone_text: str) -> str:
    """Masks phone number but leaves the country code intact."""
    # Remove any spaces or dashes for clean matching (e.g. "+91 98765" -> "+9198765")
    clean_text = re.sub(r'[\s\-()]', '', phone_text)
    
    # Check if the start of the string matches any known country code
    for code in KNOWN_COUNTRY_CODES:
        if clean_text.startswith(code):
            return f"{code}xxxxxxxxxx"
            
    # If no country code is found, mask the whole thing
    return "xxxxxxxxxx"


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
        return text, True

    operators = {
        "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}), 
        "PHONE_NUMBER": OperatorConfig("custom", {"lambda": mask_phone_keep_country_code}),
        "PERSON": OperatorConfig("replace", {"new_value": "[NAME]"}),
        "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CARD]"}),
        "IBAN_CODE": OperatorConfig("replace", {"new_value": "[IBAN]"}),
        "IP_ADDRESS": OperatorConfig("replace", {"new_value": "[IP]"}),
    }
    try:
        anonymized = anonymizer.anonymize(text=text, analyzer_results=relevant, operators=operators)
        return anonymized.text, True
    except Exception as e:
        print(f"Masking error: {e}") 
        return text, False