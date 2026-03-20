# 📱 Abhi's Android Job Tracker

Live tracker hosted on GitHub Pages, auto-updated 6× daily via GitHub Actions.

**Live URL:** `https://<your-github-username>.github.io/android-tracker/`

---

## 🚀 One-Time Setup (15 minutes)

### Step 1 — Create the GitHub repo

1. Go to [github.com/new](https://github.com/new)
2. Repository name: `android-tracker`
3. Set to **Public**
4. Do NOT initialize with README (you'll push existing files)
5. Click **Create repository**

### Step 2 — Push this project to GitHub

Open your terminal and run:

```bash
# Clone / init
cd /path/to/this/folder
git init
git add .
git commit -m "🚀 initial tracker deploy"

# Connect to GitHub (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/android-tracker.git
git branch -M main
git push -u origin main
```

### Step 3 — Enable GitHub Pages

1. Go to your repo on GitHub
2. Click **Settings** → **Pages** (left sidebar)
3. Under **Source**, select **Deploy from a branch**
4. Branch: `main`, folder: `/ (root)`
5. Click **Save**
6. Wait ~60 seconds, then visit:  
   `https://YOUR_USERNAME.github.io/android-tracker/`

### Step 4 — Add SerpAPI key (optional but recommended)

Without a SerpAPI key the updater falls back to direct ATS scraping,
which works but finds fewer results. SerpAPI free tier = 100 searches/month
(enough for ~16 runs/month at 6 searches each).

1. Sign up free at [serpapi.com](https://serpapi.com)
2. Copy your API key
3. In your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
4. Click **New repository secret**
5. Name: `SERPAPI_KEY`
6. Value: your SerpAPI key
7. Click **Add secret**

### Step 5 — Verify the Action runs

1. Go to your repo → **Actions** tab
2. You should see **🤖 Auto-Update Android Tracker** in the left sidebar
3. Click **Run workflow** → **Run workflow** to trigger a manual test
4. Watch the logs — it should complete in ~2 minutes
5. Check `index.html` for a new commit if new jobs were found

---

## ⏰ Update Schedule

The tracker auto-updates at these times **EST** every day:

| Time (EST) | UTC |
|---|---|
| 9:00 AM | 14:00 |
| 12:00 PM | 17:00 |
| 3:00 PM | 20:00 |
| 6:00 PM | 23:00 |
| 9:00 PM | 02:00 +1d |
| 12:00 AM | 05:00 |

> **Note:** GitHub Actions cron has ~5 min variance. Not exact to the second.

---

## 📂 File Structure

```
android-tracker/
├── index.html              ← The tracker (auto-updated)
├── requirements.txt        ← Python deps
├── scripts/
│   └── update_tracker.py  ← Scraper + injector
└── .github/
    └── workflows/
        └── update-tracker.yml  ← GitHub Actions schedule
```

---

## 🔧 Manual Update

To trigger an update manually anytime:

1. GitHub repo → **Actions** tab
2. Click **🤖 Auto-Update Android Tracker**
3. Click **Run workflow** → **Run workflow**

Or from terminal (if you have `gh` CLI):
```bash
gh workflow run update-tracker.yml
```

---

## 🛠 Customizing the Scraper

Edit `scripts/update_tracker.py` to:

- **Add companies to watch:** Add to `greenhouse_companies` list
- **Change search queries:** Edit `SEARCH_QUERIES` list  
- **Adjust region/level detection:** Edit `REGION_KEYWORDS` / `LEVEL_KEYWORDS`

---

## 🔄 Updating Manually From Claude

When you're in a Claude session, say:
> *"find me android all jobs"*

Claude will run a full sweep and inject results directly into your local tracker file. Then push to GitHub:

```bash
git add index.html
git commit -m "manual sweep · $(date +'%Y-%m-%d')"
git push
```

GitHub Pages auto-publishes within ~60 seconds.

---

## ⚠️ Troubleshooting

**Action fails with permission error:**  
Go to repo **Settings** → **Actions** → **General** → set  
*Workflow permissions* to **Read and write permissions**

**GitHub Pages shows 404:**  
Wait 2–3 minutes after enabling. If still 404, check Settings → Pages shows "Your site is live at..."

**No new jobs being found:**  
Add a SerpAPI key (Step 4). Direct scraping may miss jobs on some ATSes.

**Duplicate entries appearing:**  
The script deduplicates by URL. If a company changes their job URL, it may re-add. Check `index.html` and remove manually if needed.
