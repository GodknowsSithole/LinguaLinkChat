import os,threading,torch
from functools import lru_cache
from transformers import AutoTokenizer,AutoModelForSeq2SeqLM
MODEL=os.getenv("MODEL_ID","facebook/nllb-200-distilled-600M")
NUM_BEAMS=int(os.getenv("NUM_BEAMS","2"))            # 5 = best quality/slowest, 1 = greedy/fastest
QUANTIZE=os.getenv("QUANTIZE_INT8","0")=="1"          # dynamic int8 on Linear layers (x86 CPUs): lower RAM, similar speed at 2 beams
class Translator:
 def __init__(self):
  self.device="cuda" if torch.cuda.is_available() else "cpu"
  self.t=AutoTokenizer.from_pretrained(MODEL)
  self.m=AutoModelForSeq2SeqLM.from_pretrained(MODEL)
  if self.device=="cpu" and QUANTIZE:
   self.m=torch.quantization.quantize_dynamic(self.m,{torch.nn.Linear},dtype=torch.qint8)
  self.m=self.m.to(self.device); self.m.eval()
 def translate(self,text,source,target):
  if source==target:return text
  self.t.src_lang=source; x=self.t(text,return_tensors="pt",truncation=True,max_length=512).to(self.device)
  with torch.inference_mode(): y=self.m.generate(**x,forced_bos_token_id=self.t.convert_tokens_to_ids(target),max_new_tokens=512,num_beams=NUM_BEAMS,no_repeat_ngram_size=3,repetition_penalty=1.1)
  return self.t.batch_decode(y,skip_special_tokens=True)[0]
@lru_cache(maxsize=1)
def get_translator():return Translator()
def preload():
 """Load the model in a background thread at server start so the first message is not delayed."""
 def run():
  t=get_translator(); t.translate("Hello","eng_Latn","zul_Latn")   # warm-up pass
 threading.Thread(target=run,daemon=True,name="model-preload").start()
