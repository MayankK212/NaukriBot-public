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

import html
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


def _esc(value):
    return html.escape(str(value if value is not None else ""))


def _build_html(results, scraped_count, untouched=0, rejected_jobs=None):
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
            f"<i>{_esc(k)}</i> → {_esc(v)}" for k, v in qa.items()
        ) if qa else "<span style='color:#9aa0a6'>—</span>"
        reason = r.get("reason") or ""
        if reason:
            reason_html = (f"<div style='color:#b06000;font-weight:600;margin-bottom:5px;'>"
                           f"⚠️ {_esc(reason)}</div>")
        else:
            reason_html = ""
        rows.append(f"""
          <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;">
              <b>{_esc(r.get('title',''))}</b><br>
              <span style="color:#5f6368;">{_esc(r.get('company',''))} · {_esc(r.get('location',''))}</span><br>
              <a href="{r.get('link','')}" style="color:#1a73e8;font-size:12px;">Job link</a>
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;color:{colour};font-weight:600;white-space:nowrap;">
              {label}
            </td>
            <td style="padding:8px;border-bottom:1px solid #eee;font-size:12px;color:#3c4043;">
              {reason_html}{qa_html}
            </td>
          </tr>""")

    # --- Rejected-by-resume-match section ---
    rej = rejected_jobs or []
    rejected_section = ""
    if rej:
        MAX_REJECTED_DISPLAY = 200
        shown = rej[:MAX_REJECTED_DISPLAY]
        extra = len(rej) - MAX_REJECTED_DISPLAY
        rej_rows = []
        for r in shown:
            rej_rows.append(
                f"<tr>"
                f"<td style='padding:6px 8px;border-bottom:1px solid #eee;'><b>{_esc(r.get('title',''))}</b> "
                f"<span style='color:#5f6368;'>— {_esc(r.get('company',''))} · {_esc(r.get('location',''))}</span></td>"
                f"<td style='padding:6px 8px;border-bottom:1px solid #eee;font-size:12px;color:#c5221f;'>"
                f"{_esc(r.get('reason',''))}</td>"
                f"</tr>")
        more_note = f"<p style='color:#5f6368;margin:4px 0 0 0;'>…and {extra} more rejected jobs not shown.</p>" if extra else ""
        rejected_section = f"""
      <h3 style='margin-top:24px;'>🚫 Rejected by resume match ({len(rej)})</h3>
      <table style='border-collapse:collapse;width:100%;max-width:760px;'>
        <thead>
          <tr style='text-align:left;background:#fce8e6;'>
            <th style='padding:8px;'>Job</th>
            <th style='padding:8px;'>Reason</th>
          </tr>
        </thead>
        <tbody>{''.join(rej_rows)}</tbody>
      </table>
      {more_note}"""

    today = datetime.now().strftime("%d %b %Y, %I:%M %p")
    untouched_html = ""
    if untouched:
        untouched_html = (f"<p style='color:#b06000;'><b>⏳ {untouched} job(s)</b> still "
                          f"pending — not reached this run (run cap / time budget / "
                          f"Naukri apply limit). They'll be auto-applied next run.</p>")
    return f"""
    <html><body style="font-family:Arial,Helvetica,sans-serif;color:#202124;">
      <h2 style="margin-bottom:4px;">🤖 JobBot Daily Report</h2>
      <p style="color:#5f6368;margin-top:0;">{today}</p>
      <p><b>{scraped_count}</b> new jobs scraped · <b>{len(results)}</b> processed<br>
         <span style="color:#5f6368;">{summary_bits}</span></p>
      {untouched_html}
      <table style="border-collapse:collapse;width:100%;max-width:760px;">
        <thead>
          <tr style="text-align:left;background:#f1f3f4;">
            <th style="padding:8px;">Job</th>
            <th style="padding:8px;">Status</th>
            <th style="padding:8px;">Why not applied / Q&amp;A</th>
          </tr>
        </thead>
        <tbody>{''.join(rows) if rows else '<tr><td style="padding:8px;">No pending jobs today.</td></tr>'}</tbody>
      </table>
      {rejected_section}
      <p style="color:#9aa0a6;font-size:12px;margin-top:16px;">Sent automatically by JobBot.</p>
    </body></html>"""


