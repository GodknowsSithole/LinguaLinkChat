"""Capture real UI evidence screenshots of the prototype (Edge via Playwright)."""
import os, time
from playwright.sync_api import sync_playwright
OUT = os.path.join(os.path.dirname(__file__), "..", "assignments", "screenshots"); os.makedirs(OUT, exist_ok=True)
URL = "http://localhost:3000"; PW = "Demo@12345"
S = lambda n: os.path.join(OUT, n)

def login(page, who, pw=PW):
    page.goto(URL); page.wait_for_selector("input[placeholder=Email]")
    page.fill("input[placeholder=Email]", f"{who}@lingualink.example.com"); page.fill("input[placeholder^=Password]", pw)
    page.click("button:has-text('Log in')")

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True, args=["--disable-gpu","--disable-software-rasterizer"])
    a = b.new_context(viewport={"width": 1280, "height": 760}); pa = a.new_page()
    pa.goto(URL); pa.wait_for_selector("input[placeholder=Email]"); pa.screenshot(path=S("01_login.png"))
    login(pa, "thandi", "wrong-password"); pa.wait_for_timeout(1500); pa.screenshot(path=S("02_login_error.png"))
    login(pa, "thandi"); pa.wait_for_selector("button.person"); pa.click("button.person:has-text('Sipho')"); pa.wait_for_timeout(1500)
    pa.screenshot(path=S("03_thandi_history.png"))
    c = b.new_context(viewport={"width": 1280, "height": 760}); pc = c.new_page()
    login(pc, "sipho"); pc.wait_for_selector("button.person"); pc.click("button.person:has-text('Thandi')"); pc.wait_for_timeout(1500)
    msg = "Please bring your identity document to the clinic on Monday."
    pa.fill("form.composer input:not([type=file])", msg); t0 = time.time(); pa.click("button:has-text('Send')")
    pc.wait_for_selector("text=/Monday|Msombuluko/", timeout=240000); print("delivered in", round(time.time() - t0, 2), "s")
    pa.wait_for_timeout(1000)
    pa.screenshot(path=S("04_sender_view_english.png")); pc.screenshot(path=S("05_recipient_view_isizulu.png"))
    b.close()
print(os.listdir(OUT))


