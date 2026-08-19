# Deploy Guide — JobBot Dashboard online (Render.com)

Dashboard ko web pe host karne ke liye ye steps follow karo. ~10 min lagte hain.
Recruiters ko URL share karna hai — koi install/run ki zaroorat nahi, sirf link.

> **Security note:** `MONGO_URI` (Atlas connection string) hamesha Render ke
> secret field mein rakha jaata hai. Ye repo mein ya browser mein kabhi nahi jaata.

---

## Step 1 — Ye files push karo GitHub pe

Pehle is commit ko apne `NaukriBot` repo (private) pe push karo:

```
git add dashboard/requirements.txt render.yaml dashboard/DEPLOY.md
git commit -m "Add Render.com deployment config for online dashboard"
git push
```

Sabse zaroori cheez: `dashboard/requirements.txt` (dependencies) aur `render.yaml`
(Blueprint — Render ise automatically padhta hai).

---

## Step 2 — Render pe account banao (free)

1. Browser mein kholo: **https://render.com**
2. **"Get Started"** → **"Sign up with GitHub"** → apna GitHub account connect karo.
3. Koi credit card nahi chahiye (free plan hai).

---

## Step 3 — Blueprint deploy karo

1. Render dashboard mein **"New +"** button → **"Blueprint"** chuno.
2. Render apne GitHub repos dikhayega → **`<your-username>/NaukriBot`** select karo.
3. Render `render.yaml` padhega aur `jobbot-dashboard` service bana dega.
   - **URL note:** Agar `jobbot-dashboard` naam pehle se kisi aur service ke
     paas hai, Render suffix add karta hai (jaise `-zhft`). Asli URL check
     karo Render dashboard → service → **"On Render"** section mein.
   - Is repo ke case mein URL hai: **`https://jobbot-dashboard-zhft.onrender.com`**
4. **"Apply Blueprint"** pe click karo.

---

## Step 4 — MONGO_URI secret bharo (sabse important)

Blueprint banne ke baad:

1. Render dashboard mein apni **`jobbot-dashboard`** service kholo.
2. Left sidebar mein **"Environment"** pe jao.
3. `MONGO_URI` wali row dikhegi (value khaali hai — by design).
4. **Edit** karke value paste karo apne `D:\JobBot\.env` se:
   ```
   mongodb+srv://<user>:<password>@cluster0.mongodb.net/...
   ```
5. **Save** karo.

> Agar value khaali chhod di toh dashboard loads hoga nahi (Mongo connect nahi
> hoga). Secret isliye `sync: false` hai — repo mein kabhi nahi jaata.

---

## Step 5 — Deploy ho jane do

- Render automatically build+deploy karega. Logs me `Dashboard ready` type kuch
  aayega (gunicorn started).
- Kuch minutes lag sakte hain (pehla build: dependencies install).
- URL: **https://jobbot-dashboard-zhft.onrender.com**

**Check karo:**
- KPI cards numbers dikha rahe hain? (Total Applied / Pending / etc.)
- Filters kaam kar rahe hain?
- Kisi job pe click karke drill-down panel khul raha hai?

---

## Step 6 — Keep-alive pinger (talwar: free plan so jaata hai)

Render ka free plan **~15 min idle** ke baad service "sleep" kar deta hai. Agla
request aane pe 30-60s lagte hain wapas jaagne mein. Recruiters ke saamne ye
sharminda kar sakta hai.

Isse theek karne ke liye `keepalive.yml` workflow (GitHub Actions) har 10 min
me URL pe ping karta hai → service kabhi sotee nahi.

Is file ko abhi add karna (URL update ke saath):

```
# .github/workflows/keepalive.yml
name: keepalive
on:
  schedule:
    - cron: '*/10 * * * *'
  workflow_dispatch:
jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - run: curl -sS -o /dev/null -w "%{http_code}" https://jobbot-dashboard-zhft.onrender.com/ || true
```

Push karo. GitHub Actions har 10 min pe chalega, dashboard jaga rahega.

> Note: GitHub Actions free tier pe scheduled workflows have a minimum interval —
> 10 min is the practical floor, so `*/10` is right.

---

## Future updates (dashboard mein koi bhi change)

Sirf GitHub pe push karo → Render **auto-redeploy** kar dega. Kuch bhi manually
karne ki zaroorat nahi.

```
git add dashboard/
git commit -m "describe change"
git push
```

---

## Troubleshooting

- **Dashboard khulta hai, numbers nahi aate / error:** MONGO_URI check karo
  (Render → Environment). Galti se khali hai toh Atlas connect nahi hoga.
- **"Internal Server Error" on /api/funnel:** pandas install ho gaya hoga
  requirements se. Agar nahi, Render console: `pip install pandas`.
- **Cold start (30-60s pehli baar):** Keep-alive pinger laga do (Step 6).
- **Deploy fail build step:** Render ke Logs tab mein error dekho. Sabse common:
  `gunicorn: command not found` → matlab requirements.txt push nahi hui.
- **URL change:** Agar service ka naam badla toh URL bhi badlega. Keep-alive
  workflow mein bhi naya URL daalo.
