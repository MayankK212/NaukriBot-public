# JobBot → Power BI Dashboard (direct MongoDB connection)

A resume-worthy Power BI dashboard that shows the JobBot's live pipeline:
jobs seen on Naukri → scraped → applied → errors → needs-review → manual.

**No CSV/Excel export, and no Atlas Data API needed.** Power BI's built-in
**Python script** connector runs `mongo_queries.py` on every refresh — the
script queries your MongoDB Atlas cluster **directly with pymongo** (the same
connection the bot uses) and hands the results to Power BI as tables. One
source of truth: the `JobPortalBot` database.

## What's here
| File | Purpose |
|---|---|
| `mongo_queries.py` | The Python script Power BI runs — queries Mongo, builds 9 tables |
| `build_guide.md` | Step-by-step: 3 report pages, DAX measures, formatting |
| `verify_data_api.py` | *(removed — the Data API isn't available on the free M0 tier)* |

## Why not the Atlas Data API?
The Data API lives under **Atlas App Services**, which isn't offered on the
free M0 tier — that's why you can't see it in the Atlas console. The Python
connector below needs **zero Atlas setup**: same credentials, same queries,
works on M0 forever.

## Quick start (≈15 min)

### 1. Install the Python packages (one time)
```bash
pip install pandas pymongo
```
(pymongo is almost certainly already installed — the bot uses it.)

### 2. Point the script at your database
Open `mongo_queries.py` → check the `MONGO_URI` line. The script already
auto-reads `D:\JobBot\.env` (the same file the bot uses), so **you usually
don't have to change anything.** If `.env` is missing the key, paste your
Atlas connection string over the placeholder.

### 3. Verify it works (30 seconds)
```bash
python dashboard/mongo_queries.py
```
Expected output: 9 lines, one per table, ending with
`OK - 9 tables ready for Power BI.` If you get a connection error, check the
connection string.

### 4. Point Power BI at the script
1. Power BI Desktop → **File → Options and settings → Options → Python
   scripting** → set **Python home directory** to the Python where you
   installed pandas (e.g. `C:\Users\<you>\AppData\Local\Programs\Python\Python312`).
2. **Get Data → Python script** → paste the **whole contents of
   `mongo_queries.py`** → **OK**.
3. Power BI runs it and shows a preview: 9 tables (`DailyApplied`,
   `DailyScraped`, `DailyFlagged`, `DailyFunnel`, `FunnelToday`, `StatusNow`,
   `JobsByRole`, `TopCompanies`, `JobsByLocation`). Check them all → **Load**.

### 5. Build the report
Follow [`build_guide.md`](build_guide.md) — 3 pages (Executive Summary,
Daily Trends, Pipeline Breakdown) with KPI cards, a funnel, trend lines, and
breakdown charts.

## Data source → table map
| Power BI table | Where the data lives | Meaning |
|---|---|---|
| `DailyApplied` | `applied_jobs.applied_at` | Applications per day (real history, ~50/day) |
| `DailyScraped` | `pending_jobs` ObjectId time | Jobs scraped per day |
| `DailyFlagged` | `apply_manually.flagged_at` | Manual-apply jobs per day |
| `DailyFunnel` | `daily_stats` | Seen → new → dropped → applied (fills from the **next** daily run) |
| `FunnelToday` | `daily_stats` + `DailyApplied` | Today's funnel for the funnel visual |
| `StatusNow` | all collections | Current pipeline: Applied / Pending / Needs Review / Apply Manually |
| `JobsByRole` / `TopCompanies` / `JobsByLocation` | `pending_jobs` | Breakdowns |

> ⚠️ The `seen` / `relevance-dropped` funnel numbers were not tracked before
> 2026-08-02, so `DailyFunnel` is empty until the bot's next run. The applied /
> scraped / flagged trends are **real history** already.

## Refresh
- **Manual:** In Power BI Desktop, **Refresh** re-runs the Python script and
  pulls live numbers.
- **Automatic (optional):** publish to a Power BI workspace and set a
  scheduled refresh — the script runs on the Power BI service machine, which
  needs Python + pandas there. For a personal resume dashboard, refreshing in
  Desktop is usually enough.
- To keep the funnel fresh, the bot logs `daily_stats` on every run.

## Security notes
- The connection string is inside `mongo_queries.py` / the `.pbix` — keep the
  file private. It's the same string already in `.env`.
- Use a **read-only** Atlas user for the dashboard if you want extra safety
  (the bot itself uses a full-access user).

## Alternative (only if you're on a paid Atlas tier, M10+)
Enable **Atlas SQL** (BI Connector) and use Power BI's native **MongoDB**
connector — same data, fewer moving parts. The Python route above works on the
free M0 tier, so it's the default.
