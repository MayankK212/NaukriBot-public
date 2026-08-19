# -*- coding: utf-8 -*-
# ============================================================
# JobBot -> MongoDB -> Power BI  (direct connection)
# ------------------------------------------------------------
# Runs as Power BI's PYTHON SCRIPT data source. On every refresh
# Power BI executes this script: it queries MongoDB Atlas live
# via pymongo and imports the DataFrames below into the report.
# No CSV, no export, no Data API — same connection the bot uses.
#
# SETUP (one time):
#   1. pip install pandas pymongo            (pymongo probably present)
#   2. Paste your Atlas connection string over MONGO_URI below.
#      -> Copy it from D:\JobBot\.env  (the MONGO_URI=... line),
#         or set MONGO_URI as a Windows environment variable and
#         leave the placeholder — the script checks the env first.
#   3. Power BI Desktop: File -> Options -> Python scripting ->
#      set your Python home. Then Get Data -> Python script ->
#      paste THIS WHOLE FILE -> OK.
#   4. You get 9 tables (DailyApplied, DailyScraped, ...). Follow
#      dashboard/build_guide.md to build the 3 report pages.
#
# Test outside Power BI:  python dashboard/mongo_queries.py
# Prints each table's row count. Expected output ends with
# "OK — 9 tables ready for Power BI."
# ============================================================
import os
from datetime import datetime

import pandas as pd
from pymongo import MongoClient

# ---------- CONFIG ----------
# The script finds MONGO_URI in this order:
#   1. Windows environment variable  MONGO_URI
#   2. D:\JobBot\.env  (auto-read below — same file the bot uses)
#   3. The placeholder below (paste your connection string over it)
MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "PASTE_YOUR_MONGODB_URI_HERE"
DB_NAME = os.getenv("MONGO_DB_NAME") or "JobPortalBot"

if MONGO_URI.startswith("PASTE_YOUR"):
    # No env var set -> read D:\JobBot\.env directly (no dotenv needed,
    # so it also works inside Power BI's own Python install).
    _env_paths = [r"D:\JobBot\.env"]  # hard fallback: Power BI has no __file__
    try:  # standalone runs resolve .env relative to this file
        _base = os.path.dirname(os.path.abspath(__file__))
        _env_paths += [os.path.join(_base, "..", ".env"),
                       os.path.join(_base, ".env")]
    except NameError:
        pass  # pasted into Power BI -> __file__ undefined
    for _p in _env_paths:
        if os.path.exists(_p):
            with open(_p, encoding="utf-8") as _f:
                for _line in _f:
                    if _line.strip().startswith("MONGO_URI="):
                        _v = _line.split("=", 1)[1].strip().strip('"').strip("'")
                        if _v:
                            MONGO_URI = _v
                            break
            if not MONGO_URI.startswith("PASTE_YOUR"):
                break

_EMPTY_FUNNEL_COLS = [
    "date", "seen", "new_raw", "relevance_dropped", "scraped",
    "applied", "apply_errors", "needs_review", "manual",
]


def _connect():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)[DB_NAME]


