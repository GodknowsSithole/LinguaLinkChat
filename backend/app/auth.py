import os, jwt
from datetime import datetime,timedelta,timezone
from pwdlib import PasswordHash
from fastapi import HTTPException,Depends
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
SECRET=os.getenv("JWT_SECRET","change-this-development-secret")
ph=PasswordHash.recommended(); bearer=HTTPBearer()
def hash_password(p): return ph.hash(p)
def verify_password(p,h): return ph.verify(p,h)
def token(uid): return jwt.encode({"sub":str(uid),"exp":datetime.now(timezone.utc)+timedelta(days=7)},SECRET,algorithm="HS256")
def decode(t):
 try:return int(jwt.decode(t,SECRET,algorithms=["HS256"])["sub"])
 except Exception: raise HTTPException(401,"Invalid or expired token")
def current_user_id(c:HTTPAuthorizationCredentials=Depends(bearer)): return decode(c.credentials)
