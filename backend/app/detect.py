from functools import lru_cache
from lingua import LanguageDetectorBuilder, Language

DETECTABLE = [
    Language.ENGLISH, Language.AFRIKAANS,
    Language.ZULU, Language.XHOSA, Language.SOTHO,
    Language.TSONGA, Language.TSWANA,
]

# lingua Language -> NLLB-200 language code (used as source for translation)
LINGUA_TO_NLLB = {
    Language.ENGLISH: "eng_Latn",
    Language.AFRIKAANS: "afr_Latn",
    Language.ZULU: "zul_Latn",
    Language.XHOSA: "xho_Latn",
    Language.SOTHO: "sot_Latn",
    Language.TSONGA: "tso_Latn",
    Language.TSWANA: "tsn_Latn",
}


@lru_cache(maxsize=1)
def _build():
    return LanguageDetectorBuilder.from_languages(*DETECTABLE).with_low_accuracy_mode().build()


@lru_cache(maxsize=4096)
def detect_language(text: str):
    """Detect the language of a message and return an NLLB-200 language code.

    Returns "" when the text is too short to detect reliably.
    """
    text = (text or "").strip()
    if len(text) < 3:
        return ""
    result = _build().detect_language_of(text)
    if result is None:
        return ""
    return LINGUA_TO_NLLB.get(result, "")
