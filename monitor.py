"""Ticketlink multi-event public-page monitor.

Only public, explicitly stated numeric availability can be classified as available.
Dynamic seat-map inventories require an independently validated, authorized adapter.
Never signs in, bypasses queues/captcha, selects seats or purchases tickets.
"""
import json
import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "monitor-config.json"
TZ = ZoneInfo("Asia/Taipei")
# Intentionally conservative: only explicit English/Korean counts are parsed.
COUNT_PATTERNS = [
    re.compile(r"(?:available seats?|remaining seats?)\s*[:：]?\s*(\d{1,5})", re.I),
    re.compile(r"(?:잔여석|남은 좌석)\s*[:：]?\s*(\d{1,5})", re.I),
]

def valid_url(value):
    try:
        u = urlparse(value)
        return u.scheme == "https" and u.hostname in {"www.ticketlink.co.kr", "ticketlink.co.kr"} and u.username is None and u.password is None and u.port in (None, 443)
    except (ValueError, TypeError):
        return False

def load_config():
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not isinstance(data.get("events"), list):
        raise ValueError("Config requires an events list")
    return data

def should_run(event, now):
    interval = int(event.get("interval_minutes", 5))
    if interval not in (5, 10, 15, 30):
        raise ValueError("Interval must be 5, 10, 15 or 30")
    return (now.minute // 5) % (interval // 5) == 0

def inspect(browser, event):
    url = event.get("schedule_url") or event["url"]
    if not valid_url(url) or not valid_url(event["url"]):
        return {"status": "error", "reason": "Invalid Ticketlink URL"}
    page = browser.new_page(locale="en-US", timezone_id="Asia/Seoul")
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        body = page.locator("body").inner_text(timeout=10000)
        title = page.title()
        http = response.status if response else None
        if http != 200:
            return {"status": "unknown", "reason": f"HTTP {http}", "http": http, "source_url": url}
        if re.search(r"captcha|verify you are human|접근이 제한|access denied", body, re.I):
            return {"status": "unknown", "reason": "Access verification required", "source_url": url}
        keywords = [x.strip() for x in event.get("seat_keywords", []) if isinstance(x, str) and x.strip()]
        matches = []
        for line in body.splitlines():
            line = " ".join(line.split())
            if not line:
                continue
            if keywords and not any(k.casefold() in line.casefold() for k in keywords):
                continue
            for pattern in COUNT_PATTERNS:
                m = pattern.search(line)
                if m:
                    matches.append({"label": line[:160], "count": int(m.group(1))})
                    break
        # Generic count lines can indicate a whole event, not the requested seat type.
        # We do not claim a particular area is available unless its label is on the same line.
        if matches:
            count = sum(x["count"] for x in matches)
            return {"status": "unverified_count", "count": count,
                    "matches": matches[:20], "title": title, "http": http, "source_url": url,
                    "reason": "Public page displays numeric counts; seat selectability is NOT verified"}
        return {"status": "unknown", "reason": "No verifiable numeric seat inventory in public page",
                "title": title, "http": http, "source_url": url}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:300], "source_url": url}
    finally:
        page.close()

def send_email(to, subject, body):
    required = ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")
    if not all(os.environ.get(k) for k in required):
        print("Email skipped: SMTP secrets not configured")
        return False
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_USERNAME"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=30) as server:
        server.starttls()
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)
    return True

def main():
    config = load_config()
    now = datetime.now(TZ)
    if not config.get("enabled", True):
        print("All monitoring paused")
        return
    report = {"checked_at": now.isoformat(), "events": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for event in config["events"][:30]:
                if not event.get("enabled", True):
                    continue
                if not should_run(event, now) and os.environ.get("FORCE_CHECK") != "1":
                    continue
                result = inspect(browser, event)
                if result.get("status") == "unknown" and event.get("schedule_url"):
                    fallback = dict(event)
                    fallback["schedule_url"] = ""
                    product_result = inspect(browser, fallback)
                    if product_result.get("status") == "unverified_count":
                        result = product_result
                    else:
                        result["product_page_status"] = product_result.get("status")
                        result["product_page_reason"] = product_result.get("reason")
                item = {"id": event.get("id"), "name": event.get("name"),
                        "url": event.get("url"), **result}
                report["events"].append(item)
                print(json.dumps(item, ensure_ascii=False))
                # Explicit numeric counts alone are not sufficient to prove seat selectability.
                # Do not email unverified availability as if it were purchasable inventory.
        finally:
            browser.close()
    output = ROOT / "monitor-results.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["## Ticketlink monitor", "", "| 活動 | 狀態 | 說明 |", "|---|---|---|"]
        for x in report["events"]:
            lines.append(f"| {str(x.get('name', '')).replace('|', '/')} | {x['status']} | {str(x.get('reason', '')).replace('|', '/')} |")
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()