def send_status_email(results, scraped_count=0, untouched=0, rejected_jobs=None):
    """Sends the daily HTML report. Returns True on success, False otherwise.

    untouched = pending jobs not reached this run (cap/budget/apply wall) —
    shown as a summary line so the user knows the pipeline isn't stuck.
    rejected_jobs = jobs dropped by the resume<->JD relevance gate in the scraper
    (never saved to pending_jobs) — listed with one-line rejection reasons."""
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
    msg.add_alternative(_build_html(results, scraped_count, untouched, rejected_jobs), subtype="html")

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


# ----------------------------------------------------------------------
# Separate "scrape selection" report — explains WHY each job went into
# pending_jobs (or was rejected), so the user can sanity-check the gate.
# ----------------------------------------------------------------------

def _basis_summary_html():
    """One block explaining the selection/rejection rule that ran."""
    from relevance import get_min_skills, matching_enabled, fetch_detail_enabled
    if not matching_enabled():
        note = ("Relevance matching is currently <b>OFF</b> (no skills in the "
                "profile or <code>JD_MIN_MATCHED_SKILLS=0</code>) — every new "
                "job is kept.")
    else:
        min_skills = get_min_skills()
        note = (f"Relevance matching <b>ON</b> — keep a job if <b>≥{min_skills} "
                f"of your skills</b> appear in its JD/keyskills, <b>or</b> at "
                f"least 1 skill <b>plus</b> a role match (title/description "
                f"mentions one of your search roles). Detail pages fetched for "
                f"scoring: {fetch_detail_enabled()}.")
    return f"""
    <div style="background:#e8f0fe;border-left:4px solid #1a73e8;padding:10px 14px;border-radius:8px;font-size:13px;color:#174ea6;">
      <b>🎯 How jobs were selected / rejected</b><br>{note}
      <div style="margin-top:6px;color:#5f6368;">
        Also applied before the gate: <b>location filter</b> (job city must match
        a preferred location; Remote/WFH/NCR handled) and <b>de-dup</b> (a job
        already in pending/applied is skipped silently, not listed here).
      </div>
    </div>"""


def send_selection_email(selected_jobs, rejected_jobs):
    """
    Separate daily email: lists every job the scraper judged this run —
    the ones that went into pending_jobs (with the basis: matched skills,
    role hit, which search query) and the ones rejected by the resume<->JD
    gate (with one-line reasons). Returns True on success.
    """
    if not EMAIL_USER or not EMAIL_PASS:
        print("✉️  Selection email skipped: EMAIL_USER / EMAIL_PASS not set in .env.")
        return False
    if not selected_jobs and not rejected_jobs:
        print("✉️  Selection email skipped: nothing judged this run.")
        return False

    sel = selected_jobs or []
    rej = rejected_jobs or []

    def _basis(j):
        bits = []
        matched = j.get("matched_skills") or []
        if matched:
            bits.append(f"✓ {len(matched)} skill(s): <b>{_esc(', '.join(matched))}</b>")
        else:
            bits.append("✓ 0 skills matched")
        bits.append("🎯 role matched" if j.get("role_hit") else "role not matched")
        if j.get("search_role"):
            bits.append(f"via query <i>{_esc(j.get('search_role'))}</i>")
        return " &nbsp;·&nbsp; ".join(bits)

    sel_rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;'><b>{_esc(j.get('title',''))}</b> "
        f"<span style='color:#5f6368;'>— {_esc(j.get('company',''))} · {_esc(j.get('location',''))}</span><br>"
        f"<a href='{j.get('link','')}' style='color:#1a73e8;font-size:12px;'>Job link</a></td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;font-size:12px;color:#137333;'>{_basis(j)}</td>"
        f"</tr>" for j in sel)

    rej_rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;'><b>{_esc(j.get('title',''))}</b> "
        f"<span style='color:#5f6368;'>— {_esc(j.get('company',''))} · {_esc(j.get('location',''))}</span></td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;font-size:12px;color:#c5221f;'>{_esc(j.get('reason',''))}</td>"
        f"</tr>" for j in rej)

    today = datetime.now().strftime("%d %b %Y, %I:%M %p")
    empty_sel = '<tr><td style="padding:8px;">None this run.</td></tr>'
    empty_rej = '<tr><td style="padding:8px;">None this run.</td></tr>'
    html = f"""
    <html><body style="font-family:Arial,Helvetica,sans-serif;color:#202124;">
      <h2 style="margin-bottom:4px;">🎯 JobBot Scrape Selection Report</h2>
      <p style="color:#5f6368;margin-top:0;">{today} — which jobs were scraped into <code>pending_jobs</code>, and why.</p>
      {_basis_summary_html()}
      <h3 style="margin-top:22px;">✅ Selected → pending_jobs ({len(sel)})</h3>
      <table style="border-collapse:collapse;width:100%;max-width:760px;">
        <thead><tr style="text-align:left;background:#e6f4ea;">
          <th style="padding:8px;">Job</th><th style="padding:8px;">Basis (why kept)</th>
        </tr></thead>
        <tbody>{''.join(sel_rows) if sel_rows else empty_sel}</tbody>
      </table>
      <h3 style="margin-top:24px;">🚫 Rejected by resume match ({len(rej)})</h3>
      <table style="border-collapse:collapse;width:100%;max-width:760px;">
        <thead><tr style="text-align:left;background:#fce8e6;">
          <th style="padding:8px;">Job</th><th style="padding:8px;">Reason</th>
        </tr></thead>
        <tbody>{''.join(rej_rows) if rej_rows else empty_rej}</tbody>
      </table>
      <p style="color:#9aa0a6;font-size:12px;margin-top:16px;">Sent automatically by JobBot.</p>
    </body></html>"""

    subject = (f"JobBot: {len(sel)} scraped → pending · {len(rej)} rejected "
               f"· {datetime.now().strftime('%d %b')}")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg.set_content(
        f"{len(sel)} jobs selected into pending_jobs, {len(rej)} rejected. "
        "Open in an HTML-capable client for the selection basis."
    )
    msg.add_alternative(html, subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, context=context) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print(f"✉️  Selection email sent to {EMAIL_TO}.")
        return True
    except Exception as exc:
        print(f"✉️  Selection email FAILED: {exc}")
        return False


