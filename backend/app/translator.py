"""Choose Google Cloud or the optional local NLLB model."""
import os
from functools import lru_cache
from .cloud_translation import GoogleTranslator,TranslationError
from .languages import LANGUAGES

MODEL=os.getenv("MODEL_ID","facebook/nllb-200-distilled-600M")

class LocalTranslator:
 provider="nllb:"+MODEL
 def supports(self,code):return code in LANGUAGES and code not in {"nbl_Latn","ven_Latn"}
 def detect(self,text):
  from .detect import detect_language
  return detect_language(text)
 def translate(self,text,source,target):
  if not self.supports(source) or not self.supports(target):
   raise TranslationError("This language is unavailable from the local model. Configure Google translation to use another provider.",422)
  from .local_translation import get_translator
  return get_translator().translate(text,source,target)

@lru_cache(maxsize=1)
def get_translator():
 provider=os.getenv("TRANSLATION_PROVIDER","nllb").strip().lower()
 if provider=="google":return GoogleTranslator()
 if provider=="nllb":return LocalTranslator()
 raise TranslationError("TRANSLATION_PROVIDER must be google or nllb.")

def detect_language(text):return get_translator().detect(text)

def preload():
 if isinstance(get_translator(),GoogleTranslator):get_translator().initialize()
 else:
  from .local_translation import preload as preload_local
  preload_local()
