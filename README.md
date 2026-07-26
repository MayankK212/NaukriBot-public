# 🤖 JobBot — Auto-apply to Naukri jobs, every day, for free

JobBot finds fresh jobs on **Naukri.com**, fills the screening questions from your
profile, applies to them, and **emails you a report** — automatically, every
morning, running on **GitHub's free servers**. Your computer can stay **off**.

> **In plain words:** you set it up once (about 30–45 min). After that, every day
> at 8:30 AM you get an email listing the jobs it applied to for you.

---

## 📖 Table of contents
1. [What you'll need](#1-what-youll-need)
2. [How it works (30-second version)](#2-how-it-works)
3. [Setup — do this once](#3-setup--do-this-once)
   - [Step 1: Get the code on your computer](#step-1-get-the-code-on-your-computer)
   - [Step 2: Install Python](#step-2-install-python)
   - [Step 3: Install JobBot's requirements](#step-3-install-jobbots-requirements)
   - [Step 4: Free database (MongoDB Atlas)](#step-4-free-database-mongodb-atlas)
   - [Step 5: Gmail App Password (for the email report)](#step-5-gmail-app-password)
   - [Step 6: Your details file (resume_data.json)](#step-6-your-details-file)
   - [Step 7: Save your Naukri login (cookies)](#step-7-save-your-naukri-login)
   - [Step 8: Test it on your computer](#step-8-test-it-on-your-computer)
   - [Step 9: Put the code on GitHub (private)](#step-9-put-the-code-on-github-private)
   - [Step 10: Add your secrets to GitHub](#step-10-add-your-secrets-to-github)
   - [Step 11: Turn on the daily robot](#step-11-turn-on-the-daily-robot)
4. [Everyday use & maintenance](#4-everyday-use--maintenance)
5. [Make it yours (customise)](#5-make-it-yours-customise)
6. [Troubleshooting](#6-troubleshooting)
7. [FAQ](#7-faq)

---

## 1. What you'll need

All **free**. Create these accounts if you don't have them:

| Thing | Why | Link |
|------|-----|------|
| A **Naukri.com** account | So the bot can apply as you | https://www.naukri.com |
| A **Gmail** account | To send you the daily report | https://gmail.com |
| A **GitHub** account | Runs the bot daily for free | https://github.com |
| A **MongoDB Atlas** account | Free cloud database for the jobs | https://www.mongodb.com/atlas |

You do **not** need to keep your PC on. You do **not** need to pay anything.

---

## 2. How it works

```
Every day 8:30 AM  →  GitHub runs the bot  →  finds new jobs  →
answers screening questions from your profile  →  applies  →  emails you the report
```

The bot only auto-submits a job when it can answer **every** question confidently
from your profile. Anything it's unsure about is marked **“needs review”** in the
email so you can finish it by hand.

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

### Step 6: Your details file
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
  "relocation_preference": "Yes",
  "skills": ["SQL", "Python", "Excel", "Power BI"],
  "graduation_year": 2021,
  "highest_education": "B.Tech",
  "ug_degree": "B.Tech",
  "date_of_birth": "DD/MM/YYYY",
  "languages": ["English", "Hindi"],
  "communication_skills_scale_of_10": 8
}
```
- `search_roles` = the job titles to search on Naukri.
- The bot uses these fields to answer screening questions. The more you fill, the
  more it can auto-answer. Add any skill you have to `skills`.

### Step 7: Save your Naukri login
The bot needs to be logged in as you. Run this once — a browser opens, **log in to
Naukri manually**, and it saves your session to `cookies.json`:
```powershell
.\.venv\Scripts\python.exe login_setup.py
```

### Step 8: Test it on your computer
Before going to the cloud, make sure it works locally. Create a file named **`.env`**
in the folder (Notepad) with:
```
MONGO_URI="mongodb+srv://USERNAME:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
EMAIL_USER="you@gmail.com"
EMAIL_PASS="your 16-char app password"
EMAIL_TO="you@gmail.com"
```
Then run the whole pipeline once:
```powershell
.\.venv\Scripts\python.exe run_daily.py
```
If jobs get scraped and you receive an email — 🎉 it works. Now let's make it run
daily in the cloud (so your PC can stay off).

> 🔒 `.env` and `cookies.json` are **never** uploaded to GitHub (they're in
> `.gitignore`). They hold your secrets and stay only on your computer.

### Step 9: Put the code on GitHub (private)
**Easiest (no commands): GitHub Desktop**
1. Install https://desktop.github.com and sign in.
2. **File → Add local repository →** choose your `C:\JobBot` folder → Add.
3. Write a short message → **Commit to main**.
4. Click **Publish repository** → **keep “Keep this code private” ticked** → Publish.

### Step 10: Add your secrets to GitHub
On GitHub, open your repo → **Settings → Secrets and variables → Actions →
New repository secret**. Add these **5** (name on left, your value on right):

| Secret name | What to paste |
|-------------|---------------|
| `MONGO_URI` | your MongoDB connection string from Step 4 |
| `EMAIL_USER` | your Gmail address |
| `EMAIL_PASS` | the 16-char Gmail App Password from Step 5 |
| `EMAIL_TO` | where to receive the report (your email) |
| `NAUKRI_COOKIES` | the **entire contents** of your `cookies.json` file (open it, copy all, paste) |
| `RESUME_JSON` | the **entire contents** of your `resume_data.json` (so your profile stays out of the code) |

> To copy `cookies.json` contents on Windows PowerShell:
> ```powershell
> Get-Content cookies.json -Raw | Set-Clipboard
> ```
> Then just paste (Ctrl+V) into the secret box.

### Step 11: Turn on the daily robot
Your repo → **Actions** tab → **JobBot Daily** (left side) → **Run workflow** →
green **Run workflow** button.

- Watch it run live. In a few minutes you'll get the report email.
- From now on it runs **automatically every day at 8:30 AM IST** — PC off, phone off. ✅

**You're done!** 🎉

---

## 4. Everyday use & maintenance

- **Nothing to do daily** — just read the email each morning.
- **Jobs marked “needs review”** in the email had a question the bot couldn't answer
  confidently. Open those on Naukri and finish them yourself.
- **Refresh your login every few weeks.** Naukri logs sessions out over time. When the
  email shows 0 jobs / apply failures, refresh the cookies:
  ```powershell
  .\.venv\Scripts\python.exe login_setup.py
  ```
  Then copy the new `cookies.json` contents into the `NAUKRI_COOKIES` secret again
  (Step 10). *(This is the only recurring chore.)*

---

## 5. Make it yours (customise)

- **Change which jobs are searched:** edit `search_roles` in `resume_data.json`.
- **Answer more questions automatically:** add the matching field to `resume_data.json`.
  If a new question keeps showing up as “needs review”, the bot needs a rule for it —
  open an issue / ask, with the exact question text.
- **Change the run time:** in `.github/workflows/daily-jobbot.yml`, edit the line
  `cron: "0 3 * * *"`. It's in **UTC**; `0 3 * * *` = 8:30 AM IST. (Add/subtract to shift.)
- **Keep the database in sync** after editing your details:
  ```powershell
  .\.venv\Scripts\python.exe sync_resume.py
  ```

---

## 6. Troubleshooting

| Problem | Fix |
|--------|-----|
| `python` not recognised | Reinstall Python and tick **“Add Python to PATH”** (Step 2). |
| Email not received | Check `EMAIL_PASS` is the **App Password** (not your Gmail login), and check Spam. |
| Workflow can't connect to DB | In Atlas → Network Access, make sure `0.0.0.0/0` is **Active** (Step 4). |
| “JobBot Daily” missing in Actions | Make sure the `.github/workflows/daily-jobbot.yml` file was uploaded, and Settings → Actions → General → **Allow all actions**. |
| 0 jobs found / apply fails | Your Naukri cookies expired — refresh them (Step in section 4). |
| A question got a wrong answer | Update the value in `resume_data.json`, run `sync_resume.py`. |

Every run also saves debug files. On a failed/empty run: repo → that run → **Artifacts
→ jobbot-debug** to download what Naukri actually showed.

---

## 7. FAQ

**Do I need to keep my PC on?**
No. GitHub's servers run it. Your PC is only needed for the one-time setup and to
refresh cookies occasionally.

**Is it really free?**
Yes — GitHub Actions, MongoDB Atlas free tier, and Gmail are all free for this usage.

**Is my data safe?**
Your secrets (DB, email, cookies) live in GitHub **Secrets** and your local `.env` —
never in the code. **Keep your GitHub repo PRIVATE.**

**Will it apply to wrong jobs?**
It searches only your `search_roles`, and only auto-submits when it's confident about
every question. The rest are flagged for you.

**How do I stop it?**
Repo → **Actions → JobBot Daily → ⋯ → Disable workflow**.

---

Made with ☕ and Playwright. Use responsibly — you are applying as yourself.