if __name__ == "__main__":
    # Quick manual test with dummy data.
    demo = [
        {"title": "Game Data Analyst", "company": "Acme Games", "location": "noida",
         "link": "https://naukri.com/x", "status": "applied",
         "reason": None, "questions_and_answers": {"Experience?": "6", "Notice period?": "60 days"}},
        {"title": "Game Developer", "company": "Studio Z", "location": "remote",
         "link": "https://naukri.com/y", "status": "apply_manually",
         "reason": "Apply on company site (external redirect)",
         "questions_and_answers": {}},
        {"title": "BI Engineer", "company": "Data Co", "location": "gurgaon",
         "link": "https://naukri.com/z", "status": "needs_review",
         "reason": "Hard screening question - needs manual review: Years of PySpark?",
         "questions_and_answers": {"Years of PySpark?": "[needs manual review]"}},
    ]
    demo_rejected = [
        {"title": "Java Backend Dev", "company": "TechCorp", "location": "bangalore",
         "reason": "No resume skills or role matched in the JD"},
        {"title": "ML Engineer", "company": "AI Labs", "location": "remote",
         "reason": "Only 1/3 resume skills matched - no role match"},
    ]
    send_status_email(demo, scraped_count=12, untouched=7, rejected_jobs=demo_rejected)

    # Separate selection-basis report demo.
    demo_selected = [
        {"title": "Game Data Analyst", "company": "Acme Games", "location": "noida",
         "link": "https://naukri.com/x", "search_role": "Data Analyst",
         "score": 4, "matched_skills": ["python", "sql", "excel", "power bi"],
         "role_hit": True, "min_skills": 3},
        {"title": "BI Engineer", "company": "Data Co", "location": "gurgaon",
         "link": "https://naukri.com/z", "search_role": "Business Intelligence Engineer",
         "score": 3, "matched_skills": ["sql", "power bi", "etl pipeline"],
         "role_hit": True, "min_skills": 3},
        {"title": "Analyst (2 skills + role)", "company": "Insights Ltd", "location": "remote",
         "link": "https://naukri.com/a", "search_role": "Analytics Manager",
         "score": 2, "matched_skills": ["excel", "sql"],
         "role_hit": True, "min_skills": 3},
    ]
    send_selection_email(demo_selected, demo_rejected)
