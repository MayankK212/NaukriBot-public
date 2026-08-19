"""
Offline tests for the resume <-> job description relevance matcher.
No network, no browser, no Mongo needed.

Usage:
  python test_relevance.py

Run after editing relevance.py or scraper.py's matching logic.
"""

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from relevance import (  # noqa: E402
    build_skill_matchers,
    get_min_skills,
    matching_enabled,
    role_keywords,
    score_text,
    should_keep,
)

PASS = 0
FAIL = 0

_SENTINEL = object()


def check(name, got, expected=_SENTINEL):
    global PASS, FAIL
    if expected is _SENTINEL:
        name, got, expected = f"eq({name!r})", name, got
    ok = got == expected
    PASS += ok
    FAIL += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={got!r} expected={expected!r}")


def check_true(name, cond):
    check(name, bool(cond), True)


# A stand-in for resume_data.json (skills/roles mirror the real profile).
PROFILE = {
    "current_role": "Senior Data Analyst",
    "search_roles": [
        "Senior Data Analyst",
        "Lead Data Analyst",
        "Analytics Manager",
        "Senior BI Analyst",
        "Business Intelligence Engineer",
        "Data Engineer",
    ],
    "skills": [
        "SQL", "ML", "Python", "PySpark", "Databricks", "Power BI",
        "Snowflake", "Web Scraping", "Data Engineering", "Data Pipeline",
        "Business Analytics", "AI", "ETL Pipeline", "Databricks Engineer",
        "Spark", "Big Data", "Revenue Operations",
    ],
    "experience_years": 6,
}


def test_build_matchers():
    print("\n== build_skill_matchers ==")
    m = build_skill_matchers(PROFILE)
    names = [n for n, _ in m]
    check_true("all 17 skills compiled", len(m) == 17)
    for s in ("sql", "python", "power bi", "etl pipeline", "pyspark"):
        check_true(f"has skill {s!r}", s in names)


def test_score_simple():
    print("\n== score_text: simple overlap ==")
    m = build_skill_matchers(PROFILE)
    rk = role_keywords(PROFILE)

    jd = "We need a Data Analyst with strong SQL and Python and Power BI."
    score, matched, role_hit = score_text("Senior Data Analyst", jd, m, rk)
    check_true("SQL+Python+PowerBI matched", score >= 3)
    check_true("role hit (Data Analyst)", role_hit)

    jd2 = "Data Engineer role: ETL pipelines, Spark and Databricks on AWS."
    score2, matched2, role_hit2 = score_text("Data Engineer", jd2, m, rk)
    check_true("ETL+Spark+Databricks matched", score2 >= 3)
    check_true("role hit (Data Engineer)", role_hit2)

    irrelevant = "Sales Executive required with strong communication skills."
    score3, matched3, role_hit3 = score_text("Sales Executive", irrelevant, m, rk)
    check("irrelevant job -> 0 skills", score3, 0)
    check("irrelevant job -> no role hit", role_hit3, False)


def test_aliases():
    print("\n== score_text: aliases ==")
    m = build_skill_matchers(PROFILE)
    rk = role_keywords(PROFILE)

    # powerbi (no space), ETL alone, ML abbreviation, MySQL for SQL
    jd = "PowerBI dashboards, ETL, machine learning, MySQL database."
    score, matched, _ = score_text("BI Analyst", jd, m, rk)
    for s in ("power bi", "etl pipeline", "ml", "sql"):
        check_true(f"alias match {s!r}", s in matched)

    # Word boundaries: "spark" must NOT match "PySpark", "SQL" must not match "MySQL"
    jd2 = "Python coding and PySpark for data processing."
    score2, matched2, _ = score_text("Data Engineer", jd2, m, rk)
    check_true("PySpark matched", "pyspark" in matched2)
    check("Spark NOT matched by 'pyspark'", "spark" in matched2, False)

    jd3 = "Work with MySQL and Postgres databases."
    score3, matched3, _ = score_text("Backend Developer", jd3, m, rk)
    check_true("SQL matched via MySQL alias", "sql" in matched3)


def test_role_keywords():
    print("\n== role_keywords ==")
    rk = role_keywords(PROFILE)
    check_true("has full current role", "senior data analyst" in rk)
    check_true("has stripped role", "data analyst" in rk)
    check_true("has BI alias", "business intelligence" in rk)
    check_true("has data engineering alias", "data engineering" in rk)

    # A JD that only mentions the role (no skills) still role-hits.
    m = build_skill_matchers(PROFILE)
    score, _, role_hit = score_text("Analytics Manager", "Analytics Manager opening at a bank.", m, rk)
    check_true("title-only role hit", role_hit)
    check("title-only score is 0", score, 0)


def test_keep_decisions():
    print("\n== should_keep (default min_skills=3) ==")
    m = build_skill_matchers(PROFILE)
    rk = role_keywords(PROFILE)

    # 3+ skills, no role keyword -> keep
    jd = "Need SQL, Python, Power BI for reporting."
    s, _, rh = score_text("Reporting Analyst", jd, m, rk)
    check_true("3 skills no role -> keep", should_keep(s, rh))

    # 1 skill + role hit -> keep
    jd2 = "Senior Data Analyst who knows SQL."
    s2, _, rh2 = score_text("Senior Data Analyst", jd2, m, rk)
    check_true("1 skill + role -> keep", should_keep(s2, rh2))

    # 1 skill, no role -> drop
    s3, _, rh3 = score_text("Receptionist", "Familiar with Excel and word processing.", m, rk)
    check_true("1 weak skill no role -> drop", not should_keep(s3, rh3))

    # 0 skills, role hit -> drop (skills are the real signal)
    s4, _, rh4 = score_text("Data Analyst", "Data Analyst wanted, 2 years exp.", m, rk)
    check_true("0 skills + role -> drop", not should_keep(s4, rh4))

    # Tighter threshold -> higher bar (no role boost in play)
    check_true("min_skills=4 rejects 3-match job", not should_keep(3, False, 4))
    check_true("min_skills=4 still keeps role-boosted 3-match job", should_keep(3, True, 4))
    check_true("min_skills=0 keeps everything", should_keep(0, False, 0))


def test_env_config():
    print("\n== env config ==")
    os.environ["JD_MIN_MATCHED_SKILLS"] = "4"
    check("env min_skills=4", get_min_skills(), 4)
    os.environ.pop("JD_MIN_MATCHED_SKILLS")
    check("default min_skills=3", get_min_skills(), 3)
    os.environ["JD_MIN_MATCHED_SKILLS"] = "0"
    check("matching disabled at 0", matching_enabled(), False)
    os.environ.pop("JD_MIN_MATCHED_SKILLS")


if __name__ == "__main__":
    test_build_matchers()
    test_score_simple()
    test_aliases()
    test_role_keywords()
    test_keep_decisions()
    test_env_config()
    print(f"\n{'='*50}\nResult: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
