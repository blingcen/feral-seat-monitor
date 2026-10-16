# FERAL Seats Monitor

A GitHub Actions starter project to periodically inspect the public Ticketlink page for MINHO CONCERT `<MEAN : of feral>` on 2026-11-29 and email a notification when the page exposes a clear, enabled FERAL seat/reservation action.

- Target: https://www.ticketlink.co.kr/global/en/product/65790
- Intended recipient: `vlln5330@hotmail.com`
- Subject: `🍇 出現葡萄`
- Schedule: every 5 minutes (best-effort; GitHub may delay scheduled workflows)

## Important limitations

Ticketlink is a dynamic ticketing site. The public page may not expose actual seat inventory until a user opens the seat-selection interface or signs in. This starter only detects explicit enabled actions in the page DOM and requires FERAL/seat context; it may miss inventory that is only available inside a dynamically loaded seat map. It does not bypass login, CAPTCHA, queueing, or other access controls, and it never purchases tickets. Validate the detection against the actual page before relying on it.

## Configure email with GitHub Actions Secrets

In the repository, open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `SMTP_HOST` — SMTP server hostname (for Gmail: `smtp.gmail.com`)
- `SMTP_PORT` — `587`
- `SMTP_USERNAME` — sender email address
- `SMTP_PASSWORD` — SMTP/app password for the sender account; do not commit it to the repository or paste it into chat

The recipient is fixed to `vlln5330@hotmail.com` in the workflow. If using Gmail, use an app password when your account supports it; do not use your normal account password.

## Enable and test

1. Push these files to the `main` branch.
2. Configure the four repository secrets above.
3. Open **Actions → FERAL Seats Monitor** and enable workflows if GitHub prompts you.
4. Run **Run workflow** once manually. The first run may fail if the Ticketlink page blocks automated browsers or if SMTP secrets are missing.
5. Inspect the run logs to confirm what the page exposes. Do not rely on notifications until a real seat availability transition has been tested.

## Accuracy and duplicate notifications

This starter is intentionally conservative but is not yet a verified inventory API integration. It does not guarantee detection or prevent repeated emails if the page keeps exposing the same enabled action. Those features should be added only after confirming a stable, legitimate availability signal on Ticketlink.
