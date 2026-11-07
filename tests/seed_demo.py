"""Seed realistic demo data through the public API (idempotent).
Usage: python tests/seed_demo.py [base_url]
Demo accounts (password for all: Demo@12345):
  thandi@lingualink.demo  (English)   sipho@lingualink.demo (isiZulu)
  lerato@lingualink.demo  (Sesotho)   pieter@lingualink.demo (Afrikaans)
"""
import sys, requests
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PW = "Demo@12345"
USERS = [("Thandi Mokoena", "thandi", "eng_Latn"), ("Sipho Dlamini", "sipho", "zul_Latn"),
         ("Lerato Molefe", "lerato", "sot_Latn"), ("Pieter van Wyk", "pieter", "afr_Latn")]
tok = {}
for name, key, lang in USERS:
    email = f"{key}@lingualink.demo".replace(".demo", ".example.com")
    r = requests.post(f"{BASE}/auth/register", json={"name": name, "email": email, "password": PW, "preferred_language": lang})
    if r.status_code == 409:
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": PW})
    tok[key] = r.json()["access_token"]
H = lambda k: {"Authorization": f"Bearer {tok[k]}"}
ids = {k: requests.get(f"{BASE}/me", headers=H(k)).json()["id"] for k in tok}
convo = [("thandi", "sipho", "Good morning Sipho, is the clinic open today?"),
         ("sipho", "thandi", "Sawubona Thandi, yebo ivulwe kusukela ngo-8 ekuseni."),
         ("thandi", "sipho", "Thank you. Please bring your identity document."),
         ("pieter", "thandi", "Goeie middag, ek wil graag 'n afspraak maak."),
         ("lerato", "thandi", "Ke leboha thuso ea hau kajeno.")]
existing = requests.get(f"{BASE}/messages/{ids['sipho']}", headers=H("thandi")).json()
if not existing:
    for a, b, t in convo:
        requests.post(f"{BASE}/messages", headers=H(a), json={"recipient_id": ids[b], "text": t}).raise_for_status()
print("Seeded. Demo logins: <name>@lingualink.example.com / " + PW, "->", ", ".join(k for k in tok))
