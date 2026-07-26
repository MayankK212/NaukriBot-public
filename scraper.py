import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from database import _get_db_objects, get_resume_data, job_fingerprint
from browser_setup import launch_browser, new_context

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

APPLIED_JSON_PATH = Path(__file__).with_name("applied_jobs.json")


def _load_existing_index(db):
    """
    Builds a de-dup index of every job already known to the system, so the
    scraper never re-inserts a duplicate. Matches on EITHER the exact link OR
    the content fingerprint (title/company/location/salary/rating), so a job
    with a changed link but identical details is still recognised.

    Sources: pending_jobs, applied_jobs, applied_jobs.json.
    Returns (links_set, fingerprints_set).
    """
    links = set()
    fingerprints = set()

    def _index(doc):
        if doc.get("link"):
            links.add(doc["link"])
        fingerprints.add(job_fingerprint(doc))

    for coll in ("pending_jobs", "applied_jobs"):
        try:
            for doc in db[coll].find({}):
                _index(doc)
        except Exception:
            pass

    if APPLIED_JSON_PATH.exists():
        try:
            with APPLIED_JSON_PATH.open("r", encoding="utf-8") as f:
                for job in json.load(f):
                    _index(job)
        except Exception:
            pass

    return links, fingerprints


def _slugify(value):
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _get_search_roles(resume):
    """
    Returns the list of roles/keywords to search on Naukri.
    Priority: resume['search_roles'] (a list) if provided; otherwise just the
    resume's current_role. Duplicates (case-insensitive) removed, order kept.
    """
    configured = resume.get("search_roles")
    if isinstance(configured, list) and any(str(r).strip() for r in configured):
        raw = [str(r).strip() for r in configured if str(r).strip()]
    else:
        raw = []
        current = (resume.get("current_role") or "").strip()
        if current:
            raw.append(current)

    seen, roles = set(), []
    for r in raw:
        key = r.lower()
        if key not in seen:
            seen.add(key)
            roles.append(r)
    return roles


def _get_locations(resume):
    """
    Locations to search in. Priority: resume['preferred_locations'] (list),
    else [current_location], else [None] (no location filter).
    """
    prefs = resume.get("preferred_locations")
    if isinstance(prefs, list) and any(str(l).strip() for l in prefs):
        return [str(l).strip() for l in prefs if str(l).strip()]
    current = (resume.get("current_location") or "").strip()
    return [current] if current else [None]


def _get_experience(resume):
    """Years of experience as an int for Naukri's `experience` filter, or None."""
    try:
        return int(float(str(resume.get("experience_years")).split()[0]))
    except (TypeError, ValueError):
        return None


def _build_search_url(role, page_no=1, location=None, experience=None):
    """
    Builds a Naukri search URL for a role, optionally filtered by location and
    experience. Naukri patterns:
      role only        -> /<role>-jobs
      role + location  -> /<role>-jobs-in-<city>
      pagination       -> append '-<n>'
      experience       -> ?experience=<years>
      freshness sort   -> ?sort=f (newest first)
    """
    slug = _slugify(role)
    loc_slug = _slugify(location) if location else ""
    if slug and loc_slug:
        base = f"https://www.naukri.com/{slug}-jobs-in-{loc_slug}"
    elif slug:
        base = f"https://www.naukri.com/{slug}-jobs"
    elif loc_slug:
        base = f"https://www.naukri.com/jobs-in-{loc_slug}"
    else:
        base = "https://www.naukri.com/jobs-in-india"
    if page_no > 1:
        base = f"{base}-{page_no}"
    params = ["sort=f"]
    if experience is not None and str(experience).strip() != "":
        params.append(f"experience={experience}")
    return f"{base}?" + "&".join(params)


