import json
import os
import re
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer import AnalyzerEngine, PatternRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None

CONFIG_PATH = "masking_config.json"

# Base list of PII types (Presidio needs to be told what to look for)
BASE_RELEVANT_TYPES = {
    "EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "CREDIT_CARD", 
    "IBAN_CODE", "IP_ADDRESS", "LOCATION", "NRP", "MEDICAL_LICENSE"
}
_MIN_SCORE = 0.4

KNOWN_COUNTRY_CODES = ["+1", "+91", "+44", "+49", "+33", "+61", "+81", "+86"] # Shortened for brevity

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {"default": {"entities": {}, "phone_masking": {}}, "country_overrides": {}}

MASK_CONFIG = load_config()

def mask_phone_keep_country_code(phone_text: str, phone_conf: dict) -> str:
    preserve = phone_conf.get("preserve_country_code", True)
    mask_str = phone_conf.get("mask_string", "xxxxxxxxxx")

    if not preserve:
        return mask_str

    clean_text = re.sub(r'[\s\-()]', '', phone_text)
    for code in KNOWN_COUNTRY_CODES:
        if clean_text.startswith(code):
            return f"{code}{mask_str}"
    return mask_str

def _engines():
    global _analyzer, _anonymizer
    if _analyzer is None:
        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()

        # This tells Presidio: "If you see these words, mark them as NRP (Religion/Politics)"
        sensitive_words = ["Hindu", "Muslim", "Christian", "Sikh", "Buddhist", "BJP", "Congress"]
        deny_list_recognizer = PatternRecognizer(
            supported_entity="NRP",
            deny_list=sensitive_words
        )
        _analyzer.registry.add_recognizer(deny_list_recognizer)
    return _analyzer, _anonymizer

def mask_text(text: str, country_code: str | None = None) -> tuple[str, bool]:
    """Returns (masked_text, success). Uses country_code to apply correct rules."""
    if not text or not text.strip():
        return text, True

    # 1. Determine which rules to use (Default or Country Override)
    country_code = str(country_code).upper() if country_code else "UNKNOWN"
    overrides = MASK_CONFIG.get("country_overrides", {})
    
    if country_code in overrides:
        active_rules = overrides[country_code]
    else:
        active_rules = MASK_CONFIG.get("default", {})

    # 2. Analyze text
    analyzer, anonymizer = _engines()
    try:
        # We pass the specific entities to look for based on the config
        entities_to_find = list(active_rules.get("entities", {}).keys())
        results = analyzer.analyze(text=text, language="en", entities=entities_to_find)
    except Exception:
        return text, False

    relevant = [r for r in results if r.score >= _MIN_SCORE]
    if not relevant:
        return text, True

    # 3. Build dynamic operators based on active country rules
    operators = {}
    for entity, new_value in active_rules.get("entities", {}).items():
        operators[entity] = OperatorConfig("replace", {"new_value": new_value})
    
    # Special handling for phone based on country config
    if "PHONE_NUMBER" in entities_to_find:
        phone_conf = active_rules.get("phone_masking", {})
        operators["PHONE_NUMBER"] = OperatorConfig("custom", {"lambda": lambda x: mask_phone_keep_country_code(x, phone_conf=phone_conf)})

    try:
        anonymized = anonymizer.anonymize(text=text, analyzer_results=relevant, operators=operators)
        return anonymized.text, True
    except Exception as e:
        print(f"Masking error: {e}")
        return text, False