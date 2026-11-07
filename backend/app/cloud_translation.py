"""Google Cloud Translation Basic. Credentials stay in request headers."""
import html
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .languages import GOOGLE_CODES


class TranslationError(Exception):
 def __init__(self,message,status_code=503):
  super().__init__(message)
  self.status_code=status_code


class GoogleTranslator:
 provider="google:nmt"

 def __init__(self):
  self.key=os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
  if not self.key:raise TranslationError("Set GOOGLE_TRANSLATE_API_KEY in the local .env file to enable Google translation.")
  self.supported_codes=None

 def _request(self,path="",payload=None):
  request=Request("https://translation.googleapis.com/language/translate/v2"+path,
   data=json.dumps(payload).encode("utf-8") if payload is not None else None,
   headers={"Content-Type":"application/json; charset=utf-8","X-Goog-Api-Key":self.key},
   method="POST" if payload is not None else "GET")
  try:
   with urlopen(request,timeout=30) as response:
    data=json.load(response)
   return data["data"]
  except HTTPError as exc:
   if exc.code in (401,403):
    message="Google translation is unavailable. Check the API key, Cloud Translation API access, billing, and key restrictions."
   elif exc.code==429:message="Google translation quota has been reached. Please try again later."
   else:message="Google translation could not complete. Please try again."
   raise TranslationError(message) from None
  except (URLError,TimeoutError,OSError,ValueError,KeyError,TypeError):
   raise TranslationError("Could not reach Google translation or read its response. Please try again.") from None

 def initialize(self):
  try:self.supported_codes={row["language"] for row in self._request("/languages")["languages"]}
  except (KeyError,TypeError):raise TranslationError("Google returned an invalid supported-language response.") from None
  return self

 def supports(self,code):
  if self.supported_codes is None:self.initialize()
  return GOOGLE_CODES.get(code) in self.supported_codes

 def detect(self,text):
  try:code=self._request("/detect",{"q":text})["detections"][0][0]["language"]
  except (KeyError,IndexError,TypeError):raise TranslationError("Google could not detect the message language.") from None
  reverse={value:key for key,value in GOOGLE_CODES.items()}
  if code not in reverse:raise TranslationError("The detected language is not supported in this app.",422)
  return reverse[code]

 def translate(self,text,source,target):
  if not self.supports(source) or not self.supports(target):
   raise TranslationError("This language is unavailable from Google Cloud Translation.",422)
  if source==target:return text
  data=self._request(payload={"q":text,"source":GOOGLE_CODES[source],"target":GOOGLE_CODES[target],"format":"text","model":"nmt"})
  try:translated=data["translations"][0]["translatedText"]
  except (KeyError,IndexError,TypeError):raise TranslationError("Google returned an invalid translation response.") from None
  if not isinstance(translated,str) or not translated.strip():raise TranslationError("Google returned an empty translation.")
  return html.unescape(translated)
