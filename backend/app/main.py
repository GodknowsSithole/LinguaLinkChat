import asyncio,json,os
from collections import defaultdict
from fastapi import FastAPI,HTTPException,Depends,WebSocket,WebSocketDisconnect,UploadFile,File,Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel,EmailStr,Field
from .db import connect,init_db,close_pool,INTEGRITY_ERRORS
from .auth import hash_password,verify_password,token,decode,current_user_id
from .languages import LANGUAGES
from .translator import get_translator,preload,detect_language
from .cloud_translation import TranslationError
from .documents import extract_text,chunk_text,save_attachment,MAX_CHARS
app=FastAPI(title="LinguaLink Chat API")
@app.exception_handler(TranslationError)
async def translation_error(request,exc):
 return JSONResponse(status_code=exc.status_code,content={"detail":str(exc)})
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:3000","http://localhost:3001"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
@app.on_event("startup")
def startup():init_db();preload()
@app.on_event("shutdown")
def shutdown():close_pool()
class Register(BaseModel):name:str=Field(min_length=2,max_length=80);email:EmailStr;password:str=Field(min_length=8);preferred_language:str
class Login(BaseModel):email:EmailStr;password:str
class Preference(BaseModel):preferred_language:str
class SendMessage(BaseModel):recipient_id:int;text:str=Field(min_length=1,max_length=3000);source_language:str=""

def public_user(r):return {"id":r["id"],"name":r["name"],"email":r["email"],"preferred_language":r["preferred_language"]}
def valid_lang(x):
 if x not in LANGUAGES:raise HTTPException(400,"Unsupported language")
 if not get_translator().supports(x):raise HTTPException(422,f"{LANGUAGES[x]} is unavailable from the selected translation service.")
def is_blocked(c,a,b):
 return c.execute("SELECT 1 FROM blocked_users WHERE (user_id=? AND other_id=?) OR (user_id=? AND other_id=?)",(a,b,b,a)).fetchone() is not None
@app.get("/languages")
def languages():return [{"code":k,"name":v,"supported":get_translator().supports(k)} for k,v in LANGUAGES.items()]
@app.post("/auth/register")
def register(x:Register):
 valid_lang(x.preferred_language)
 try:
  with connect() as c:uid=c.execute("INSERT INTO users(name,email,password_hash,preferred_language) VALUES(?,?,?,?) RETURNING id",(x.name,x.email.lower(),hash_password(x.password),x.preferred_language)).fetchone()["id"]
 except INTEGRITY_ERRORS:raise HTTPException(409,"Email already registered")
 return {"access_token":token(uid),"token_type":"bearer"}
@app.post("/auth/login")
def login(x:Login):
 with connect() as c:r=c.execute("SELECT * FROM users WHERE email=?",(x.email.lower(),)).fetchone()
 if not r or not verify_password(x.password,r["password_hash"]):raise HTTPException(401,"Incorrect email or password")
 return {"access_token":token(r["id"]),"token_type":"bearer"}
@app.get("/me")
def me(uid=Depends(current_user_id)):
 with connect() as c:r=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
 return public_user(r)
@app.patch("/me/language")
def preference(x:Preference,uid=Depends(current_user_id)):
 valid_lang(x.preferred_language)
 with connect() as c:c.execute("UPDATE users SET preferred_language=? WHERE id=?",(x.preferred_language,uid))
 return {"preferred_language":x.preferred_language}
@app.get("/users")
def users(search:str="",uid=Depends(current_user_id)):
 q=search.strip()
 with connect() as c:
  if q:
   like=f"%{q}%"
   rows=c.execute("""SELECT * FROM users WHERE id<>? AND (LOWER(name) LIKE LOWER(?) OR LOWER(email) LIKE LOWER(?))
    AND id NOT IN (SELECT other_id FROM blocked_users WHERE user_id=?)
    ORDER BY name""",(uid,like,like,uid)).fetchall()
  else:
   rows=c.execute("""SELECT * FROM users WHERE id<>?
    AND id NOT IN (SELECT other_id FROM hidden_users WHERE user_id=?)
    AND id NOT IN (SELECT other_id FROM blocked_users WHERE user_id=?)
    ORDER BY name""",(uid,uid,uid)).fetchall()
 return [public_user(r) for r in rows]
@app.post("/users/{other_id}/hide")
def hide_user(other_id:int,uid=Depends(current_user_id)):
 with connect() as c:c.execute("INSERT INTO hidden_users(user_id,other_id) VALUES(?,?) ON CONFLICT DO NOTHING",(uid,other_id))
 return {"hidden":True}
@app.post("/users/{other_id}/unhide")
def unhide_user(other_id:int,uid=Depends(current_user_id)):
 with connect() as c:c.execute("DELETE FROM hidden_users WHERE user_id=? AND other_id=?",(uid,other_id))
 return {"hidden":False}
