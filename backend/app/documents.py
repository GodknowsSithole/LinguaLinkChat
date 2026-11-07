import io,re,os,uuid
from fastapi import HTTPException
from pypdf import PdfReader
from docx import Document

MAX_CHARS=8000  # cap to keep CPU-only translation time bounded
CHUNK_CHARS=600  # roughly fits NLLB's 512 token limit with margin
UPLOAD_DIR=os.getenv("UPLOAD_DIR","uploads")

MIME_TYPES={".txt":"text/plain",".pdf":"application/pdf",".docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}

def save_attachment(filename:str,data:bytes):
 os.makedirs(UPLOAD_DIR,exist_ok=True)
 ext=os.path.splitext(filename or "")[1].lower()
 stored_name=f"{uuid.uuid4().hex}{ext}"
 path=os.path.join(UPLOAD_DIR,stored_name)
 with open(path,"wb") as f:f.write(data)
 return path,MIME_TYPES.get(ext,"application/octet-stream")

def extract_text(filename:str,data:bytes)->str:
 name=(filename or "").lower()
 if name.endswith(".txt"):
  try:return data.decode("utf-8")
  except UnicodeDecodeError:return data.decode("latin-1")
 if name.endswith(".pdf"):
  try:
   reader=PdfReader(io.BytesIO(data))
   return "\n".join(page.extract_text() or "" for page in reader.pages)
  except Exception:raise HTTPException(400,"Could not read PDF file")
 if name.endswith(".docx"):
  try:
   doc=Document(io.BytesIO(data))
   return "\n".join(p.text for p in doc.paragraphs)
  except Exception:raise HTTPException(400,"Could not read DOCX file")
 raise HTTPException(400,"Unsupported document type. Use .txt, .pdf or .docx")

def chunk_text(text:str,size:int=CHUNK_CHARS):
 text=re.sub(r"\n{3,}","\n\n",text.strip())
 paragraphs=[p.strip() for p in text.split("\n") if p.strip()]
 chunks=[];cur=""
 for p in paragraphs:
  candidate=(cur+"\n"+p) if cur else p
  if len(candidate)>size and cur:
   chunks.append(cur);cur=p
  else:
   cur=candidate
  while len(cur)>size:
   chunks.append(cur[:size]);cur=cur[size:]
 if cur:chunks.append(cur)
 return chunks or [""]
