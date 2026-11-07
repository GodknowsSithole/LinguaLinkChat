"""Prototype test harness for ISJ107V Assignment 4 (Q4.1 / Q4.2).

Runs against a live backend (default http://127.0.0.1:8001) and writes results.json.
Usage:  python tests/run_prototype_tests.py [base_url]
Use a throw-away PostgreSQL database (DATABASE_URL) / UPLOAD_DIR for the server under test.
"""
import asyncio, json, statistics, sys, time, uuid
import requests, websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
WS = BASE.replace("http", "ws")
R = []          # test case results
M = {}          # quantitative measures


def rec(tc, name, expected, actual, ok):
    R.append({"id": tc, "name": name, "expected": expected, "actual": actual, "status": "Pass" if ok else "Fail"})
    print(f"{tc} {'PASS' if ok else 'FAIL'} - {name}: {actual}")


def reg(name, lang, pw="Passw0rd!23"):
    email = f"{name.lower()}.{uuid.uuid4().hex[:6]}@example.com"
    r = requests.post(f"{BASE}/auth/register", json={"name": name, "email": email, "password": pw, "preferred_language": lang})
    return email, pw, r


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---- Setup: two users with different preferred languages --------------------
ea, pa, ra = reg("Thandi", "eng_Latn")
eb, pb, rb = reg("Sipho", "zul_Latn")
ta, tb = ra.json()["access_token"], rb.json()["access_token"]
ida = requests.get(f"{BASE}/me", headers=H(ta)).json()["id"]
idb = requests.get(f"{BASE}/me", headers=H(tb)).json()["id"]

# TC-01 register / login / me
l = requests.post(f"{BASE}/auth/login", json={"email": ea, "password": pa})
me = requests.get(f"{BASE}/me", headers=H(l.json().get("access_token", "")))
rec("TC-01", "Register and log in", "201/200 + JWT; /me returns profile without password hash",
    f"register={ra.status_code}, login={l.status_code}, /me keys={sorted(me.json().keys())}",
    ra.status_code == 200 and l.status_code == 200 and "password_hash" not in me.json())

