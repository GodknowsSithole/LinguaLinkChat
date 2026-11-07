"""UI test: change preferred language, then re-translate an older received text message.
Needs the stack running (API :8000, web :3000, PostgreSQL) and the demo data (tests/seed_demo.py).
Run:  python tests/test_retranslate_ui.py
"""
import os, sys, time
from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"; PW = "Demo@12345"
OUT = os.path.join(os.path.dirname(__file__), "..", "assignments", "screenshots"); os.makedirs(OUT, exist_ok=True)
OLD = "Ngiyabonga, sicela ulethe idokhumenti yakho."   # message from Thandi, stored in isiZulu for Sipho

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True, args=["--disable-gpu", "--disable-software-rasterizer"])
    pg = b.new_context(viewport={"width": 1280, "height": 760}).new_page()
    pg.goto(URL); pg.wait_for_selector("input[placeholder=Email]")
    pg.fill("input[placeholder=Email]", "sipho@lingualink.example.com"); pg.fill("input[placeholder^=Password]", PW)
    pg.click("button:has-text('Log in')")
    pg.wait_for_selector("button.person"); pg.click("button.person:has-text('Thandi')")
    pg.wait_for_selector(f"text={OLD}", timeout=60000)
    print("1. Old message shown in isiZulu:", OLD)

    # change preferred language to Sesotho
    pg.select_option(".profile select", label="Sesotho"); pg.wait_for_timeout(1500)
    still_old = pg.locator(f"text={OLD}").count() > 0
    print("2. After language change, old message still in isiZulu (expected, needs re-translate):", still_old)
    pg.screenshot(path=os.path.join(OUT, "06_before_retranslate.png"))

    # open the message menu and choose Re-translate
    bubble = pg.locator(".bubble", has_text=OLD)
    bubble.locator("button.menu-dots").click()
    btn = bubble.locator("button.retranslate-btn"); assert btn.count() == 1, "Re-translate option missing"
    t0 = time.time(); btn.click()
    pg.wait_for_function("t => !document.body.innerText.includes(t)", arg=OLD, timeout=240000)
    secs = time.time() - t0
    pg.wait_for_timeout(1000)
    new_text = pg.locator(".bubble:not(.mine) p").nth(1).inner_text()
    print(f"3. Re-translated in {secs:.1f}s ->", new_text)
    pg.screenshot(path=os.path.join(OUT, "07_after_retranslate.png"))
    # own (sent) messages must not offer the option
    pg.locator(".bubble.mine").first.locator("button.menu-dots").click()
    print("4. Option hidden on own messages:", pg.locator(".bubble.mine button.retranslate-btn").count() == 0)
    ok = (not pg.locator(f"text={OLD}").count()) and new_text != OLD
    print("RESULT:", "PASS" if ok else "FAIL")
    pg.select_option(".profile select", label="isiZulu"); pg.wait_for_timeout(1500)   # restore demo user language
    b.close(); sys.exit(0 if ok else 1)
