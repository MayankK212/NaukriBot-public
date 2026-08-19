# -*- coding: utf-8 -*-
# ============================================================
# JobBot Web Dashboard - live MongoDB -> browser
# ------------------------------------------------------------
# A self-contained dashboard that queries the same JobPortalBot
# Atlas database the bot writes to. No CSV, no export - every
# page load / refresh hits Mongo live.
#
# RUN:   python dashboard/app.py
# OPEN:  http://127.0.0.1:5000
#
# (Optional custom port:  python dashboard/app.py 8080)
# ============================================================
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_from_directory
from pymongo import MongoClient

from mongo_queries import build_tables

_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

# ---------- timezone ----------
# The bot writes applied_at with its local machine time (India / Asia-Kolkata).
# The dashboard's "today" MUST use that same timezone — otherwise a server in
# another region (e.g. Render Oregon = US-West) would treat a different day as
# "today" and the Today card / from-to filters would disagree with the data.
# Override with the DASHBOARD_TZ env var if the bot ever runs elsewhere.
_DASHBOARD_TZ = os.getenv("DASHBOARD_TZ", "Asia/Kolkata")


def _today_str():
    """YYYY-MM-DD in the dashboard timezone (the bot's data day)."""
    return datetime.now(ZoneInfo(_DASHBOARD_TZ)).strftime("%Y-%m-%d")

# ---------- MongoDB connection (shared with mongo_queries.py) ----------
_client = None
_db = None


def _get_db():
    global _client, _db
    if _db is None:
        from dotenv import load_dotenv
        # Local dev: finds D:\JobBot\.env by walking up from the cwd. On Render
        # there is no .env — MONGO_URI comes straight from the Render secret
        # env var, and load_dotenv() simply finds nothing (returns False).
        load_dotenv()
        uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
        dbname = os.getenv("MONGO_DB_NAME") or "JobPortalBot"
        _client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        _db = _client[dbname]
    return _db


# ---------- helpers ----------
def _status_count(status_rows, name):
    for r in status_rows:
        if r["status"] == name:
            return int(r["count"] or 0)
    return 0


def _series_sum(tbl, col):
    if tbl is None or tbl.empty:
        return 0
    return int(tbl[col].sum())


# ---------- location grouping ----------
# Raw `location` strings are messy ("gurugram, bengaluru", "hybrid - dubai",
# "gurugram(sector 49)"). We group each job into canonical city buckets so the
# filter shows clean options and a job like "gurgaon, kanpur" belongs to BOTH
# the gurgaon and kanpur groups.
_LOC_PREFIXES = ("hybrid - ", "hybrid-", "onsite - ", "remote - ",
                 "work from home - ", "wfh - ", "hybrid", "onsite", "remote")

_LOC_ALIAS = {
    "bangalore": "bangalore", "bengaluru": "bangalore", "blr": "bangalore",
    "bangalore rural": "bangalore", "bengaluru rural": "bangalore",
    "gurugram": "gurgaon", "gurgaon": "gurgaon",
    "delhi": "delhi / ncr", "new delhi": "delhi / ncr", "delhi ncr": "delhi / ncr",
    "ncr": "delhi / ncr",
    "hyderabad": "hyderabad", "hyd": "hyderabad",
    "mumbai": "mumbai", "bombay": "mumbai",
    "dubai": "dubai", "united arab emirates": "dubai", "uae": "dubai",
    "india": "india", "remote": "remote",
}

# regex fragment that matches a raw location string belonging to each group
_LOC_MATCH = {
    "bangalore": "bangalore|bengaluru",
    "gurgaon": "gurugram|gurgaon",
    "delhi / ncr": "delhi|ncr",
    "hyderabad": "hyderabad|hyd",
    "mumbai": "mumbai|bombay",
    "dubai": "dubai|united arab emirates",
    "india": "india",
}


def _loc_groups(value):
    """Canonical city-group names for a raw location string.
    'gurgaon, kanpur' -> {'gurgaon', 'kanpur'}
    'hybrid - bengaluru' -> {'bangalore'}
    'gurugram(sector 19)' -> {'gurgaon'}"""
    groups = set()
    if not value:
        return groups
    for part in value.lower().split(","):
        t = re.sub(r"\(.*?\)", "", part).strip()
        for pre in _LOC_PREFIXES:
            if t.startswith(pre):
                t = t[len(pre):].strip()
                break
        for tok in re.split(r"[/+]", t):
            tok = tok.strip()
            if tok:
                groups.add(_LOC_ALIAS.get(tok, tok))
    return groups


