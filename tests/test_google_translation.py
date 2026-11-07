"""Google adapter and API tests. All external requests use fake credentials and mocks."""
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest import TestCase,main as run_tests
from unittest.mock import patch
from urllib.error import HTTPError,URLError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from app import cloud_translation,db,main,translator
from fastapi.testclient import TestClient


class GoogleAdapterTests(TestCase):
 def setUp(self):
  self.enterContext(patch.dict(os.environ,GOOGLE_TRANSLATE_API_KEY="fake-test-key"))
  self.provider=cloud_translation.GoogleTranslator()
  self.provider.supported_codes={"en","zu","nr"}

 def test_authentication_header_and_southern_ndebele_mapping(self):
  response=io.BytesIO(json.dumps({"data":{"translations":[{"translatedText":"Mock &amp; translation"}]}}).encode())
  with patch.object(cloud_translation,"urlopen",return_value=response) as request:
   self.assertEqual(self.provider.translate("Hello","eng_Latn","nbl_Latn"),"Mock & translation")
  sent=request.call_args.args[0]
  self.assertEqual(sent.full_url,"https://translation.googleapis.com/language/translate/v2")
  self.assertNotIn("fake-test-key",sent.full_url)
  self.assertEqual(dict(sent.header_items())["X-goog-api-key"],"fake-test-key")
  payload=json.loads(sent.data)
  self.assertEqual((payload["source"],payload["target"],payload["format"]),("en","nr","text"))

 def test_capabilities_use_provider_response(self):
  with patch.object(self.provider,"_request",return_value={"languages":[{"language":"nr"},{"language":"en"}]}):
   self.provider.initialize()
  self.assertTrue(self.provider.supports("nbl_Latn"))
  self.assertFalse(self.provider.supports("ven_Latn"))

 def test_google_detects_source_instead_of_limited_local_detector(self):
  with patch.object(self.provider,"_request",return_value={"detections":[[{"language":"nr"}]]}):
   self.assertEqual(self.provider.detect("Mock source text"),"nbl_Latn")

 def test_request_failures_never_become_successful_output(self):
  errors=[HTTPError("https://example.com",403,"fake-test-key",{},None),HTTPError("https://example.com",429,"quota",{},None),URLError("offline"),TimeoutError()]
  for error in errors:
   with self.subTest(error=str(type(error))),patch.object(cloud_translation,"urlopen",side_effect=error):
    with self.assertRaises(cloud_translation.TranslationError) as caught:self.provider.translate("Hello","eng_Latn","nbl_Latn")
    self.assertNotIn("fake-test-key",str(caught.exception))

 def test_empty_or_invalid_translation_is_error(self):
  for data in ({},{"translations":[]},{"translations":[{"translatedText":""}]},{"translations":[{"translatedText":{}}]}):
   with self.subTest(data=data),patch.object(self.provider,"_request",return_value=data):
    with self.assertRaises(cloud_translation.TranslationError):self.provider.translate("Hello","eng_Latn","nbl_Latn")

 def test_unsupported_pair_does_not_send_request(self):
  with patch.object(self.provider,"_request") as request:
   with self.assertRaises(cloud_translation.TranslationError):self.provider.translate("Hello","eng_Latn","ven_Latn")
   request.assert_not_called()

 def test_provider_selection_does_not_load_torch_for_google(self):
  translator.get_translator.cache_clear()
  self.addCleanup(translator.get_translator.cache_clear)
  with patch.dict(os.environ,TRANSLATION_PROVIDER="google"):
   self.assertIsInstance(translator.get_translator(),cloud_translation.GoogleTranslator)
  translator.get_translator.cache_clear()
  with patch.dict(os.environ,TRANSLATION_PROVIDER="nllb"):
   self.assertIsInstance(translator.get_translator(),translator.LocalTranslator)


