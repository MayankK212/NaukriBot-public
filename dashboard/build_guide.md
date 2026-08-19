# JobBot Dashboard — Power BI Build Guide

Build a 3-page resume dashboard from the 9 live tables loaded from
`mongo_queries.py` (Power BI's Python script connector — direct MongoDB, no
Data API/CSV). Assumes you finished the README quick start (all 9 tables are
loaded). ~40 minutes.

---

## Step 0 — Data prep (do this once, 5 min)

1. **Check the table names** (Model view, or right-click in Fields). The script
   already names them cleanly — you shouldn't need to rename anything:
   - `DailyApplied`, `DailyScraped`, `DailyFlagged`, `DailyFunnel`,
     `FunnelToday`, `StatusNow`, `JobsByRole`, `TopCompanies`, `JobsByLocation`
2. **Create a Calendar table** (Model view → **New table** → paste):
   ```dax
   Calendar = CALENDAR(MIN(DailyApplied[day]), TODAY())
   ```
   This spans your data to today, so trend charts always show a continuous axis.

3. **Create relationships** (Model view → **Manage relationships** → New):
   | From | To | Cardinality |
   |---|---|---|
   | `Calendar[Date]` | `DailyApplied[day]` | 1 : many |
   | `Calendar[Date]` | `DailyScraped[day]` | 1 : many |
   | `Calendar[Date]` | `DailyFlagged[day]` | 1 : many |
   | `Calendar[Date]` | `DailyFunnel[date]` | 1 : many |

4. **Create measures** (Model view → **New measure**):
   ```dax
   Total Applied      = CALCULATE(SUM(StatusNow[count]), StatusNow[status] = "Applied")
   Pending            = CALCULATE(SUM(StatusNow[count]), StatusNow[status] = "pending")
   Needs Review       = CALCULATE(SUM(StatusNow[count]), StatusNow[status] = "needs_review")
   Apply Manually     = CALCULATE(SUM(StatusNow[count]), StatusNow[status] = "Apply Manually")
   Applied Today      = CALCULATE(SUM(DailyApplied[applied]), Calendar[Date] = TODAY())
   Applied Per Day    = SUM(DailyApplied[applied])
   Scraped Per Day    = SUM(DailyScraped[scraped])
   Flagged Per Day    = SUM(DailyFlagged[flagged])
   ```
   Set each measure's **Format** to `Number`, 0 decimals.

---

## Page 1 — Executive Summary

Goal: 30-second read. KPIs on top, funnel below.

- **Page name:** "Executive Summary"
- **KPI cards** (New visual → *Card (new)*) — one per row, 5 across:
  - **Total Applied** (all-time, from `StatusNow`)
  - **Applied Today** (`Applied Today`)
  - **Pending** — still queued to apply
  - **Needs Review** — flagged for your eyes
  - **Apply Manually** — company-site jobs
- **Funnel** (New visual → *Funnel*): Field **stage**, Values **value**
  (`FunnelToday`). This is the story: *Seen → Scraped → Relevance dropped →
  Applied → Errors → Needs review → Manual*.
- **Slicer** (optional): a date slicer on `Calendar[Date]` so you can slide the
  KPIs/funnel to any day.
- **Title:** "JobBot — Automated Naukri Application Pipeline"
- **Subtitle/note:** "Direct MongoDB connection • daily 08:25 IST run"

> Tip: set each KPI card's **Category label** to the metric name (so the card
> shows "405 / Applied" instead of just a number).

---

## Page 2 — Daily Trends

Goal: volume and consistency over time.

- **Page name:** "Daily Trends"
- **Line chart 1** — *Applied Per Day* (legend none, axis `Calendar[Date]`,
  values `Applied Per Day`). Shows the real daily volume (~50/day cap visible).
- **Line chart 2** — *Scraped Per Day* (`Scraped Per Day`) on the same axis.
- **Line chart 3** — *Flagged Per Day* (`Flagged Per Day`).
- **Combined line chart** (show them together): one line chart, axis
  `Calendar[Date]`, values `Applied Per Day` + `Scraped Per Day` + `Flagged Per
  Day`. Color them distinctly (e.g. green / blue / amber).
- **Table** (bottom): `DailyFunnel` — columns `date, seen, new_raw,
  relevance_dropped, scraped, applied, apply_errors, needs_review, manual`.
  This is your daily operations log at a glance.

---

## Page 3 — Pipeline Breakdown

Goal: *where* the jobs come from — roles, companies, locations, status.

- **Page name:** "Pipeline Breakdown"
- **Donut** — *StatusNow*: Legend **status**, Values **count**. Colors:
  Applied=green, Pending=blue, Needs Review=amber, Apply Manually=grey,
  Skipped=light grey.
- **Bar chart (horizontal)** — *JobsByRole*: Axis **role**, Values **jobs**
  (sorted desc). Shows which search roles dominate the pipeline.
- **Bar chart (horizontal)** — *TopCompanies*: Axis **company**, Values **jobs**.
- **Bar chart** — *JobsByLocation*: Axis **location** (Text.Proper already
  applied), Values **jobs**.
- **Header KPI strip**: Total Applied / Pending / Needs Review (reuse measures).

---

## Step 4 — Polish (10 min, makes it resume-ready)

- **Theme:** View → Themes → pick a clean corporate theme; set your **brand
  color** for all KPI cards (Format → General → Color). Match title fonts.
- **Consistent axis:** ensure all trend charts share the same date range via
  `Calendar[Date]` (they already do through the relationship).
- **Data labels:** on KPI cards enable **Value** → **Display units** (e.g.
  *Thousands* if numbers get big) — small numbers read better as integers.
- **Tooltips (pro):** add a page tooltip on the trend lines showing that day's
  funnel (create a 4th tiny page, format as a tooltip, set as tooltip on the
  line charts).
- **Remove clutter:** delete the auto-generated "Page 1" grids; hide any helper
  tables (disable **Enable load** on `FunnelToday` if you only use it in the
  funnel, or keep it — it's tiny).
- **Save as** `JobBot_Dashboard.pbix` in the `dashboard/` folder.

---

## Refresh & share

- **Refresh now:** Home → **Refresh** (or Ctrl+R). Power BI re-runs the Python
  script and pulls fresh numbers from Atlas.
- **Daily automation (optional):** Publish to a Power BI workspace → Settings →
  Scheduled refresh. Note: on the service, the script runs where Power BI runs
  it — the service needs Python + pandas configured. For a personal resume
  dashboard, refreshing in Desktop is usually enough. Set it to 09:00 IST
  (after the 08:25 bot run) if you do.
- **Share for a resume:** export PDF/PNG per page, or share the workspace link.
  If you share the `.pbix`, remove/replace the connection string in
  `mongo_queries.py` first and note that in the README's security section.

## Troubleshooting
- **Power BI says "Python was not specified"** — set the Python home under
  File → Options → Python scripting (the install where you ran
  `pip install pandas`).
- **"No module named pandas/pymongo"** — that Python lacks the packages. Run
  `pip install pandas pymongo` against the same Python Power BI is using.
- **Connection error** — the `MONGO_URI` isn't resolving. Run
  `python dashboard/mongo_queries.py`; if that fails, paste the connection
  string from `.env` directly into the placeholder in the script.
- **Empty `DailyFunnel`** — expected until the bot's next run (logging added
  2026-08-02). Applied/scraped/flagged trends are real immediately.
- **Dates show as numbers** — the `day`/`date` columns are already typed as Date
  in the script; if they aren't, format the column as Date (Model view).
- **Privacy warning** — set the data source to **Public** and refresh.