@app.post("/users/{other_id}/block")
def block_user(other_id:int,uid=Depends(current_user_id)):
 with connect() as c:
  c.execute("INSERT INTO blocked_users(user_id,other_id) VALUES(?,?) ON CONFLICT DO NOTHING",(uid,other_id))
  c.execute("INSERT INTO hidden_users(user_id,other_id) VALUES(?,?) ON CONFLICT DO NOTHING",(uid,other_id))
 return {"blocked":True}
@app.post("/users/{other_id}/unblock")
def unblock_user(other_id:int,uid=Depends(current_user_id)):
 with connect() as c:
  c.execute("DELETE FROM blocked_users WHERE user_id=? AND other_id=?",(uid,other_id))
  c.execute("DELETE FROM hidden_users WHERE user_id=? AND other_id=?",(uid,other_id))
 return {"blocked":False}
@app.get("/users/blocked")
def list_blocked(uid=Depends(current_user_id)):
 with connect() as c:rows=c.execute("SELECT u.* FROM blocked_users b JOIN users u ON u.id=b.other_id WHERE b.user_id=? ORDER BY u.name",(uid,)).fetchall()
 return [public_user(r) for r in rows]
@app.get("/messages/{other_id}")
def history(other_id:int,uid=Depends(current_user_id)):
 with connect() as c:
  clear=c.execute("SELECT cleared_message_id FROM chat_clears WHERE user_id=? AND other_id=?",(uid,other_id)).fetchone()
  since=clear["cleared_message_id"] if clear else 0
  rows=c.execute("""SELECT m.*,u.name sender_name,COALESCE(t.translated_text,m.original_text) display_text FROM messages m JOIN users u ON u.id=m.sender_id LEFT JOIN message_translations t ON t.message_id=m.id AND t.user_id=? WHERE ((sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)) AND m.id>? AND m.id NOT IN (SELECT message_id FROM message_hidden_for WHERE user_id=?) ORDER BY m.id""",(uid,uid,other_id,other_id,uid,since,uid)).fetchall()
 return [dict(r) for r in rows]
@app.delete("/messages/{other_id}")
def delete_chat_for_me(other_id:int,uid=Depends(current_user_id)):
 with connect() as c:
  last=c.execute("SELECT MAX(id) mx FROM messages WHERE (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)",(uid,other_id,other_id,uid)).fetchone()
  mx=last["mx"] or 0
  c.execute("INSERT INTO chat_clears(user_id,other_id,cleared_message_id) VALUES(?,?,?) ON CONFLICT(user_id,other_id) DO UPDATE SET cleared_message_id=excluded.cleared_message_id",(uid,other_id,mx))
 return {"cleared_through":mx}
connections=defaultdict(set)
async def push(uid,payload):
 dead=[]
 for ws in connections[uid]:
  try:await ws.send_json(payload)
  except Exception:dead.append(ws)
 for ws in dead:connections[uid].discard(ws)
@app.post("/messages")
async def send(x:SendMessage,uid=Depends(current_user_id)):
 raw=x.text.strip()
 source=x.source_language or await asyncio.to_thread(detect_language,raw)
 valid_lang(source)
 with connect() as c:
  recipient=c.execute("SELECT * FROM users WHERE id=?",(x.recipient_id,)).fetchone()
  sender=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
  if not recipient:raise HTTPException(404,"Recipient not found")
  if is_blocked(c,uid,x.recipient_id):raise HTTPException(403,"You cannot message this user")
 target=recipient["preferred_language"]
 translated=await asyncio.to_thread(get_translator().translate,raw,source,target)
 with connect() as c:
  mid=c.execute("INSERT INTO messages(sender_id,recipient_id,original_text,original_language) VALUES(?,?,?,?) RETURNING id",(uid,x.recipient_id,raw,source)).fetchone()["id"]
  c.execute("INSERT INTO message_translations(message_id,user_id,language,translated_text,provider) VALUES(?,?,?,?,?)",(mid,x.recipient_id,target,translated,get_translator().provider))
 payload={"type":"message","message":{"id":mid,"sender_id":uid,"recipient_id":x.recipient_id,"sender_name":sender["name"],"original_text":raw,"original_language":source,"display_text":translated,"translated_language":target}}
 await push(x.recipient_id,payload);await push(uid,{**payload,"message":{**payload["message"],"display_text":raw}})
 return payload["message"]
