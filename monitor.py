import os
import re
import smtplib
import hashlib
from email.message import EmailMessage
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://www.ticketlink.co.kr/global/en/product/65790"
TARGET_DATE = "2026/11/29"
TZ = ZoneInfo("Asia/Taipei")

# Only notify when the page exposes a clear, enabled seat/reservation action.
# Ticketlink may render seat availability dynamically or require a logged-in session;
# this script intentionally does not bypass authentication, CAPTCHA, or access controls.
ACTION_WORDS = re.compile(r"(select seat|available seat|book now|reserve|purchase|예매하기|좌석 선택|예약하기|구매하기)", re.I)
DISABLED_WORDS = re.compile(r"(sold out|unavailable|매진|판매 종료|예매 종료)", re.I)
AREA_WORDS = re.compile(r"(FERAL|페럴|페럴석|floor|section|area|zone|석|구역)", re.I)


def inspect_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="en-US", timezone_id="Asia/Seoul")
        try:
            response = page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)
            # Wait briefly for client-rendered ticket UI, without interacting with purchase flows.
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
                    text = " ".join(el.inner_text(timeout=500).split())
                    if not text or not ACTION_WORDS.search(text):
                        continue
                    disabled = el.get_attribute("disabled") is not None or el.get_attribute("aria-disabled") == "true"
                    cls = (el.get_attribute("class") or "").lower()
                    if disabled or "disabled" in cls or DISABLED_WORDS.search(text):
                        continue
                    actions.append(text[:160])
                except Exception:
                    continue
            # Require an explicit seat/section label alongside an enabled reservation action.
            # Generic page-level "Book" text alone is not enough to trigger an email.
            areas = sorted({a for a in actions if AREA_WORDS.search(a)})
            explicit_seat_context = bool(re.search(r"(FERAL|페럴).{0,80}(seat|석|section|zone|구역)|(seat|석|section|zone|구역).{0,80}(FERAL|페럴)", body, re.I | re.S))
            available = bool(areas and explicit_seat_context)
            status = response.status if response else None
            browser.close()
            return {
                "available": available,
                "areas": areas,
                "status": status,
                "title": title,
                "diagnostic": " | ".join(actions[:12]),
                "body_excerpt": body[:1800],
            }
        finally:
            try:
                browser.close()
            except Exception:
                pass


def send_email(subject, body):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    recipient = os.environ.get("EMAIL_TO", "vlln5330@hotmail.com")
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
    result = inspect_page()
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"Checked at {now}; HTTP={result['status']}; title={result['title']!r}; available={result['available']}")
    print(f"Detected action labels: {result['diagnostic']}")
    if result["available"]:
        areas = "\n".join(f"- {x}" for x in result["areas"])
        body = (
            f"偵測到 Ticketlink 頁面可能出現可購買的 FERAL 座位，請立即自行確認並完成購票。\n\n"
            f"演出日期：{TARGET_DATE}\n檢查時間（台北）：{now}\n"
            f"偵測到的區域／按鈕：\n{areas}\n\n購票連結：{URL}\n\n"
            "注意：這是自動偵測結果，請以 Ticketlink 實際購票頁面為準；本程式不會自動登入或購票。"
        )
        # Workflow-level concurrency and a persisted fingerprint are not available in this starter.
        # The workflow below uses a repository variable to avoid duplicate notifications only after setup.
        send_email("🍇 出現葡萄", body)


if __name__ == "__main__":
    main()