# warm the model (first call loads NLLB-200 into memory) and measure cold start
t0 = time.perf_counter()
w = requests.post(f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": "Good morning, how are you today?"})
M["cold_start_first_translation_s"] = round(time.perf_counter() - t0, 2)

# TC-02 main workflow: translation en -> zu
sent = "Hello, I need help with my application form."
t0 = time.perf_counter()
m = requests.post(f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": sent})
dt = time.perf_counter() - t0
j = m.json()
hist = requests.get(f"{BASE}/messages/{ida}", headers=H(tb)).json()
rec("TC-02", "Send message, auto-detect + translate eng->zul (emerging tech)",
    "200; original_language=eng_Latn; recipient text differs from original; stored in history",
    f"status={m.status_code}, lang={j.get('original_language')}, recipient_text='{j.get('display_text')}', history_rows={len(hist)}",
    m.status_code == 200 and j.get("original_language") == "eng_Latn" and j.get("display_text") != sent and len(hist) >= 2)

# TC-03 invalid input
cases = {
    "empty text": requests.post(f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": ""}).status_code,
    "text >3000 chars": requests.post(f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": "a" * 3001}).status_code,
    "short password": requests.post(f"{BASE}/auth/register", json={"name": "Bad", "email": "x@example.com", "password": "123", "preferred_language": "eng_Latn"}).status_code,
    "bad email": requests.post(f"{BASE}/auth/register", json={"name": "Bad", "email": "not-an-email", "password": "Passw0rd!23", "preferred_language": "eng_Latn"}).status_code,
    "unsupported language": requests.post(f"{BASE}/auth/register", json={"name": "Bad", "email": "y@example.com", "password": "Passw0rd!23", "preferred_language": "xxx_Xxxx"}).status_code,
    "duplicate email": requests.post(f"{BASE}/auth/register", json={"name": "Dup", "email": ea, "password": pa, "preferred_language": "eng_Latn"}).status_code,
    "wrong password": requests.post(f"{BASE}/auth/login", json={"email": ea, "password": "wrongpass1"}).status_code,
}
exp = {"empty text": 422, "text >3000 chars": 422, "short password": 422, "bad email": 422, "unsupported language": 400, "duplicate email": 409, "wrong password": 401}
rec("TC-03", "Invalid input is rejected with clear error codes", str(exp), str(cases), cases == exp)

# TC-04 access control
a1 = requests.get(f"{BASE}/me").status_code
a2 = requests.get(f"{BASE}/me", headers=H("garbage.token.value")).status_code
dm = requests.post(f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": "Attachment owner test"}).json()
ec, pc, rc = reg("Intruder", "eng_Latn")
tc_ = rc.json()["access_token"]
up = requests.post(f"{BASE}/messages/document", headers=H(ta), data={"recipient_id": idb},
                   files={"file": ("note.txt", b"Please bring your ID document to the clinic on Monday.", "text/plain")})
att_id = up.json().get("id")
a3 = requests.get(f"{BASE}/attachments/{att_id}", headers=H(tc_)).status_code
a4 = requests.delete(f"{BASE}/message/{dm['id']}", headers=H(tb)).status_code
rec("TC-04", "Access control: no/invalid token, third-party attachment, delete others' message",
    "403 (no bearer), 401, 404, 403", f"{a1}, {a2}, {a3}, {a4}", (a1, a2, a3, a4) in [(403, 401, 404, 403), (401, 401, 404, 403)])

# TC-05 block
requests.post(f"{BASE}/users/{ida}/block", headers=H(tb))
bl = requests.post(f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": "Are you there?"})
requests.post(f"{BASE}/users/{ida}/unblock", headers=H(tb))
rec("TC-05", "Blocked user cannot send message", "403 'You cannot message this user'", f"{bl.status_code} {bl.json().get('detail')}", bl.status_code == 403)

# TC-06 document upload (txt ok / unsupported type rejected / translation on demand)
bad = requests.post(f"{BASE}/messages/document", headers=H(ta), data={"recipient_id": idb}, files={"file": ("virus.exe", b"MZ....", "application/octet-stream")})
t0 = time.perf_counter()
tr = requests.post(f"{BASE}/messages/{att_id}/translate", headers=H(tb))
M["document_translation_s"] = round(time.perf_counter() - t0, 2)
rec("TC-06", "Document upload: .txt accepted & translated on demand; .exe rejected",
    "upload 200; .exe 400; translate 200 with text in recipient language",
    f"upload={up.status_code}, exe={bad.status_code}, translate={tr.status_code}, text='{tr.json().get('display_text','')[:70]}'",
    up.status_code == 200 and bad.status_code == 400 and tr.status_code == 200)

# TC-07 real-time WebSocket delivery
async def ws_test():
    async with websockets.connect(f"{WS}/ws?access_token={tb}", ping_interval=None) as s:
        await asyncio.sleep(0.3)
        t0 = time.perf_counter()
        await asyncio.to_thread(requests.post, f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": "See you at the clinic tomorrow."})
        msg = json.loads(await asyncio.wait_for(s.recv(), 120))
        return msg, time.perf_counter() - t0
msg, wdt = asyncio.run(ws_test())
rec("TC-07", "Real-time delivery over authenticated WebSocket", "recipient receives type=message push with translated text",
    f"type={msg['type']}, text='{msg['message']['display_text']}', {wdt:.2f}s", msg["type"] == "message")
try:
    async def ws_bad():
        async with websockets.connect(f"{WS}/ws?access_token=bad") as s:
            await s.recv()
    asyncio.run(ws_bad()); wsbad = "connected (unexpected)"
except Exception as e:
    wsbad = f"rejected ({type(e).__name__})"
rec("TC-08", "WebSocket with invalid token is rejected", "connection closed (code 1008)", wsbad, wsbad.startswith("rejected"))

# ---- Q4.2 measures ----------------------------------------------------------
phrases = ["Where is the nearest clinic?", "Please send me the form by Friday.", "My child is sick and needs a doctor.",
           "The meeting starts at nine in the morning.", "Thank you for your help today.", "How much does the bus ticket cost?",
           "I would like to open a bank account.", "Can you call me back this afternoon?", "The school closes at three o'clock.",
           "Please bring your identity document.", "We will visit our family next week.", "The water is not working in my street."]
lat = []
for p in phrases:
    t0 = time.perf_counter()
    r = requests.post(f"{BASE}/messages", headers=H(ta), json={"recipient_id": idb, "text": p})
    if r.status_code == 200:
        lat.append(time.perf_counter() - t0)
M["translation_latency_n"] = len(lat)
M["translation_latency_mean_s"] = round(statistics.mean(lat), 2)
M["translation_latency_median_s"] = round(statistics.median(lat), 2)
M["translation_latency_max_s"] = round(max(lat), 2)
M["translation_within_3s_pct"] = round(100 * sum(1 for x in lat if x <= 3) / len(lat), 1)
M["translation_success_pct"] = round(100 * len(lat) / len(phrases), 1)

# cheap endpoints
t0 = time.perf_counter()
for _ in range(20):
    requests.get(f"{BASE}/messages/{idb}", headers=H(ta))
M["history_fetch_mean_ms"] = round((time.perf_counter() - t0) / 20 * 1000, 1)

# language detection accuracy (hand-written labelled set; small, indicative only)
sys.path.insert(0, "backend")
from app.detect import detect_language
LAB = {
 "eng_Latn": ["Where is the nearest clinic?", "I would like to open a bank account.", "Please send me the form by Friday.", "The children are playing outside.", "Thank you for your help today."],
 "afr_Latn": ["Waar is die naaste kliniek?", "Ek wil graag 'n bankrekening oopmaak.", "Die kinders speel buite in die tuin.", "Dankie vir jou hulp vandag.", "Ons gaan volgende week ons familie besoek."],
 "zul_Latn": ["Ikuphi ikliniki eseduze?", "Ngicela ukuvula i-akhawunti ebhange.", "Ngiyabonga kakhulu ngosizo lwakho namuhla.", "Izingane zidlala ngaphandle emnyango.", "Sizovakashela umndeni wethu kusasa."],
 "xho_Latn": ["Iphi ikliniki ekufutshane?", "Ndiyabulela kakhulu ngoncedo lwakho namhlanje.", "Abantwana badlala ngaphandle egadini.", "Ndifuna ukuvula iakhawunti yebhanki.", "Siza kutyelela usapho lwethu ngoMvulo."],
 "sot_Latn": ["Kliniki e haufi e kae?", "Ke leboha thuso ea hau kajeno.", "Bana ba bapala kantle jarateng.", "Ke batla ho bula akhaonto ea banka.", "Re tla etela lelapa la rona beke e tlang."],
 "tsn_Latn": ["Kokelo e e gaufi e kae?", "Ke a leboga thuso ya gago gompieno.", "Bana ba tshameka kwa ntle mo tshimong.", "Ke batla go bula akhaonto ya banka.", "Re tla etela lelapa la rona beke e e tlang."],
 "tso_Latn": ["Ekliniki leyi nga ekusuhi yi kwihi?", "Ndza khensa mpfuno wa wena namuntlha.", "Vana va tlanga ehandle enhoveni.", "Ndzi lava ku pfula akhawunti ya bhanga.", "Hi ta endzela ndyangu wa hina vhiki leyi taka."],
}
tot = ok = 0; per = {}; wrong = []
for lang, ss in LAB.items():
    c = 0
    for s in ss:
        d = detect_language(s); tot += 1
        if d == lang: ok += 1; c += 1
        else: wrong.append((s, lang, d))
    per[lang] = f"{c}/{len(ss)}"
M["lang_detect_accuracy_pct"] = round(100 * ok / tot, 1)
M["lang_detect_n"] = tot
M["lang_detect_per_language"] = per
M["lang_detect_errors"] = wrong
rec("TC-09", "Language detection on labelled sentences (7 languages, 35 sentences)", ">= 90% correct (Assignment 2 objective)",
    f"{ok}/{tot} = {M['lang_detect_accuracy_pct']}%", M["lang_detect_accuracy_pct"] >= 90)

print(json.dumps(M, indent=1))
json.dump({"tests": R, "measures": M}, open("tests/results.json", "w"), indent=1, ensure_ascii=False)