def _normalize_text(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _extract_posted(job):
    """Reads the 'posted X ago' freshness label from a job card, if present."""
    selectors = [
        "span.job-post-day",
        "span[class*='job-post-day']",
        "span[class*='fleft']",
        "span[class*='posted']",
    ]
    for selector in selectors:
        el = job.query_selector(selector)
        if not el:
            continue
        text = _normalize_text(el.inner_text())
        if text and any(k in text for k in ("ago", "day", "hour", "just now", "today", "week", "month")):
            return text
    return None


def _freshness_hours(posted_text):
    """
    Converts a freshness label into an approximate age in hours for sorting
    (smaller = more recent). Unknown/blank sorts last.
    """
    t = _normalize_text(posted_text)
    if not t:
        return 10 ** 9
    if "just now" in t or "few" in t or "today" in t:
        return 0
    m = re.search(r"(\d+)\s*\+?\s*(hour|day|week|month)", t)
    if not m:
        return 10 ** 9
    qty = int(m.group(1))
    unit = m.group(2)
    factor = {"hour": 1, "day": 24, "week": 24 * 7, "month": 24 * 30}[unit]
    return qty * factor


def _extract_rating(job):
    selectors = [
        "span.starRating",
        "span[class*='rating']",
        "span[class*='star']",
        "div[class*='rating']",
        "span[aria-label*='rating']",
    ]

    for selector in selectors:
        el = job.query_selector(selector)
        if not el:
            continue
        text = _normalize_text(el.inner_text() or el.get_attribute("aria-label") or "")
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if match:
            return float(match.group(1))

    return None


def _extract_location(job):
    selectors = [
        "span.loc",
        "li.loc",
        "span[class*='loc']",
        "div[class*='loc']",
        "span[title]",
        "div[title]",
    ]

    for selector in selectors:
        el = job.query_selector(selector)
        if not el:
            continue
        text = _normalize_text(el.inner_text() or el.get_attribute("title") or "")
        if text:
            return text

    return _normalize_text(job.inner_text())


def _extract_salary(job):
    selectors = [
        "span.salary",
        "div.salary",
        "li.salary",
        "span[class*='salary']",
        "div[class*='salary']",
        "span[title*='Lacs']",
        "span[title*='Lakhs']",
        "span[title*='PA']",
    ]

    for selector in selectors:
        el = job.query_selector(selector)
        if not el:
            continue
        text = _normalize_text(el.inner_text() or el.get_attribute("title") or "")
        if text:
            return text

    text = _normalize_text(job.inner_text())
    if text:
        salary_match = re.search(r"(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*(?:lacs|lakhs|k|thousand|crore|cr|lac|l)\s*(?:pa|per annum)?)", text)
        if salary_match:
            return salary_match.group(1)

    return None


# City aliases so different spellings match the same place.
_CITY_ALIASES = {
    "gurgaon": {"gurgaon", "gurugram"},
    "gurugram": {"gurgaon", "gurugram"},
    "bangalore": {"bangalore", "bengaluru"},
    "bengaluru": {"bangalore", "bengaluru"},
    "mumbai": {"mumbai", "bombay", "navi mumbai"},
    "delhi": {"delhi", "new delhi"},
    "new delhi": {"delhi", "new delhi"},
}
_NCR_CITIES = {"noida", "greater noida", "gurgaon", "gurugram",
               "ghaziabad", "faridabad", "delhi", "new delhi"}
_REMOTE_TERMS = ("remote", "work from home", "wfh", "anywhere")


def _matches_location(location_text, preferred=None):
    """
    True if the job's location matches ANY preferred location.

    Naukri often lists several cities in one string ("Noida, Bengaluru,
    Hyderabad" or "Gurgaon/Remote"), so we do a token/substring match instead
    of an exact compare. Handles city aliases (Gurgaon=Gurugram,
    Bangalore=Bengaluru), Remote/WFH, and broad "Delhi NCR" preferences.
    """
    if not preferred:
        return True                      # no preference set → keep everything
    jl = _normalize_text(location_text)
    if not jl:
        return True                      # unknown location → don't drop the job

    for pref in preferred:
        pl = _normalize_text(pref)
        if not pl:
            continue
        # Remote preference
        if pl in ("remote", "work from home", "wfh"):
            if any(term in jl for term in _REMOTE_TERMS):
                return True
            continue
        # Broad NCR preference → match any NCR city
        if "ncr" in pl:
            if "ncr" in jl or any(city in jl for city in _NCR_CITIES):
                return True
            continue
        # Preferred is a specific NCR city → also match broad "NCR"/"Delhi NCR"
        # listings (the region includes that city).
        if pl in _NCR_CITIES and "ncr" in jl:
            return True
        # Specific city (with spelling aliases)
        for variant in _CITY_ALIASES.get(pl, {pl}):
            if variant in jl:
                return True
    return False


DEBUG_DIR = Path(__file__).with_name("debug")


def _diagnose_empty_page(page, role, page_number):
    """
    When a page yields zero job cards, log WHY (login wall / captcha / block)
    and dump the full HTML + screenshot to debug/ (uploaded as a CI artifact).
    """
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        body = (page.inner_text("body") or "")
    except Exception:
        body = ""
    low = body.lower()

    if any(k in low for k in ("login", "sign in", "log in", "otp")):
        signal = "LOGIN WALL (cookies invalid/expired in CI)"
    elif any(k in low for k in ("captcha", "verify you are", "unusual traffic", "are you a human", "robot")):
        signal = "CAPTCHA / bot challenge"
    elif any(k in low for k in ("access denied", "forbidden", "blocked", "not available in your")):
        signal = "IP BLOCK / access denied"
    elif not body.strip():
        signal = "EMPTY BODY (page didn't render)"
    else:
        signal = "NO CARDS (unexpected layout)"

    print(f"      🔎 0 cards — title={title!r} → {signal}")
    print(f"      body[:200]={body[:200]!r}")

    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        base = DEBUG_DIR / f"scrape_empty_{_slugify(role)}_p{page_number}"
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        except Exception:
            pass
        print(f"      🐞 Saved {base}.html (download from the run's artifacts)")
    except Exception as exc:
        print(f"      🐞 Debug dump failed: {exc}")


def _extract_jobs_from_page(page, limit=None):
    jobs = page.query_selector_all("div.srp-jobtuple-wrapper")
    if not jobs:
        jobs = page.query_selector_all("article")

    job_list = []

    for job in jobs:
        if limit is not None and len(job_list) >= limit:
            break
        title_el = job.query_selector("a.title")
        company_el = job.query_selector("a.comp-name")
        if not title_el:
            continue

        title = title_el.inner_text().strip() if title_el else ""
        link = title_el.get_attribute("href") if title_el else None
        company = company_el.inner_text().strip() if company_el else ""
        rating = _extract_rating(job)
        location = _extract_location(job)
        salary = _extract_salary(job)
        posted = _extract_posted(job)

        if not _matches_location(location):
            continue

        job_list.append({
            "title": title,
            "link": link,
            "company": company,
            "rating": rating,
            "location": location,
            "salary": salary,
            "posted": posted,
            "status": "pending",
        })

    return job_list


def _safe_go_to(page, url):
    page.set_default_timeout(90000)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        return True
    except Exception as exc:
        print(f"Initial navigation failed for {url}: {exc}")

    fallback_urls = ["https://www.naukri.com/jobs-in-india", "https://www.naukri.com/"]
    for fallback_url in fallback_urls:
        try:
            page.goto(fallback_url, wait_until="domcontentloaded", timeout=90000)
            print(f"Loaded fallback page: {fallback_url}")
            return True
        except Exception as fallback_exc:
            print(f"Fallback also failed for {fallback_url}: {fallback_exc}")

    return False


def scrape_naukri(roles=None, max_pages=10, max_jobs_per_role=10):
    resume = get_resume_data()
    if not resume:
        raise RuntimeError("No resume data found. Parse a resume first.")

    search_roles = roles if roles else _get_search_roles(resume)
    locations = _get_locations(resume)
    experience = _get_experience(resume)
    print(f"Searching Naukri | roles={search_roles} | "
          f"locations={locations} | experience={experience}")

    with sync_playwright() as p:
        browser = launch_browser(p)
        context = new_context(browser)

        with open("cookies.json", "r") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)

        page = context.new_page()

        # DIAGNOSTIC: what public IP does the browser actually egress from?
        # (ipify is not behind Akamai, so it answers regardless of the block.)
        #   - phone's residential IP  → proxy works; if Naukri still blocks it,
        #     the phone is likely on MOBILE DATA (use home WiFi instead).
        #   - a datacenter IP         → proxy NOT routing via the phone.
        try:
            page.goto("https://api.ipify.org?format=text",
                      wait_until="domcontentloaded", timeout=20000)
            egress_ip = (page.inner_text("body") or "").strip()
            print(f"🌍 Browser egress IP (as websites see it): {egress_ip}")
        except Exception as exc:
            print(f"🌍 Could not determine egress IP: {exc}")

        _, db, _ = _get_db_objects()  # (client, db, resume_collection)

        # Everything already in pending_jobs / applied_jobs / applied_jobs.json.
        existing_links, existing_fps = _load_existing_index(db)

        job_list = []
        seen_links = set()   # de-dup within this scrape run too
        seen_fps = set()
        # Real preferred locations (drop the None placeholder) for filtering.
        preferred_locs = [l for l in locations if l]

        # ---- Search each role × location, deduping across all of them ----
        for role in search_roles:
            for location in locations:
                where = location or "anywhere"
                print(f"\n🎯 Role: {role} | 📍 {where} | exp={experience}")
                combo_count = 0
                empty_pages = 0

                for page_number in range(1, max_pages + 1):
                    if combo_count >= max_jobs_per_role:
                        break

                    page_url = _build_search_url(role, page_number, location, experience)
                    print(f"   → Page {page_number}: {page_url}")
                    if not _safe_go_to(page, page_url):
                        print(f"      ⚠️ Could not load page {page_number}, next combo.")
                        break

                    # Wait for job cards to render (SPA), fall back to a fixed wait.
                    try:
                        page.wait_for_selector("div.srp-jobtuple-wrapper, article",
                                               timeout=20000)
                    except Exception:
                        page.wait_for_timeout(4000)

                    page_jobs = _extract_jobs_from_page(page)
                    if not page_jobs:
                        _diagnose_empty_page(page, role, page_number)
                        empty_pages += 1
                        if empty_pages >= 2:
                            print(f"      ℹ️ No more listings for {role} in {where}.")
                            break
                        continue
                    empty_pages = 0

                    # Client-side location filter: keep only jobs whose (often
                    # multi-city) location matches ANY preferred location.
                    if preferred_locs:
                        kept = [j for j in page_jobs
                                if _matches_location(j.get("location"), preferred_locs)]
                        if len(kept) != len(page_jobs):
                            print(f"      🧭 location filter: kept {len(kept)}/{len(page_jobs)}")
                        page_jobs = kept

                    new_on_page = 0
                    for job in page_jobs:
                        link = job.get("link")
                        fp = job_fingerprint(job)
                        # Skip if link OR content fingerprint already exists
                        # anywhere, or was already collected in this run.
                        if link and (link in existing_links or link in seen_links):
                            continue
                        if fp in existing_fps or fp in seen_fps:
                            continue
                        if link:
                            seen_links.add(link)
                        seen_fps.add(fp)
                        job["search_role"] = role       # which query surfaced this job
                        job["search_location"] = location
                        job_list.append(job)
                        new_on_page += 1
                        combo_count += 1
                        if combo_count >= max_jobs_per_role:
                            break

                    print(f"      ✓ {new_on_page} new / {len(page_jobs)} on page "
                          f"({combo_count}/{max_jobs_per_role} for this role+location)")

        # Safety net: even though sort=f orders server-side, re-sort locally
        # by posting freshness (newest first) before saving.
        job_list.sort(key=lambda j: _freshness_hours(j.get("posted")))

        if job_list:
            db["pending_jobs"].insert_many(job_list)

        print(f"\nFound {len(job_list)} NEW jobs (newest first) and saved to "
              f"MongoDB (skipped duplicates already in pending/applied).")
        browser.close()

    return len(job_list)


if __name__ == "__main__":
    scrape_naukri()