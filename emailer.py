"""
Email reporting for the JobBot pipeline.

Sends a daily HTML status report of every job the auto-apply engine processed.
Configuration is read from environment variables (.env):

    EMAIL_USER   = your Gmail address (the sender)
    EMAIL_PASS   = a Google "App Password" (NOT your normal password)
    EMAIL_TO     = recipient address (defaults to EMAIL_USER)
    EMAIL_HOST   = SMTP host   (default: smtp.gmail.com)
    EMAIL_PORT   = SMTP port   (default: 465, SSL)

How to create a Gmail App Password:
  1. Enable 2-Step Verification on your Google account.
  2. Go to https://myaccount.google.com/apppasswords
  3. Create a password for "Mail" → copy the 16-char code into EMAIL_PASS.
"""

import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage

from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

load_dotenv()

# NOTE: use `or` (not getenv defaults) — GitHub Actions injects UNSET secrets as
# empty strings "", which would otherwise override the fallbacks and crash.
EMAIL_USER = os.getenv("EMAIL_USER") or None
EMAIL_PASS = os.getenv("EMAIL_PASS") or None
EMAIL_TO = os.getenv("EMAIL_TO") or EMAIL_USER
EMAIL_HOST = os.getenv("EMAIL_HOST") or "smtp.gmail.com"
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or 465)

# Human-friendly labels + colours for each internal status.
STATUS_META = {
    "applied":         ("✅ Applied", "#137333"),
    "already_applied": ("🔁 Already applied", "#5f6368"),
    "apply_manually":  ("🌐 Apply on company site", "#b06000"),
    "error":           ("⚠️ Apply error (kept pending)", "#c5221f"),
    "needs_review":    ("🟡 Needs manual review (hard Qs)", "#b06000"),
    "user_rejected":   ("🚫 Skipped by user", "#5f6368"),
    "skipped":         ("⏭️ Skipped (no apply button)", "#5f6368"),
    "failed":          ("❌ Failed", "#c5221f"),
    "incomplete":      ("… Incomplete", "#b06000"),
}


def _status_label(status):
    return STATUS_META.get(status, (status, "#5f6368"))


def _build_html(results, scraped_count):
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    summary_bits = ", ".join(
        f"{_status_label(s)[0]}: {n}" for s, n in sorted(counts.items())
    ) or "no jobs processed"

    rows = []
    for r in results:
        label, colour = _status_label(r["status"])
        qa = r.get("questions_and_answers") or {}
        qa_html = "<br>".join(
            f"<i>{k}</i> → {v}" for k, v in qa.items()
        ) if qa else "<span style='color:#9aa0a6'>—</span>"
        rows.append(f"""
          <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;">
              <b>{r.get('title','')}</b><br>
              <span style="color:#5f6368;">{r.get('company','')} · {r.get('location','')}</span><br>
              <a href="{r.get('link','')}" style="color:#1a73e8;font-size:12px;">Job link</a>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;color:{colour};font-weight:600;white-space:nowrap;">
              {label}
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;font-size:12px;color:#3c4043;">
              {qa_html}
            </td>
          </tr>""")

    today = datetime.now().strftime("%d %b %Y, %I:%M %p")
    return f"""
    <html><body style="font-family:Arial,Helvetica,sans-serif;color:#202124;">
      <h2 style="margin-bottom:4px;">🤖 JobBot Daily Report</h2>
      <p style="color:#5f6368;margin-top:0;">{today}</p>
      <p><b>{scraped_count}</b> new jobs scraped · <b>{len(results)}</b> processed<br>
         <span style="color:#5f6368;">{summary_bits}</span></p>
      <table style="border-collapse:collapse;width:100%;max-width:760px;">
        <thead>
          <tr style="text-align:left;background:#f1f3f4;">
            <th style="padding:8px;">Job</th>
            <th style="padding:8px;">Status</th>
            <th style="padding:8px;">Q&amp;A</th>
          </tr>
        </thead>
        <tbody>{''.join(rows) if rows else '<tr><td style="padding:8px;">No pending jobs today.</td></tr>'}</tbody>
      </table>
      <p style="color:#9aa0a6;font-size:12px;margin-top:16px;">Sent automatically by JobBot.</p>
    </body></html>"""


def send_status_email(results, scraped_count=0):
    """Sends the daily HTML report. Returns True on success, False otherwise."""
    if not EMAIL_USER or not EMAIL_PASS:
        print("✉️  Email skipped: EMAIL_USER / EMAIL_PASS not set in .env.")
        return False

    applied = sum(1 for r in results if r["status"] == "applied")
    subject = (f"JobBot: {applied} applied / {len(results)} processed "
               f"· {datetime.now().strftime('%d %b')}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.set_content(
        f"{scraped_count} new jobs scraped, {len(results)} processed, "
        f"{applied} applied. Open in an HTML-capable client for details."
    )
    msg.add_alternative(_build_html(results, scraped_count), subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, context=context) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print(f"✉️  Status email sent to {EMAIL_TO}.")
        return True
    except Exception as exc:
        print(f"✉️  Email FAILED: {exc}")
        return False


if __name__ == "__main__":
    # Quick manual test with dummy data.
    demo = [
        {"title": "Game Data Analyst", "company": "Acme Games", "location": "noida",
         "link": "https://naukri.com/x", "status": "applied",
         "questions_and_answers": {"Experience?": "6", "Notice period?": "60 days"}},
        {"title": "Game Developer", "company": "Studio Z", "location": "remote",
         "link": "https://naukri.com/y", "status": "apply_manually",
         "questions_and_answers": {}},
    ]
    send_status_email(demo, scraped_count=12)
