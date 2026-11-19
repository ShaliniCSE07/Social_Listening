import json
import os
import re
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None

# Only these PII types matter for GR-7
_RELEVANT_TYPES = {"EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "CREDIT_CARD", "IBAN_CODE", "IP_ADDRESS"}
_MIN_SCORE = 0.4

KNOWN_COUNTRY_CODES = ["+1", "+7", "+20", "+27", "+30", "+31", "+32", "+33", "+34", "+36", "+39", "+40", "+41", "+43", "+44", "+45", "+46", "+47", "+48", "+49", "+51", "+52", "+53", "+54", "+55", "+56", "+57", "+58", "+60", "+61", "+62", "+63", "+64", "+65", "+66", "+81", "+82", "+84", "+86", "+90", "+91", "+92", "+93", "+94", "+95", "+98", "+212", "+213", "+216", "+218", "+220", "+221", "+222", "+223", "+224", "+225", "+226", "+227", "+228", "+229", "+230", "+231", "+232", "+233", "+234", "+235", "+236", "+237", "+238", "+239", "+240", "+241", "+242", "+243", "+244", "+245", "+246", "+248", "+249", "+250", "+251", "+252", "+253", "+254", "+255", "+256", "+257", "+258", "+260", "+261", "+262", "+263", "+264", "+265", "+266", "+267", "+268", "+269", "+290", "+291", "+297", "+298", "+299", "+350", "+351", "+352", "+353", "+354", "+355", "+356", "+357", "+358", "+359", "+370", "+371", "+372", "+373", "+374", "+375", "+376", "+377", "+378", "+379", "+380", "+381", "+382", "+383", "+385", "+386", "+387", "+389", "+420", "+421", "+423", "+500", "+501", "+502", "+503", "+504", "+505", "+506", "+507", "+508", "+509", "+590", "+591", "+592", "+593", "+594", "+595", "+596", "+597", "+598", "+599", "+670", "+672", "+673", "+674", "+675", "+676", "+677", "+678", "+679", "+680", "+681", "+682", "+683", "+685", "+686", "+687", "+688", "+689", "+690", "+691", "+692", "+850", "+852", "+853", "+855", "+856", "+880", "+886", "+960", "+961", "+962", "+963", "+964", "+965", "+966", "+967", "+968", "+970", "+971", "+972", "+973", "+974", "+975", "+976", "+977", "+992", "+993", "+994", "+995", "+996", "+998"]
KNOWN_COUNTRY_CODES.sort(key=len, reverse=True)

# --- NEW: Load Config ---
CONFIG_PATH = "masking_config.json"

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    # Fallback if file is missing
    return {
        "replacements": {"EMAIL_ADDRESS": "[EMAIL]"},
        "phone_masking": {"preserve_country_code": True, "mask_string": "xxxxxxxxxx", "fallback_mask": "xxxxxxxxxx"}
    }

MASK_CONFIG = load_config()

def mask_phone_keep_country_code(phone_text: str) -> str:
    phone_conf = MASK_CONFIG.get("phone_masking", {})
    preserve = phone_conf.get("preserve_country_code", True)
    mask_str = phone_conf.get("mask_string", "xxxxxxxxxx")
    fallback = phone_conf.get("fallback_mask", "xxxxxxxxxx")

    if not preserve:
        return fallback

    clean_text = re.sub(r'[\s\-()]', '', phone_text)
    for code in KNOWN_COUNTRY_CODES:
        if clean_text.startswith(code):
            return f"{code}{mask_str}"
    return fallback

def _engines():
    global _analyzer, _anonymizer
    if _analyzer is None:
        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()
    return _analyzer, _anonymizer

def mask_text(text: str) -> tuple[str, bool]:
    if not text or not text.strip():
        return text, True

    analyzer, anonymizer = _engines()
    try:
        results = analyzer.analyze(text=text, language="en")
    except Exception:
        return text, False

    relevant = [r for r in results if r.entity_type in _RELEVANT_TYPES and r.score >= _MIN_SCORE]
    if not relevant:
        return text, True

    # --- NEW: Dynamically build operators based on JSON config ---
    operators = {}
    
    # 1. Add standard replacements (Email, Name, etc.) from JSON
    for entity, new_value in MASK_CONFIG.get("replacements", {}).items():
        operators[entity] = OperatorConfig("replace", {"new_value": new_value})
        
    # 2. Add the custom phone logic based on JSON
    if MASK_CONFIG.get("phone_masking", {}).get("preserve_country_code"):
        operators["PHONE_NUMBER"] = OperatorConfig("custom", {"lambda": mask_phone_keep_country_code})
    else:
        # If preserve is false, just use the standard replace
        fallback = MASK_CONFIG.get("phone_masking", {}).get("fallback_mask", "xxxxxxxxxx")
        operators["PHONE_NUMBER"] = OperatorConfig("replace", {"new_value": fallback})

    try:
        anonymized = anonymizer.anonymize(text=text, analyzer_results=relevant, operators=operators)
        return anonymized.text, True
    except Exception as e:
        print(f"Masking error: {e}")
        return text, False