def _day_series(db, collection, ts_field):
    """count docs per day from a text timestamp field (YYYY-MM-DD HH:MM:SS)."""
    pipe = [
        {"$project": {
            "day": {"$dateToString": {
                "format": "%Y-%m-%d",
                "date": {"$dateFromString": {"dateString": "$%s" % ts_field,
                                             "format": "%Y-%m-%d %H:%M:%S"}}}}}},
        {"$group": {"_id": "$day", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    rows = list(db[collection].aggregate(pipe))
    df = pd.DataFrame(rows, columns=["_id", "count"])
    if df.empty:
        return pd.DataFrame(columns=["day", "count"])
    # NOTE: assign day from _id FIRST, then drop _id - renaming both would
    # leave duplicate "day" columns (breaks pandas column select + Power BI).
    df["day"] = pd.to_datetime(df["_id"])
    df = df.drop(columns=["_id"])
    return df[["day", "count"]]


def _objectid_day_series(db, collection):
    """count docs per day from the ObjectId creation time."""
    pipe = [
        {"$project": {"day": {"$dateToString": {"format": "%Y-%m-%d",
                                                "date": {"$toDate": "$_id"}}}}},
        {"$group": {"_id": "$day", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    rows = list(db[collection].aggregate(pipe))
    df = pd.DataFrame(rows, columns=["_id", "count"])
    if df.empty:
        return pd.DataFrame(columns=["day", "count"])
    df["day"] = pd.to_datetime(df["_id"])
    df = df.drop(columns=["_id"])
    return df[["day", "count"]]


def _group_by(db, collection, field, limit=None):
    pipe = [{"$group": {"_id": "$%s" % field, "jobs": {"$sum": 1}}},
            {"$sort": {"jobs": -1}}]
    if limit:
        pipe.append({"$limit": limit})
    rows = list(db[collection].aggregate(pipe))
    df = pd.DataFrame(rows, columns=["_id", "jobs"])
    return df.rename(columns={"_id": field})


def table_daily_applied(db):
    df = _day_series(db, "applied_jobs", "applied_at")
    return df.rename(columns={"count": "applied"})


def table_daily_scraped(db):
    df = _objectid_day_series(db, "pending_jobs")
    return df.rename(columns={"count": "scraped"})


def table_daily_flagged(db):
    df = _day_series(db, "apply_manually", "flagged_at")
    return df.rename(columns={"count": "flagged"})


def table_daily_funnel(db):
    rows = list(db["daily_stats"].find({}, {"_id": 0}).sort("date", 1))
    if not rows:
        return pd.DataFrame(columns=_EMPTY_FUNNEL_COLS)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    # daily_stats docs can be PARTIAL: the scraper $incs seen/new_raw/... before
    # the apply phase $incs applied/errors/... So a day may exist with only the
    # scraper side filled. Reindex fills any missing column with 0 instead of
    # raising KeyError (which would crash the whole dashboard at import).
    return df.reindex(columns=_EMPTY_FUNNEL_COLS, fill_value=0)


def table_funnel_today(db, daily_funnel):
    if daily_funnel.empty:
        return pd.DataFrame(columns=["stage", "value", "detail"])
    last = daily_funnel.sort_values("date").iloc[-1]
    today = last["date"]
    applied = int(table_daily_applied(db).loc[
        lambda d: d["day"] == today, "applied"].sum())
    return pd.DataFrame([
        ("Seen on Naukri", int(last["seen"]), "Job cards after location filter"),
        ("New scraped", int(last["new_raw"]), "New cards saved to pending_jobs"),
        ("Relevance dropped", int(last["relevance_dropped"]),
         "Removed by resume <-> JD match"),
        ("Applied", applied, "Applications submitted"),
        ("Apply errors", int(last["apply_errors"]), "Naukri apply errors"),
        ("Needs review", int(last["needs_review"]), "Flagged, awaiting human review"),
        ("Apply manually", int(last["manual"]), "Company-site jobs"),
    ], columns=["stage", "value", "detail"])


def table_status_now(db):
    applied = db["applied_jobs"].count_documents({})
    manual = db["apply_manually"].count_documents({})
    pending = list(db["pending_jobs"].aggregate(
        [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]))
    rows = [{"status": "Applied", "count": applied},
            {"status": "Apply Manually", "count": manual}]
    rows += [{"status": r["_id"], "count": r["count"]} for r in pending]
    return pd.DataFrame(rows, columns=["status", "count"])


def table_jobs_by_role(db):
    return _group_by(db, "pending_jobs", "search_role")


def table_top_companies(db):
    return _group_by(db, "pending_jobs", "company", limit=15)


def table_jobs_by_location(db):
    df = _group_by(db, "pending_jobs", "location", limit=15)
    if not df.empty:
        df["location"] = df["location"].astype(str).str.title()
    return df


def build_tables():
    """Returns {table_name: DataFrame} — the 9 Power BI tables."""
    db = _connect()
    tables = {
        "DailyApplied": table_daily_applied(db),
        "DailyScraped": table_daily_scraped(db),
        "DailyFlagged": table_daily_flagged(db),
        "DailyFunnel": table_daily_funnel(db),
        "FunnelToday": None,          # depends on DailyFunnel + DailyApplied
        "StatusNow": table_status_now(db),
        "JobsByRole": table_jobs_by_role(db),
        "TopCompanies": table_top_companies(db),
        "JobsByLocation": table_jobs_by_location(db),
    }
    tables["FunnelToday"] = table_funnel_today(db, tables["DailyFunnel"])
    return tables


# ---- Power BI / standalone execution ----
# Power BI's Python connector executes THIS FILE directly (so __name__ ==
# "__main__" there too) and then imports every DataFrame from the global
# namespace. The query loop MUST stay inside the __main__ guard: the Flask
# dashboard does `from mongo_queries import build_tables` at boot, and running
# 9 live Mongo queries at import time would hang/crash gunicorn before it can
# serve a single request.
if __name__ == "__main__":
    for _name, _df in build_tables().items():
        globals()[_name] = _df
    for _n in ("DailyApplied", "DailyScraped", "DailyFlagged", "DailyFunnel",
               "FunnelToday", "StatusNow", "JobsByRole", "TopCompanies",
               "JobsByLocation"):
        print("%-16s %s rows" % (_n, len(globals()[_n])))
    print("OK - 9 tables ready for Power BI. "
          "(drop the FunnelToday line if today's funnel shows 0 before "
          "the bot's next run; daily_stats fills from then on.)")