def _loc_regex(group):
    """Regex fragment matching raw location strings in this group."""
    return _LOC_MATCH.get(group, re.escape(group))


def _build_match(args, status=None):
    """Build a MongoDB $match stage from query-string filter params.

    role/company/location are multi-select: repeated query params
    (?role=A&role=B) match ANY of the selected values.
    Locations are matched by city group (see _loc_groups/_loc_regex)."""
    m = {}
    roles = [r.strip() for r in args.getlist("role") if r.strip()]
    companies = [c.strip() for c in args.getlist("company") if c.strip()]
    locations = [l.strip() for l in args.getlist("location") if l.strip()]
    date_from = args.get("from", "").strip()
    date_to = args.get("to", "").strip()

    if roles:
        m["search_role"] = {"$in": roles}
    if companies:
        m["company"] = {"$in": companies}
    if locations:
        pats = [_loc_regex(g) for g in locations]
        m["location"] = {"$in": [
            re.compile(r"\b(?:%s)\b" % p, re.IGNORECASE) for p in pats]}
    if status:
        m["status"] = status

    # Date range: applied_at / flagged_at / ObjectId-based
    if date_from or date_to:
        date_filter = {}
        if date_from:
            date_filter["$gte"] = date_from
        if date_to:
            date_filter["$lte"] = date_to + " 23:59:59"
        # We'll apply to the right field per-collection caller side
        m["_date_filter"] = date_filter  # sentinel — caller pops & applies

    return m


def _apply_date_filter(match, date_field):
    """Pop _date_filter and apply it to the given timestamp field."""
    df = match.pop("_date_filter", None)
    if df:
        match[date_field] = df


def _collection_match(base, date_field):
    """Copy a filter match and apply its _date_filter to date_field.
    Pass date_field=None to drop the date filter (collections with no
    usable timestamp field, e.g. pending_jobs)."""
    m = dict(base)
    df = m.pop("_date_filter", None)
    if df and date_field:
        m[date_field] = df
    return m


def _objectid_range(date_from, date_to):
    """ObjectId _id range covering [date_from, date_to] (dashboard TZ, inclusive).

    pending_jobs stores NO explicit timestamp — its only date signal is the
    ObjectId _id creation time (when the job was scraped). Convert the from/to
    filter into an _id range so pending_jobs-based cards/charts honor the date
    filter exactly like the applied_at / flagged_at collections do."""
    from bson import ObjectId
    try:
        tz = ZoneInfo(_DASHBOARD_TZ)
        oid = {}
        if date_from:
            ts = int(datetime.strptime(date_from, "%Y-%m-%d")
                     .replace(tzinfo=tz).timestamp())
            oid["$gte"] = ObjectId("%08x" % ts + "0000000000000000")
        if date_to:
            # Exclusive upper bound = midnight of the day AFTER `to`.
            ts = int((datetime.strptime(date_to, "%Y-%m-%d")
                      .replace(tzinfo=tz) + timedelta(days=1)).timestamp())
            oid["$lt"] = ObjectId("%08x" % ts + "0000000000000000")
        return oid
    except Exception:
        return {}


def _pending_match(args, status=None):
    """$match for pending_jobs honoring role/company/location AND the from/to
    date range (applied to _id since pending_jobs has no timestamp field).
    status=None matches any status; otherwise it's ANDed with the filters."""
    m = _collection_match(_build_match(args), None)
    oid = _objectid_range(args.get("from", "").strip(),
                          args.get("to", "").strip())
    if oid:
        m["_id"] = oid
    if status:
        m["status"] = status
    return m


