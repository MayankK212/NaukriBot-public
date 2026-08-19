"""
JobBot daily orchestrator (fully unattended).

Pipeline:
  1. Scrape fresh, relevant jobs from Naukri into MongoDB `pending_jobs`.
  2. Auto-apply to every pending job (no prompts, auto-submit).
  3. Email a status report of every job processed.

Run manually:
    python run_daily.py

Scheduled daily via Windows Task Scheduler (see setup_schedule.ps1).
"""

import sys
import traceback
from datetime import datetime

# Force UTF-8 stdout/stderr so emoji prints don't crash on Windows cp1252
# (important when output is redirected to a log by Task Scheduler).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from scraper import scrape_naukri
from auto_apply import run_interactive_apply
from emailer import send_status_email, send_selection_email
from database import record_daily_stats


def main():
    started = datetime.now()
    print(f"\n===== JobBot daily run started: {started:%Y-%m-%d %H:%M:%S} =====")

    scraped_count = 0
    rejected_jobs = []  # jobs dropped by the relevance gate (never saved to pending)
    selected_jobs = []  # jobs that passed the gate -> pending_jobs (with the why)
    results = []
    untouched = 0  # pending jobs not reached this run (cap/budget/apply wall)

    # ---- Step 1: scrape ----
    try:
        scraped_count, rejected_jobs, selected_jobs = scrape_naukri() or (0, [], [])
        print(f"[scrape] {scraped_count} new jobs added to pending_jobs.")
    except Exception:
        print("[scrape] FAILED:")
        traceback.print_exc()

    # ---- Step 2: apply (unattended) ----
    try:
        results, untouched = run_interactive_apply(interactive=False) or ([], 0)
        print(f"[apply] processed {len(results)} jobs.")
        # Log apply-phase funnel numbers for the dashboard (daily_stats).
        from collections import Counter
        status_counts = Counter(r.get("status") for r in results if isinstance(r, dict))
        record_daily_stats({
            "applied": status_counts.get("applied", 0) + status_counts.get("already_applied", 0),
            "apply_errors": status_counts.get("error", 0),
            "needs_review": status_counts.get("needs_review", 0),
            "manual": status_counts.get("apply_manually", 0),
        })
    except Exception:
        print("[apply] FAILED:")
        traceback.print_exc()

    # ---- Step 3: email report ----
    # Only email when there's something to report. This lets us schedule several
    # morning attempts (so at least one beats GitHub's cron delays) WITHOUT
    # spamming: the first run that does the work emails; later same-day runs
    # find nothing new and stay silent.
    try:
        if results or scraped_count:
            send_status_email(results, scraped_count=scraped_count, untouched=untouched,
                             rejected_jobs=rejected_jobs)
        else:
            print("[email] Nothing to report (0 scraped, 0 processed) — skipping email.")
    except Exception:
        print("[email] FAILED:")
        traceback.print_exc()

    # ---- Step 4: separate selection-basis email ----
    # Explains WHY each job went into pending_jobs (matched skills / role hit) or
    # was rejected (resume<->JD gate). Sent only when the scrape judged something
    # this run, so same-day no-op runs stay silent.
    try:
        if selected_jobs or rejected_jobs:
            send_selection_email(selected_jobs, rejected_jobs)
        else:
            print("[email] Nothing to judge for selection email — skipping.")
    except Exception:
        print("[selection-email] FAILED:")
        traceback.print_exc()

    elapsed = (datetime.now() - started).total_seconds()
    print(f"===== JobBot daily run finished in {elapsed:.0f}s =====\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