@app.post("/messages/document")
async def send_document(recipient_id:int=Form(...),file:UploadFile=File(...),uid=Depends(current_user_id)):
 data=await file.read()
 if len(data)>10*1024*1024:raise HTTPException(400,"File too large (max 10MB)")
 text=extract_text(file.filename,data).strip()
 if not text:raise HTTPException(400,"No readable text found in document")
 truncated=len(text)>MAX_CHARS
 if truncated:text=text[:MAX_CHARS]+"\n\n[Document truncated to first %d characters]"%MAX_CHARS
 with connect() as c:
  recipient=c.execute("SELECT * FROM users WHERE id=?",(recipient_id,)).fetchone()
  sender=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
  if not recipient:raise HTTPException(404,"Recipient not found")
  if is_blocked(c,uid,recipient_id):raise HTTPException(403,"You cannot message this user")
 source=await asyncio.to_thread(detect_language,text) or "eng_Latn"
 valid_lang(source)
 attachment_path,attachment_mime=save_attachment(file.filename,data)
 with connect() as c:
  mid=c.execute("INSERT INTO messages(sender_id,recipient_id,original_text,original_language,attachment_name,attachment_path,attachment_mime) VALUES(?,?,?,?,?,?,?) RETURNING id",(uid,recipient_id,text,source,file.filename,attachment_path,attachment_mime)).fetchone()["id"]
 payload={"type":"message","message":{"id":mid,"sender_id":uid,"recipient_id":recipient_id,"sender_name":sender["name"],"original_text":text,"original_language":source,"display_text":text,"translated_language":None,"attachment_name":file.filename}}
 await push(recipient_id,payload);await push(uid,payload)
 return payload["message"]
@app.get("/attachments/{message_id}")
def download_attachment(message_id:int,uid=Depends(current_user_id)):
 with connect() as c:m=c.execute("SELECT * FROM messages WHERE id=?",(message_id,)).fetchone()
 if not m or uid not in (m["sender_id"],m["recipient_id"]):raise HTTPException(404,"Attachment not found")
 if not m["attachment_path"] or not os.path.exists(m["attachment_path"]):raise HTTPException(404,"Attachment not found")
 return FileResponse(m["attachment_path"],media_type=m["attachment_mime"] or "application/octet-stream",filename=m["attachment_name"] or "document")
@app.post("/messages/{message_id}/translate")
async def translate_message(message_id:int,uid=Depends(current_user_id)):
 with connect() as c:
  m=c.execute("SELECT * FROM messages WHERE id=?",(message_id,)).fetchone()
  if not m or uid not in (m["sender_id"],m["recipient_id"]):raise HTTPException(404,"Message not found")
  viewer=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
  target=viewer["preferred_language"]
  cached=c.execute("SELECT translated_text,provider FROM message_translations WHERE message_id=? AND user_id=? AND language=?",(message_id,uid,target)).fetchone()
 if cached and cached["provider"]==get_translator().provider:return {"display_text":cached["translated_text"],"translated_language":target}
 source=m["original_language"]
 chunks=chunk_text(m["original_text"]) if m["attachment_name"] else [m["original_text"]]
 translator=get_translator()
 parts=[]
 for ch in chunks:
  parts.append(await asyncio.to_thread(translator.translate,ch,source,target))
 translated="\n".join(parts)
 with connect() as c:
  c.execute("INSERT INTO message_translations(message_id,user_id,language,translated_text,provider) VALUES(?,?,?,?,?) ON CONFLICT(message_id,user_id) DO UPDATE SET language=excluded.language,translated_text=excluded.translated_text,provider=excluded.provider",(message_id,uid,target,translated,get_translator().provider))
 return {"display_text":translated,"translated_language":target}
@app.delete("/message/{message_id}/me")
def delete_message_for_me(message_id:int,uid=Depends(current_user_id)):
 with connect() as c:
  m=c.execute("SELECT * FROM messages WHERE id=?",(message_id,)).fetchone()
  if not m or uid not in (m["sender_id"],m["recipient_id"]):raise HTTPException(404,"Message not found")
  c.execute("INSERT INTO message_hidden_for(message_id,user_id) VALUES(?,?) ON CONFLICT DO NOTHING",(message_id,uid))
 return {"hidden":True}
@app.delete("/message/{message_id}")
async def delete_message(message_id:int,uid=Depends(current_user_id)):
 with connect() as c:
  m=c.execute("SELECT * FROM messages WHERE id=?",(message_id,)).fetchone()
  if not m:raise HTTPException(404,"Message not found")
  if m["sender_id"]!=uid:raise HTTPException(403,"You can only delete messages you sent")
  other_id=m["recipient_id"]
  if m["attachment_path"] and os.path.exists(m["attachment_path"]):
   try:os.remove(m["attachment_path"])
   except OSError:pass
  c.execute("DELETE FROM message_translations WHERE message_id=?",(message_id,))
  c.execute("DELETE FROM messages WHERE id=?",(message_id,))
 await push(other_id,{"type":"message_deleted","message_id":message_id})
 await push(uid,{"type":"message_deleted","message_id":message_id})
 return {"deleted":True}
@app.websocket("/ws")
async def websocket(ws:WebSocket,access_token:str):
 try:uid=decode(access_token)
 except HTTPException:await ws.close(code=1008);return
 await ws.accept();connections[uid].add(ws)
 try:
  while True:await ws.receive_text()
 except WebSocketDisconnect:connections[uid].discard(ws)