def _day_series_filtered(db, collection, date_field, match):
    """{day: count} for a collection, honoring the given $match."""
    pipe = [{"$match": match},
            {"$project": {"day": {"$dateToString": {
                "format": "%Y-%m-%d",
                "date": {"$dateFromString": {"dateString": "$%s" % date_field,
                                             "format": "%Y-%m-%d %H:%M:%S"}}}}}},
            {"$group": {"_id": "$day", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}]
    try:
        return {r["_id"]: r["count"] for r in db[collection].aggregate(pipe)}
    except Exception:
        return {}


def _objectid_day_series_filtered(db, collection, match):
    """{day: count} from the ObjectId creation time, honoring the $match."""
    pipe = [{"$match": match},
            {"$project": {"day": {"$dateToString": {"format": "%Y-%m-%d",
                                                    "date": {"$toDate": "$_id"}}}}},
            {"$group": {"_id": "$day", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}]
    try:
        return {r["_id"]: r["count"] for r in db[collection].aggregate(pipe)}
    except Exception:
        return {}


# ---------- routes ----------
@app.route("/")
def index():
    return send_from_directory(_DIR, "index.html")


@app.route("/api/filters")
def api_filters():
    """Return distinct filter values for dropdowns (grouped locations)."""
    db = _get_db()
    roles, companies, locs = set(), set(), set()
    for coll in ("pending_jobs", "applied_jobs", "apply_manually"):
        roles.update(db[coll].distinct("search_role") or [])
        companies.update(db[coll].distinct("company") or [])
        locs.update(db[coll].distinct("location") or [])
    loc_groups = set()
    for l in locs:
        loc_groups |= _loc_groups(l)
    # Date range from daily_stats
    dates = db["daily_stats"].find({}, {"date": 1, "_id": 0}).sort("date", 1)
    date_list = [d["date"] for d in dates]
    return jsonify({
        "roles": sorted(r for r in roles if r),
        "companies": sorted(c for c in companies if c),
        "locations": sorted(g for g in loc_groups if g),
        "date_range": {
            "min": date_list[0] if date_list else "",
            "max": date_list[-1] if date_list else "",
        },
    })


@app.route("/api/jobs")
def api_jobs():
    """Return paginated job records from a collection, with optional filters."""
    db = _get_db()
    collection = request.args.get("collection", "pending_jobs")
    status = request.args.get("status", "")
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(10, int(request.args.get("per_page", 50))))

    match = _build_match(request.args, status=status if status else None)

    # Apply the date filter to the right field.
    # pending_jobs has no timestamp field -> use the ObjectId _id creation
    # time (= when the job was scraped) instead of a stored applied_at.
    if collection == "pending_jobs":
        match.pop("_date_filter", None)
        oid = _objectid_range(request.args.get("from", "").strip(),
                              request.args.get("to", "").strip())
        if oid:
            match["_id"] = oid
    else:
        date_field_map = {
            "applied_jobs": "applied_at",
            "apply_manually": "flagged_at",
        }
        _apply_date_filter(match, date_field_map.get(collection, "applied_at"))

    # Remove sentinel keys that aren't real MongoDB fields
    match.pop("_date_filter", None)

    col = db[collection]
    total = col.count_documents(match)
    skip = (page - 1) * per_page
    projection = {
        "title": 1, "company": 1, "location": 1,
        "search_role": 1, "link": 1, "applied_at": 1, "flagged_at": 1,
        "salary": 1, "rating": 1, "status": 1, "reason": 1,
        "review_question": 1,
    }
    if collection == "pending_jobs":
        projection["_id"] = 1  # needed to derive the scrape date below
    sort_key = "_id" if collection == "pending_jobs" else "applied_at"
    cursor = col.find(match, projection).sort(sort_key, -1).skip(skip).limit(per_page)

    # Collections that are inherently a single status — when the stored
    # status field is missing/null, label the job by its collection.
    default_status = {
        "applied_jobs": "applied",
        "apply_manually": "apply_manually",
    }.get(collection, status)

    jobs = []
    for j in cursor:
        date = j.get("applied_at") or j.get("flagged_at") or ""
        # pending_jobs store no timestamp — show the scrape date from the
        # ObjectId _id creation time (dashboard TZ, so it matches the filters).
        if not date and collection == "pending_jobs" and j.get("_id") is not None:
            try:
                date = j["_id"].generation_time.astimezone(
                    ZoneInfo(_DASHBOARD_TZ)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date = ""
        jobs.append({
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "location": j.get("location", ""),
            "role": j.get("search_role", ""),
            "link": j.get("link", ""),
            "date": date,
            "salary": j.get("salary", ""),
            "rating": j.get("rating", ""),
            "status": j.get("status") or default_status,
            "reason": j.get("reason", ""),
            "review_question": j.get("review_question", ""),
        })

    return jsonify({
        "jobs": jobs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/summary")
def api_summary():
    """KPI card numbers — all filter-aware. role/company/location/from/to."""
    db = _get_db()
    base = _build_match(request.args)

    m_app = _collection_match(base, "applied_at")
    total_applied = db["applied_jobs"].count_documents(m_app)

    today = _today_str()
    m_app_today = dict(m_app, applied_at={"$regex": "^" + today})
    applied_today = db["applied_jobs"].count_documents(m_app_today)

    m_manual = _collection_match(base, "flagged_at")
    manual = db["apply_manually"].count_documents(m_manual)

    # pending_jobs has no timestamp field — the from/to filter maps to the
    # ObjectId _id creation time (= when the job was scraped), so the Scraped /
    # Pending / Review / Skipped cards honor the date range just like the rest.
    m_pend = _pending_match(request.args)
    total_scraped = db["pending_jobs"].count_documents(m_pend)

    def _pend(status):
        return db["pending_jobs"].count_documents(_pending_match(request.args, status))

    return jsonify({
        "total_applied": total_applied,
        "applied_today": applied_today,
        "total_scraped": total_scraped,
        "pending": _pend("pending"),
        "needs_review": _pend("needs_review"),
        "skipped": _pend("skipped"),
        "manual": manual,
        "today": today,  # server's 'today' so the Today KPI click filters the same day
    })


@app.route("/api/daily")
def api_daily():
    """Merged per-day series: applied / scraped / flagged, filter-aware."""
    db = _get_db()
    base = _build_match(request.args)
    da = _day_series_filtered(db, "applied_jobs", "applied_at",
                              _collection_match(base, "applied_at"))
    ds = _objectid_day_series_filtered(db, "pending_jobs",
                                       _pending_match(request.args))
    df = _day_series_filtered(db, "apply_manually", "flagged_at",
                              _collection_match(base, "flagged_at"))
    days = sorted(set(da) | set(ds) | set(df))
    return jsonify([
        {"date": d, "applied": da.get(d), "scraped": ds.get(d),
         "flagged": df.get(d)}
        for d in days
    ])


@app.route("/api/funnel")
def api_funnel():
    """Today's funnel (seen -> scraped -> dropped -> applied -> errors ...)."""
    t = build_tables()
    ft = t["FunnelToday"]
    if ft is None or ft.empty:
        return jsonify({"labels": [], "values": [], "details": []})
    return jsonify({
        "labels": ft["stage"].tolist(),
        "values": [int(x) for x in ft["value"].tolist()],
        "details": ft["detail"].tolist(),
    })


@app.route("/api/breakdown")
def api_breakdown():
    """Breakdown charts — filter-aware. Locations are grouped into cities."""
    db = _get_db()
    base = _build_match(request.args)
    # pending_jobs honors from/to via ObjectId _id (scrape time).
    m_pend = _pending_match(request.args)
    m_app = _collection_match(base, "applied_at")
    m_manual = _collection_match(base, "flagged_at")

    def _group(field, limit=None):
        pipe = [{"$match": m_pend},
                {"$group": {"_id": "$%s" % field, "n": {"$sum": 1}}},
                {"$sort": {"n": -1}}]
        if limit:
            pipe.append({"$limit": limit})
        out = []
        for r in db["pending_jobs"].aggregate(pipe):
            if r["_id"] not in (None, ""):
                out.append({"label": str(r["_id"]), "value": r["n"]})
        return out

    def _group_locations(limit=15):
        counts = {}
        for r in db["pending_jobs"].find(m_pend, {"location": 1}):
            for g in _loc_groups(r.get("location") or ""):
                counts[g] = counts.get(g, 0) + 1
        rows = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [{"label": k, "value": v} for k, v in rows]

    status = [
        {"label": "Applied", "value": db["applied_jobs"].count_documents(m_app)},
        {"label": "pending", "value": db["pending_jobs"].count_documents(dict(m_pend, status="pending"))},
        {"label": "needs_review", "value": db["pending_jobs"].count_documents(dict(m_pend, status="needs_review"))},
        {"label": "skipped", "value": db["pending_jobs"].count_documents(dict(m_pend, status="skipped"))},
        {"label": "Apply Manually", "value": db["apply_manually"].count_documents(m_manual)},
    ]

    return jsonify({
        "roles": _group("search_role", 15),
        "companies": _group("company", 15),
        "locations": _group_locations(15),
        "status": status,
    })


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"JobBot dashboard -> http://127.0.0.1:{port}   (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False)
