import json
import os
import re
import smtplib
from email.message import EmailMessage
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://www.ticketlink.co.kr/global/en/product/65790"
TZ = ZoneInfo("Asia/Taipei")
CONFIG_PATH = Path(__file__).with_name("monitor-config.json")
DEFAULT_CONFIG = {"enabled": True, "email": "vlln5330@hotmail.com", "target_date": "2026-11-29", "product_url": URL}

ACTION_WORDS = re.compile(r"(select seat|available seat|book now|reserve|purchase|예매하기|좌석 선택|예약하기|구매하기)", re.I)
DISABLED_WORDS = re.compile(r"(sold out|unavailable|매진|판매 종료|예매 종료)", re.I)
AREA_WORDS = re.compile(r"(FERAL|페럴|페럴석|floor|section|area|zone|석|구역)", re.I)

def load_config():
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **data}
    except Exception as exc:
        print(f"Could not read monitor-config.json; using defaults: {exc}")
        return DEFAULT_CONFIG.copy()

def inspect_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="en-US", timezone_id="Asia/Seoul")
            response = page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass
            title = page.title()
            body = page.locator("body").inner_text(timeout=10000)
            buttons = page.locator("button, a, [role='button']")
            actions = []
            for i in range(min(buttons.count(), 300)):
                el = buttons.nth(i)
                try:
                    label = " ".join(el.inner_text(timeout=500).split())
                    if not label or not ACTION_WORDS.search(label):
                        continue
                    disabled = el.get_attribute("disabled") is not None or el.get_attribute("aria-disabled") == "true"
                    cls = (el.get_attribute("class") or "").lower()
                    if disabled or "disabled" in cls or DISABLED_WORDS.search(label):
                        continue
                    actions.append(label[:160])
                except Exception:
                    continue
            areas = sorted({a for a in actions if AREA_WORDS.search(a)})
            context = bool(re.search(r"(FERAL|페럴).{0,80}(seat|석|section|zone|구역)|(seat|석|section|zone|구역).{0,80}(FERAL|페럴)", body, re.I | re.S))
            return {"available": bool(areas and context), "areas": areas, "status": response.status if response else None,
                    "title": title, "diagnostic": " | ".join(actions[:12]), "body_excerpt": body[:1800]}
        finally:
            browser.close()

def send_email(subject, body, recipient):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    msg = EmailMessage()
    msg["From"] = username
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)

def main():
    config = load_config()
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    if not config.get("enabled", True):
        print(f"Monitoring is paused in monitor-config.json at {now}.")
        return
    result = inspect_page()
    print(f"Checked at {now}; HTTP={result['status']}; title={result['title']!r}; available={result['available']}")
    print(f"Detected action labels: {result['diagnostic']}")
    if result["available"]:
        recipient = (os.environ.get("EMAIL_TO") or config.get("email") or DEFAULT_CONFIG["email"]).strip()
        areas = "\n".join(f"- {x}" for x in result["areas"])
        body = (f"偵測到 Ticketlink 頁面可能出現可購買的 FERAL 座位，請立即自行確認並完成購票。\n\n"
                f"演出日期：{config.get('target_date', '2026-11-29')}\n檢查時間（台北）：{now}\n"
                f"偵測到的區域／按鈕：\n{areas}\n\n購票連結：{config.get('product_url', URL)}\n\n"
                "注意：這是自動偵測結果，請以 Ticketlink 實際購票頁面為準；本程式不會自動登入或購票。")
        if all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")):
            send_email("🍇 出現葡萄", body, recipient)
            print(f"Notification email sent to {recipient}.")
        else:
            print("Potential availability detected, but SMTP secrets are not configured; no email was sent.")

if __name__ == "__main__":
    main()