class GoogleApiTests(TestCase):
 def setUp(self):
  temp=self.enterContext(tempfile.TemporaryDirectory())
  self.path=Path(temp)/"test.db"
  self.enterContext(patch.dict(os.environ,GOOGLE_TRANSLATE_API_KEY="fake-test-key"))
  self.enterContext(patch.object(db,"SQLITE",True))
  self.enterContext(patch.object(db,"SQLITE_PATH",self.path,create=True))
  self.provider=cloud_translation.GoogleTranslator()
  self.provider.supported_codes={"en","nr","zu"}
  self.enterContext(patch.object(main,"get_translator",return_value=self.provider))
  self.enterContext(patch.object(main,"preload"))
  self.detect=self.enterContext(patch.object(main,"detect_language",return_value="eng_Latn"))
  self.client=self.enterContext(TestClient(main.app))

 def register(self,name,language):
  response=self.client.post("/auth/register",json=dict(name=name,email=name.lower()+"@example.com",password="TestPassword123!",preferred_language=language))
  self.assertEqual(response.status_code,200,response.text)
  headers={"Authorization":"Bearer "+response.json()["access_token"]}
  uid=self.client.get("/me",headers=headers).json()["id"]
  return uid,headers

 def test_translation_provider_cache_and_legacy_retranslation(self):
  sender,headers=self.register("Sender","eng_Latn")
  recipient,recipient_headers=self.register("Recipient","nbl_Latn")
  with patch.object(self.provider,"translate",return_value="Mock Google output") as translate:
   response=self.client.post("/messages",headers=headers,json=dict(recipient_id=recipient,text="Hello"))
   self.assertEqual(response.status_code,200,response.text)
   mid=response.json()["id"]
   with db.connect() as c:
    row=c.execute("SELECT * FROM message_translations WHERE message_id=?",(mid,)).fetchone()
    self.assertEqual(row["provider"],"google:nmt")
    c.execute("UPDATE message_translations SET provider=NULL,translated_text='Old NLLB output' WHERE message_id=?",(mid,))
   translate.reset_mock()
   response=self.client.post(f"/messages/{mid}/translate",headers=recipient_headers)
   self.assertEqual(response.json()["display_text"],"Mock Google output")
   translate.assert_called_once()
   self.client.post(f"/messages/{mid}/translate",headers=recipient_headers)
   translate.assert_called_once()
   self.assertEqual(self.client.get(f"/messages/{sender}",headers=recipient_headers).json()[0]["original_text"],"Hello")

 def test_service_failure_preserves_database(self):
  _,headers=self.register("Sender","eng_Latn")
  recipient,_=self.register("Recipient","nbl_Latn")
  with patch.object(self.provider,"translate",side_effect=cloud_translation.TranslationError("Google translation could not complete.")):
   response=self.client.post("/messages",headers=headers,json=dict(recipient_id=recipient,text="Hello"))
  self.assertEqual(response.status_code,503,response.text)
  self.assertIsInstance(response.json()["detail"],str)
  with db.connect() as c:self.assertIsNone(c.execute("SELECT * FROM messages").fetchone())

 def test_explicit_source_and_unavailable_language(self):
  _,headers=self.register("Sender","nbl_Latn")
  recipient,_=self.register("Recipient","eng_Latn")
  with patch.object(self.provider,"translate",return_value="Mock English output") as translate:
   response=self.client.post("/messages",headers=headers,json=dict(recipient_id=recipient,text="Mock source text",source_language="nbl_Latn"))
  self.assertEqual(response.status_code,200,response.text)
  translate.assert_called_once_with("Mock source text","nbl_Latn","eng_Latn")
  self.detect.assert_not_called()
  response=self.client.patch("/me/language",headers=headers,json=dict(preferred_language="ven_Latn"))
  self.assertEqual(response.status_code,422,response.text)

 def test_schema_migration_keeps_existing_translation(self):
  connection=sqlite3.connect(self.path)
  try:
   with connection:
    connection.execute("DROP TABLE message_translations")
    connection.execute("CREATE TABLE message_translations(message_id INTEGER,user_id INTEGER,language TEXT,translated_text TEXT,PRIMARY KEY(message_id,user_id))")
    connection.execute("INSERT INTO message_translations VALUES(1,1,'nbl_Latn','Old cached text')")
  finally:connection.close()
  db.init_db()
  with db.connect() as c:
   row=c.execute("SELECT * FROM message_translations").fetchone()
   self.assertEqual(row["translated_text"],"Old cached text")
   self.assertIsNone(row["provider"])


if __name__=="__main__":run_tests()
