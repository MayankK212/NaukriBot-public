"""
Resume <-> job description relevance matching for the JobBot scraper.

Pure functions only (no browser, no Mongo) so the logic can be unit-tested
offline with `python test_relevance.py`.

How it works
------------
Each scraped job's description + keyskills are scored against the user's resume
profile (resume_data.json). A job is only scraped when there is real overlap:

  score    = number of the user's skills found in the job text
  role_hit = the job title/description matches one of the user's roles

Keep rule (JD_MIN_MATCHED_SKILLS, default 3):
  score >= min_skills  OR  (score >= 1 AND role_hit)

So a job needs either a solid skills overlap, or at least one skill PLUS a role
match (e.g. a "Senior Data Analyst" posting that mentions Python + SQL).

Tuning (env vars; set in the GitHub workflow or .env):
  JD_MIN_MATCHED_SKILLS   minimum skills overlap to keep a job (0 disables matching)
  JD_FETCH_DETAIL         "true" (default) open each job page for the full JD,
                          "false" score only the search-card snippet (faster)
  JD_MAX_FETCHES          max job-detail pages fetched per scrape run (default 60)

NOT LLM-based on purpose: the free Gemini tier allows ~20 calls/day and that
budget is already reserved for answering screening questions during apply. A
deterministic skill/role scorer handles hundreds of scraped JDs for free.
"""

import os
import re


# ----------------------------------------------------------------------
# Configuration (env-driven, see docstring)
# ----------------------------------------------------------------------
def get_min_skills():
    """Minimum skill overlap required. 0 disables matching entirely."""
    try:
        return int(os.getenv("JD_MIN_MATCHED_SKILLS", "3") or 0)
    except ValueError:
        return 3


def matching_enabled():
    return get_min_skills() > 0


def fetch_detail_enabled():
    """True = open each job page for the full JD (accurate, slower)."""
    return os.getenv("JD_FETCH_DETAIL", "true").strip().lower() in ("1", "true", "yes")


def get_max_fetches():
    """Cap on job-detail pages fetched per scrape run (0 = unlimited)."""
    try:
        return int(os.getenv("JD_MAX_FETCHES", "60") or 0)
    except ValueError:
        return 60


# ----------------------------------------------------------------------
# Skill -> alternative spellings/abbreviations Naukri JDs actually use.
# ("power bi" also appears as "powerbi", "ETL Pipeline" as just "ETL", ...)
# ----------------------------------------------------------------------
_SKILL_ALIASES = {
    "power bi": ("powerbi",),
    "web scraping": ("webscraping", "web-scraping", "web scraper"),
    "ml": ("machine learning",),
    "ai": ("artificial intelligence",),
    "etl pipeline": ("etl", "elt"),
    "data pipeline": ("data pipelines",),
    "sql": ("mysql", "postgresql", "postgres", "t-sql", "tsql", "mssql", "sql server"),
    "spark": ("apache spark",),
    "pyspark": ("spark", "python spark"),
    "big data": ("big data analytics",),
    "data engineering": ("data engineer",),
    "business analytics": ("business analysis", "business intelligence"),
    "databricks engineer": ("databricks",),
    "revenue operations": ("revops", "rev ops", "revenue op"),
}


def _norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def build_skill_matchers(profile):
    """
    Compile a regex per resume skill (with its aliases). Each match must be a
    whole word/phrase (word-boundary), so "SQL" doesn't match "MySQL" unless
    MySQL is an explicit alias, and "Spark" doesn't match "PySpark".
    Returns [(canonical_skill, [compiled_pattern, ...]), ...].
    """
    matchers = []
    for skill in profile.get("skills") or []:
        ns = _norm(skill)
        if not ns:
            continue
        terms = [ns] + list(_SKILL_ALIASES.get(ns, ()))
        pats = []
        for term in terms:
            term = term.strip()
            if not term:
                continue
            pats.append(re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"))
        matchers.append((ns, pats))
    return matchers


# Role phrase aliases: JDs rarely quote the full role title, so also match the
# common shorter forms (BI = Business Intelligence, etc.).
_ROLE_ALIASES = {
    "business intelligence engineer": ("business intelligence", "bi engineer"),
    "senior bi analyst": ("bi analyst", "business intelligence"),
    "analytics manager": ("analytics",),
    "data engineer": ("data engineering",),
}


def role_keywords(profile):
    """
    Phrases that confirm a job is in the user's area: current_role +
    search_roles, plus prefix-stripped versions ("Senior Data Analyst" also
    matches "Data Analyst") and per-role aliases.
    """
    kws = set()
    roles = []
    cr = profile.get("current_role")
    if cr:
        roles.append(cr)
    for r in profile.get("search_roles") or []:
        if r:
            roles.append(r)
    for role in roles:
        nr = _norm(role)
        if not nr:
            continue
        kws.add(nr)
        stripped = re.sub(r"^(senior|lead|sr|jr|junior|principal)\s+", "", nr)
        if stripped != nr and stripped:
            kws.add(stripped)
        for alias in _ROLE_ALIASES.get(nr, ()):
            kws.add(alias)
    return sorted(k for k in kws if k)


def score_text(title, text, matchers, role_kws):
    """
    Score one job's text against the resume.
    Returns (matched_count, matched_skills_list, role_hit).
    """
    if not text:
        return 0, [], False
    t = _norm(text)
    title_low = _norm(title) or ""
    matched = [ns for ns, pats in matchers if any(p.search(t) for p in pats)]
    role_hit = any(kw in t or kw in title_low for kw in role_kws)
    return len(matched), matched, role_hit


def should_keep(score, role_hit, min_skills=None):
    """
    Final keep/drop decision. With no skills configured this would drop
    everything, so it degrades to "keep" (the caller also disables matching).
    """
    if min_skills is None:
        min_skills = get_min_skills()
    if min_skills <= 0:
        return True
    return score >= min_skills or (score >= 1 and role_hit)
