# 🤖 JobBot — Auto-apply to Naukri jobs, every day, for free

JobBot finds fresh jobs on **Naukri.com**, throws away the ones that don't match your
resume, answers the screening questions with **AI**, applies to them, and **emails you
a report** — automatically, every morning, running on **GitHub's free servers**.
Your computer can stay **off**.

> **In plain words:** you set it up once (about 45–60 min). After that, every morning
> you get an email listing the jobs it applied to for you — and the reason it skipped
> the rest.

There's also an optional **live web dashboard** (free) that charts everything the bot
has done — nice to link on your LinkedIn. See [section 6](#6-bonus-live-dashboard).

---

## 📖 Table of contents
1. [What you'll need](#1-what-youll-need)
2. [How it works](#2-how-it-works)
3. [Setup — do this once](#3-setup--do-this-once)
   - [Step 1: Get the code on your computer](#step-1-get-the-code-on-your-computer)
   - [Step 2: Install Python](#step-2-install-python)
   - [Step 3: Install JobBot's requirements](#step-3-install-jobbots-requirements)
   - [Step 4: Free database (MongoDB Atlas)](#step-4-free-database-mongodb-atlas)
   - [Step 5: Gmail App Password](#step-5-gmail-app-password)
   - [Step 6: Free Gemini API key (the AI that answers questions)](#step-6-free-gemini-api-key)
   - [Step 7: Your details file (resume_data.json)](#step-7-your-details-file)
   - [Step 8: Save your Naukri login (cookies)](#step-8-save-your-naukri-login)
   - [Step 9: Test it on your computer](#step-9-test-it-on-your-computer)
   - [Step 10: Put the code on GitHub (private)](#step-10-put-the-code-on-github-private)
   - [Step 11: Add your secrets to GitHub](#step-11-add-your-secrets-to-github)
   - [Step 12: Turn on the daily run](#step-12-turn-on-the-daily-run)
4. [Everyday use & maintenance](#4-everyday-use--maintenance)
5. [Make it yours (customise)](#5-make-it-yours-customise)
6. [Bonus: live dashboard](#6-bonus-live-dashboard)
7. [Limits you should know](#7-limits-you-should-know)
8. [Troubleshooting](#8-troubleshooting)
9. [FAQ](#9-faq)

---

## 1. What you'll need

All **free**. Create these accounts if you don't have them:

| Thing | Why | Link |
|------|-----|------|
| A **Naukri.com** account | So the bot can apply as you | https://www.naukri.com |
| A **Gmail** account | To send you the daily report | https://gmail.com |
| A **GitHub** account | Runs the bot daily for free | https://github.com |
| A **MongoDB Atlas** account | Free cloud database for the jobs | https://www.mongodb.com/atlas |
| A **Google AI Studio** key | Free AI that answers screening questions | https://aistudio.google.com/apikey |
| A **cron-job.org** account | Fires the bot on time, every day | https://cron-job.org |

You do **not** need to keep your PC on. You do **not** need to pay anything.

---

## 2. How it works

```
Every morning  →  a pinger wakes GitHub  →  the bot runs:

  scrape Naukri          find fresh jobs for your search_roles + locations
        ↓
  match your resume      score the job description against your skills;
                         drop the ones that don't match  (no AI used — free)
        ↓
  answer questions       AI (Gemini Flash) reads each screening question and
                         answers it from your profile
        ↓
  apply                  submit only if EVERY question was answered confidently
        ↓
  email you              2 emails: what it applied to (+ why it skipped the rest),
                         and what it scraped (+ why each job was kept or rejected)
```

Two rules the bot never breaks:

- **It never guesses.** If the AI isn't confident, or its answer isn't one of the
  options Naukri offered, the job is flagged **“needs review”** instead of being
  submitted. You finish those by hand.
- **It never applies to jobs that don't match your resume.** A job is only saved if
  at least **3 of your skills** appear in the description, **or** at least 1 skill
  appears *and* the job title matches one of your roles. (Both numbers are
  adjustable — see [section 5](#5-make-it-yours-customise).)

---

## 3. Setup — do this once

> 💡 Tip: do the steps in order. Copy-paste the commands exactly. On Windows, open
> **PowerShell** (search "PowerShell" in the Start menu).

### Step 1: Get the code on your computer
Easiest: click the green **Code** button on the GitHub repo → **Download ZIP** →
unzip it to a simple folder like `C:\JobBot`.

(Or, if you know git: `git clone <repo-url>`.)

### Step 2: Install Python
1. Download Python (3.12+) from https://www.python.org/downloads/
2. Run the installer. **⚠️ IMPORTANT: tick “Add Python to PATH”** on the first screen, then install.
3. Verify — open PowerShell and run:
   ```powershell
   python --version
   ```
   You should see `Python 3.12.x`.

### Step 3: Install JobBot's requirements
In PowerShell, go into the folder and install everything:
```powershell
cd C:\JobBot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chrome
```
This creates a private workspace (`.venv`) and downloads the browser the bot uses.

### Step 4: Free database (MongoDB Atlas)
This is where the bot stores the jobs it finds.
1. Sign up: https://www.mongodb.com/atlas → create a **free (M0)** cluster.
2. **Database Access** → *Add New Database User* → set a **username + password**
   (write them down — no special characters is easiest).
3. **Network Access** → *Add IP Address* → **Allow Access from Anywhere**
   (`0.0.0.0/0`) → Confirm. *(Needed because GitHub's servers change IPs. Your DB is
   still protected by the username/password.)*
4. **Database → Connect → Drivers** → copy the connection string. It looks like:
   ```
   mongodb+srv://USERNAME:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   Replace `USERNAME`/`PASSWORD` with the ones you made. **Keep this string safe** —
   you'll use it as `MONGO_URI`.

### Step 5: Gmail App Password
A normal Gmail password won't work for sending mail from a script. You need an "App Password":
1. Turn on **2-Step Verification**: https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords → type a name like `JobBot` → **Create**.
3. Copy the **16-character code** (e.g. `abcd efgh ijkl mnop`). This is your `EMAIL_PASS`.

### Step 6: Free Gemini API key
This is the AI that reads each screening question and answers it from your profile.

1. Go to https://aistudio.google.com/apikey → sign in with Google → **Create API key**.
2. Copy it. This is your `GEMINI_API_KEY`.

> ⚠️ **Without this key the bot still runs, but it applies to nothing** — every job
> gets flagged “needs review” (it refuses to guess). The startup log prints a warning
> so you can't miss it.

> 📉 **The free tier is small.** Expect roughly **20 AI requests per day** on a new
> free key, resetting at midnight US-Pacific. The bot caps itself at **18 per run**
> to stay inside that budget; jobs past the cap are flagged “needs review” instead of
> guessed. That's usually enough for the questions on one day's jobs. Want more?
> Request a higher limit at https://ai.dev/rate-limit.

### Step 7: Your details file
Make your own profile from the template — copy `resume_data.example.json` to a new
file named **`resume_data.json`** and fill in your details. (Your real
`resume_data.json` is git-ignored, so it never gets uploaded.)
Example:
```json
{
  "full_name": "Your Name",
  "email": "your.email@example.com",
  "current_role": "Data Analyst",
  "search_roles": ["Data Analyst", "Business Analyst"],
  "experience_years": 3,
  "current_ctc": "10 LPA",
  "expected_ctc": "15 LPA",
  "notice_period": "30 days",
  "current_location": "Bengaluru",
  "preferred_locations": ["India", "Remote"],
  "relocation_preference": "Yes",
  "skills": ["SQL", "Python", "Excel", "Power BI"],
  "graduation_year": 2021,
  "highest_education": "B.Tech",
  "ug_degree": "B.Tech",
  "date_of_birth": "DD/MM/YYYY",
  "languages": ["English", "Hindi"],
  "passport": "Yes",
  "communication_skills_scale_of_10": 8
}
```
- `search_roles` = the job titles to search on Naukri.
- `preferred_locations` = where you'll work. Put **`"India"`** in the list to accept
  jobs anywhere in the country; otherwise list cities (`"Bengaluru"`, `"Remote"`, …).
- **`skills` is the most important field.** It's used twice: to decide whether a job
  matches you at all, and to answer "do you know X?" questions. List everything you
  actually know.
- The AI answers from these fields, so the more you fill in, the more it can submit
  without flagging.

> ⚠️ Edit this file **locally**, not on the GitHub website — it's easy to break the
> JSON there (a missing comma) and the bot won't start. After editing, run
> `sync_resume.py` (Step 9) which will fail loudly if the JSON is invalid.

### Step 8: Save your Naukri login
The bot needs to be logged in as you. Run this once — a browser opens, **log in to
Naukri manually**, and it saves your session to `cookies.json`:
```powershell
.\.venv\Scripts\python.exe login_setup.py
```

### Step 9: Test it on your computer
Before going to the cloud, make sure it works locally. Create a file named **`.env`**
in the folder (Notepad) with:
```
MONGO_URI="mongodb+srv://USERNAME:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
EMAIL_USER="you@gmail.com"
EMAIL_PASS="your 16-char app password"
EMAIL_TO="you@gmail.com"
GEMINI_API_KEY="your gemini key"
```
Copy your profile into the database, then run the whole pipeline once:
```powershell
.\.venv\Scripts\python.exe sync_resume.py
.\.venv\Scripts\python.exe run_daily.py
```
If jobs get scraped and you receive the emails — 🎉 it works. Now let's make it run
daily in the cloud (so your PC can stay off).

You can also check the two matching/answering brains on their own — these need no
internet, no key, and take a second:
```powershell
.\.venv\Scripts\python.exe test_relevance.py
.\.venv\Scripts\python.exe test_llm_answers.py
```
Both should print `35 passed, 0 failed`.

> 🔒 `.env` and `cookies.json` are **never** uploaded to GitHub (they're in
> `.gitignore`). They hold your secrets and stay only on your computer.

### Step 10: Put the code on GitHub (private)
**Easiest (no commands): GitHub Desktop**
1. Install https://desktop.github.com and sign in.
2. **File → Add local repository →** choose your `C:\JobBot` folder → Add.
3. Write a short message → **Commit to main**.
4. Click **Publish repository** → **keep “Keep this code private” ticked** → Publish.

### Step 11: Add your secrets to GitHub
On GitHub, open your repo → **Settings → Secrets and variables → Actions →
New repository secret**. Add these **7** (name on left, your value on right):

| Secret name | What to paste |
|-------------|---------------|
| `MONGO_URI` | your MongoDB connection string from Step 4 |
| `EMAIL_USER` | your Gmail address |
| `EMAIL_PASS` | the 16-char Gmail App Password from Step 5 |
| `EMAIL_TO` | where to receive the report (your email) |
| `GEMINI_API_KEY` | your Gemini key from Step 6 |
| `NAUKRI_COOKIES` | the **entire contents** of your `cookies.json` file (open it, copy all, paste) |
| `RESUME_JSON` | the **entire contents** of your `resume_data.json` (so your profile stays out of the code) |

> To copy `cookies.json` contents on Windows PowerShell:
> ```powershell
> Get-Content cookies.json -Raw | Set-Clipboard
> ```
> Then just paste (Ctrl+V) into the secret box.

> ⚠️ If you ever change your Gemini key, update it in **both** places — your local
> `.env` **and** this GitHub secret. A blank secret means every job gets flagged.

### Step 12: Turn on the daily run

**First, run it once by hand** to prove the cloud setup works:
repo → **Actions** tab → **JobBot Daily** (left side) → **Run workflow** →
green **Run workflow** button. Watch it run; in a few minutes you'll get the emails.

**Now make it daily.** This workflow has **no built-in schedule**, on purpose:
GitHub's own `cron` is best-effort and was firing *hours* late — by which point
Naukri rejected every application. So an outside service pokes GitHub instead, and
it's punctual.

1. Make a token GitHub will accept:
   GitHub → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
   - **Repository access:** only your JobBot repo.
   - **Permissions:** `Actions` → **Read and write**, `Contents` → **Read-only**.
   - Copy the token (you only see it once). Note its **expiry date** — you'll need
     to renew it.
2. Sign up at https://cron-job.org → **Create cronjob**:
   - **URL:**
     `https://api.github.com/repos/<your-username>/<your-repo>/actions/workflows/daily-jobbot.yml/dispatches`
   - **Method:** `POST`
   - **Headers:**
     ```
     Accept: application/vnd.github+json
     Authorization: Bearer <your token>
     X-GitHub-Api-Version: 2022-11-28
     ```
   - **Body:** `{"ref":"main"}`  ← use `"master"` if that's your default branch
   - **Schedule:** every day at **08:25**, timezone **Asia/Kolkata**
     *(pick an early-morning time — applications sent early in the day succeed far
     more often.)*
3. Hit **Test run** in cron-job.org. It should return **204** and you should see a
   new run appear in your repo's Actions tab.

**You're done!** 🎉

> ⚠️ **The pinger is now the only thing that starts the bot.** If it stops (expired
> token, deleted job, cron-job.org account issue), the bot goes quiet and you just
> stop getting emails. If a morning passes with no email, check cron-job.org first.

---

## 4. Everyday use & maintenance

- **Nothing to do daily** — just read the two emails each morning.
- **Jobs marked “needs review”** had a question the bot wouldn't answer without
  guessing (or the AI budget ran out). The email shows you the exact question. Open
  those on Naukri and finish them yourself.
- **Refresh your login every few weeks.** Naukri logs sessions out over time. When
  the email shows 0 jobs / apply failures, refresh the cookies:
  ```powershell
  .\.venv\Scripts\python.exe login_setup.py
  ```
  Then copy the new `cookies.json` contents into the `NAUKRI_COOKIES` secret again
  (Step 11). *(This is the main recurring chore.)*
- **Renew the pinger token before it expires** (Step 12). An expired token = a silent
  bot.
- **After editing your details,** push them to the database and update the secret:
  ```powershell
  .\.venv\Scripts\python.exe sync_resume.py
  ```

---

## 5. Make it yours (customise)

**Which jobs it looks for** — edit `resume_data.json`: `search_roles` (job titles)
and `preferred_locations` (cities, or `"India"` for anywhere).

**How strict the resume matching is** — set these as env vars in
`.github/workflows/daily-jobbot.yml`:

| Setting | Default | What it does |
|---------|---------|--------------|
| `JD_MIN_MATCHED_SKILLS` | `3` | Skills that must appear in the job description to keep it. Lower = more jobs, less relevant. **`0` turns matching off entirely.** |
| `JD_FETCH_DETAIL` | `true` | Open each job page to read the full description. `false` = judge from the search-result snippet only (faster, less accurate). |
| `JD_MAX_FETCHES` | `60` | Cap on job pages opened per run, so the scrape stays quick. |

**How much it applies per run:**

| Setting | Default | What it does |
|---------|---------|--------------|
| `MAX_JOBS_PER_RUN` | `200` | Stop applying after this many jobs. Leftovers stay in the queue for tomorrow. |
| `APPLY_TIME_BUDGET` | `2400` | Seconds to spend applying, then stop cleanly so the email always sends. |
| `APPLY_STOP_ERRORS` | `15` | Consecutive Apply failures before giving up for the day (this is how it detects Naukri's daily cap — see [section 7](#7-limits-you-should-know)). |

**The AI:**

| Setting | Default | What it does |
|---------|---------|--------------|
| `GEMINI_MODEL` | `gemini-flash-latest` | Which model to use. Keep this alias — specific `2.x` model names return 404 for new free keys. |
| `GEMINI_MAX_CALLS_PER_RUN` | `18` | Total AI questions per run. Sized for the ~20/day free tier. |
| `GEMINI_MAX_CALLS_PER_JOB` | `15` | Cap for one job, so a single form can't eat the whole budget. |
| `GEMINI_CONFIDENT_LEVELS` | `high,medium` | Which confidence levels are allowed to auto-submit. Set to `high` to be stricter. |
| `GEMINI_MIN_INTERVAL` | `4.0` | Seconds between AI calls (keeps you under the requests-per-minute limit). |
| `GEMINI_TIMEOUT` | `30` | Seconds to wait for an answer. |
| `GEMINI_STRIP_PII` | off | Set to `true` to keep your name/email/DOB out of the text sent to the AI. |

**New kinds of screening questions need no code.** The AI reads the question and your
profile and works it out. If a question keeps getting flagged, it's almost always
because the answer isn't in `resume_data.json` — add the field and it'll start
answering. (Older versions of this bot used hand-written if-then rules for each
question type; those are gone.)

**Change the run time** — change the schedule in **cron-job.org**, not in the
workflow file (the workflow has no cron of its own; see Step 12).

---

## 6. Bonus: live dashboard

`dashboard/` holds a small web app that charts everything the bot has done —
applications over time, the daily funnel, top companies, top locations, and the
current pipeline. It reads the same MongoDB, so it's always live.

**Run it locally:**
```powershell
.\.venv\Scripts\python.exe dashboard\app.py
```
Then open http://127.0.0.1:5000

**Put it online for free** (nice to link on LinkedIn): follow
[`dashboard/DEPLOY.md`](dashboard/DEPLOY.md) — it's a one-click Render.com Blueprint
deploy using the `render.yaml` at the repo root. You paste your `MONGO_URI` as a
Render secret; nothing sensitive goes in the code.

> Render's free plan sleeps a service after ~15 minutes idle, so the first visit can
> take 30–60s to wake up. `dashboard/DEPLOY.md` shows a tiny keep-alive workflow that
> pings it every 10 minutes if you'd rather it stayed warm.

Prefer Power BI? `dashboard/mongo_queries.py` + `dashboard/build_guide.md` build the
same thing as a `.pbix` report, connecting straight to MongoDB.

---

## 7. Limits you should know

These aren't bugs — they're ceilings set by other people's services.

- **Naukri: about 50 applications per day.** Free Naukri accounts stop accepting
  submissions after roughly 50 in a day; every further Apply returns *"There was an
  error while processing your request."* It's per-account (changing IP doesn't help)
  and resets daily. The bot notices the wall and stops early instead of hammering it;
  the rest stay queued for tomorrow. Only Naukri Premium raises this — no code can
  get around it.
- **Gemini free tier: about 20 AI requests per day.** See Step 6. Jobs past the
  budget are flagged, never guessed.
- **Jobs that redirect to a company's own careers site** can't be auto-applied. They
  go to an `apply_manually` list for you.
- **Date-picker date-of-birth widgets** are sometimes still flagged for manual
  review.

---

## 8. Troubleshooting

| Problem | Fix |
|--------|-----|
| `python` not recognised | Reinstall Python and tick **“Add Python to PATH”** (Step 2). |
| **Every** job says “needs review” | `GEMINI_API_KEY` is missing/blank, or the daily AI quota is used up. Check the run log for the startup warning (Step 6). |
| No email at all in the morning | The pinger didn't fire. Check cron-job.org → your job → last execution. Usually an expired token (Step 12). |
| Email arrives but 0 applied, lots of "apply error" | Either your Naukri cookies expired (refresh them, section 4) or you hit Naukri's ~50/day cap (section 7). |
| Email not received | Check `EMAIL_PASS` is the **App Password** (not your Gmail login), and check Spam. |
| Workflow can't connect to DB | In Atlas → Network Access, make sure `0.0.0.0/0` is **Active** (Step 4). |
| “JobBot Daily” missing in Actions | Make sure `.github/workflows/daily-jobbot.yml` was uploaded, and Settings → Actions → General → **Allow all actions**. |
| Too few jobs scraped | Lower `JD_MIN_MATCHED_SKILLS`, add skills to `resume_data.json`, or widen `search_roles` / `preferred_locations` (section 5). |
| Jobs scraped that don't suit you | Raise `JD_MIN_MATCHED_SKILLS`, or trim `skills` down to what you'd actually accept work in. |
| A question got a wrong answer | Fix the value in `resume_data.json`, run `sync_resume.py`, and update the `RESUME_JSON` secret. |
| Bot won't start after editing your profile | Broken JSON in `resume_data.json` — run `sync_resume.py` locally to see the error (Step 7). |

The second email ("Scrape Selection Report") tells you exactly why each job was kept
or rejected — start there when the matching feels wrong.

Every run also saves debug files. On a failed/empty run: repo → that run → **Artifacts
→ jobbot-debug** to download what Naukri actually showed.

---

## 9. FAQ

**Do I need to keep my PC on?**
No. GitHub's servers run it. Your PC is only needed for the one-time setup and to
refresh cookies occasionally.

**Is it really free?**
Yes — GitHub Actions, MongoDB Atlas free tier, Gemini's free tier, cron-job.org, and
Gmail are all free at this usage. Render's free plan covers the optional dashboard.

**Is my data safe?**
Your secrets (DB, email, cookies, AI key) live in GitHub **Secrets** and your local
`.env` — never in the code. Your profile is uploaded as the `RESUME_JSON` secret
rather than committed. **Keep your GitHub repo PRIVATE.**

**Does my resume get sent to Google's AI?**
The relevant profile fields are, as context for answering each question. Set
`GEMINI_STRIP_PII=true` to hold back your name, email, and date of birth. Job
matching uses no AI at all — that's plain keyword scoring, done locally.

**Will it apply to wrong jobs?**
It searches only your `search_roles`, then drops anything whose description doesn't
match your skills, and only submits when every question was answered confidently.
Everything else is flagged for you, with the reason, in the email.

**Why did it only apply to ~50 jobs?**
That's Naukri's daily cap, not a bug. See [section 7](#7-limits-you-should-know).

**How do I stop it?**
Pause or delete the cron-job.org job. (Or repo → **Actions → JobBot Daily → ⋯ →
Disable workflow**.)

---

Made with ☕ and Playwright. Use responsibly — you are applying as yourself.
