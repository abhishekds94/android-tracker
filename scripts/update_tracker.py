#!/usr/bin/env python3
"""
Android Job Tracker — Auto Updater v2
Uses SerpAPI google_jobs engine which aggregates:
  LinkedIn, Glassdoor, BuiltIn, Indeed, Naukri, Greenhouse, Lever, Ashby,
  AngelList/Wellfound, ZipRecruiter, Dice, and 100s more — all in ONE search.

Budget: 250 searches/month
Strategy: rotate 10 search configs across 5 active runs/day = ~240/month
Regions: US/Remote, EU (Berlin/Amsterdam/Dublin), India (Bengaluru)
"""

import re, os, sys, json, time, datetime, requests

TRACKER_FILE   = "index.html"
TODAY          = datetime.date.today().strftime("%Y-%m-%d")
SERPAPI_KEY    = os.environ.get("SERPAPI_KEY", "")
SERPAPI_URL    = "https://serpapi.com/search.json"

# ─── ALL SEARCH CONFIGS ───────────────────────────────────────────────────────
# google_jobs engine aggregates LinkedIn, Glassdoor, BuiltIn, Indeed, Naukri,
# Greenhouse, Lever, Ashby, Wellfound, ZipRecruiter, Dice, SimplyHired, etc.

SEARCHES = [
    # Index 0 — US Senior Android (last 7 days)
    {"query": "Senior Android Engineer Kotlin Jetpack Compose",
     "engine": "google_jobs", "location": "United States",
     "gl": "us", "hl": "en", "region": "US", "chips": "date_posted:week"},

    # Index 1 — US Staff / Principal (last month)
    {"query": "Staff Android Engineer OR Principal Android Engineer Kotlin",
     "engine": "google_jobs", "location": "United States",
     "gl": "us", "hl": "en", "region": "US", "chips": "date_posted:month"},

    # Index 2 — EU Berlin
    {"query": "Senior Android Engineer Kotlin Jetpack Compose",
     "engine": "google_jobs", "location": "Berlin, Germany",
     "gl": "de", "hl": "en", "region": "EU", "chips": "date_posted:month"},

    # Index 3 — EU Amsterdam
    {"query": "Senior Android Engineer Kotlin",
     "engine": "google_jobs", "location": "Amsterdam, Netherlands",
     "gl": "nl", "hl": "en", "region": "EU", "chips": "date_posted:month"},

    # Index 4 — EU Dublin
    {"query": "Senior Android Engineer Kotlin Jetpack Compose",
     "engine": "google_jobs", "location": "Dublin, Ireland",
     "gl": "ie", "hl": "en", "region": "EU", "chips": "date_posted:month"},

    # Index 5 — India Bengaluru
    {"query": "Senior Android Engineer Kotlin Jetpack Compose",
     "engine": "google_jobs", "location": "Bengaluru, Karnataka, India",
     "gl": "in", "hl": "en", "region": "🇮🇳 India", "chips": "date_posted:month"},

    # Index 6 — Greenhouse direct ATS
    {"query": 'site:greenhouse.io "Senior Android Engineer" OR "Staff Android Engineer" Kotlin',
     "engine": "google", "location": None, "gl": "us", "hl": "en", "region": None, "chips": None},

    # Index 7 — Lever direct ATS
    {"query": 'site:lever.co "Senior Android Engineer" OR "Senior Mobile Engineer" Android Kotlin',
     "engine": "google", "location": None, "gl": "us", "hl": "en", "region": None, "chips": None},

    # Index 8 — Ashby direct ATS
    {"query": 'site:ashbyhq.com "Senior Android" OR "Staff Android" Kotlin',
     "engine": "google", "location": None, "gl": "us", "hl": "en", "region": None, "chips": None},

    # Index 9 — LinkedIn hiring posts
    {"query": '"Senior Android Engineer" "we are hiring" OR "now hiring" OR "open role" Kotlin 2026',
     "engine": "google", "location": None, "gl": "us", "hl": "en", "region": None, "chips": None},
]

# ─── BUDGET ROTATION: UTC hour → which search indices to run ─────────────────
# 5 active runs/day × 2 searches = 10/day × 30 = 300 (trim 12am = 240 ✅)
HOUR_TO_BATCHES = {
    14: [0, 1],   # 9am  EST — US Senior + US Staff
    17: [2, 3],   # 12pm EST — EU Berlin + Amsterdam
    20: [4, 5],   # 3pm  EST — EU Dublin + India
    23: [6, 7],   # 6pm  EST — Greenhouse + Lever
    2:  [8, 9],   # 9pm  EST — Ashby + LinkedIn posts
    5:  [],       # 12am EST — skip (budget save)
}

# ─── REGION / LEVEL / VISA ───────────────────────────────────────────────────

REGION_KW = {
    "US": ["united states","remote us","us remote","new york","san francisco",
           "seattle","austin","chicago","boston","menlo park","mountain view",
           "remote - us","los angeles"],
    "EU": ["berlin","germany","amsterdam","netherlands","dublin","ireland",
           "london","stockholm","paris","munich","hamburg","europe",
           "remote eu","eu remote"],
    "🇮🇳 India": ["bengaluru","bangalore","india","mumbai","hyderabad",
                  "pune","chennai","noida","gurgaon","gurugram"],
    "Remote": ["remote global","worldwide","fully remote","work from anywhere"],
}

LEVEL_KW = {
    "Staff":     ["staff android","staff software","staff mobile","staff engineer"],
    "Principal": ["principal android","principal engineer","principal mobile"],
    "Senior":    ["senior android","senior software","senior mobile",
                  "senior engineer","sr. android","sr android"],
}

KNOWN_H1B = {"google","airbnb","meta","apple","amazon","netflix","stripe",
             "robinhood","verkada","reddit","snap","lyft","uber","doordash",
             "coinbase","spotify","linkedin","microsoft","walmart","target",
             "cvs","expedia","booking.com","adyen","salesforce","oracle"}

def detect_region(text, default=None):
    t = text.lower()
    for r, kws in REGION_KW.items():
        if any(k in t for k in kws):
            return r
    return default or "Remote"

def detect_level(title):
    t = title.lower()
    for lv, kws in LEVEL_KW.items():
        if any(k in t for k in kws):
            return lv
    return "Senior"

def detect_visa(region, company):
    co = company.lower()
    if region == "EU":         return "EU Blue Card eligible"
    if region == "🇮🇳 India": return "No visa needed"
    if region == "Remote":     return "Global remote · verify"
    if any(s in co for s in KNOWN_H1B): return "Known H-1B ✓"
    return "Verify H-1B"

def esc(s): return str(s).replace('"',"'").replace('\n',' ').replace('\r','').strip()

# ─── TRACKER I/O ─────────────────────────────────────────────────────────────

def load_tracker():
    with open(TRACKER_FILE, "r", encoding="utf-8") as f: return f.read()

def save_tracker(content):
    with open(TRACKER_FILE, "w", encoding="utf-8") as f: f.write(content)

def get_existing_urls(content):
    return set(re.findall(r'url:"([^"]+)"', content))

# ─── SERPAPI ─────────────────────────────────────────────────────────────────

def call_google_jobs(s):
    params = {"engine":"google_jobs","q":s["query"],"api_key":SERPAPI_KEY,
              "hl":s.get("hl","en"),"gl":s.get("gl","us"),"num":10}
    if s.get("location"): params["location"] = s["location"]
    if s.get("chips"):    params["chips"]    = s["chips"]
    try:
        data = requests.get(SERPAPI_URL, params=params, timeout=25).json()
        if "error" in data:
            print(f"  SerpAPI error: {data['error']}"); return []
        jobs = []
        for j in data.get("jobs_results", []):
            title    = j.get("title","")
            company  = j.get("company_name","")
            location = j.get("location","")
            via      = j.get("via","").replace("via ","")
            desc     = j.get("description","")[:300]
            exts     = j.get("extensions",[])

            # Best apply URL: prefer ATS over aggregator
            apply_url = ""
            for opt in j.get("apply_options",[]):
                lnk = opt.get("link","")
                if any(a in lnk for a in ["greenhouse.io","lever.co","ashbyhq.com",
                                           "workday","smartrecruiters"]):
                    apply_url = lnk; break
            if not apply_url:
                opts = j.get("apply_options",[])
                if opts: apply_url = opts[0].get("link","")

            # Note: posted time + tech keywords
            note_parts = [x for x in exts if any(k in x.lower()
                          for k in ["ago","full-time","remote","contract"])]
            techs = [kw for kw in ["Kotlin","Compose","KMP","MVI","MVVM","Hilt",
                                    "Coroutines","Flow","Multiplatform"]
                     if kw.lower() in desc.lower()]
            if techs: note_parts.append(" · ".join(techs[:4]))
            if via and via not in note_parts: note_parts.insert(0, via)

            region = detect_region(f"{title} {company} {location} {desc}",
                                   s.get("region"))
            jobs.append({"title":title,"company":company,"location":location,
                         "url":apply_url,"source":via or "Google Jobs",
                         "region":region,
                         "note":" · ".join(note_parts) if note_parts else via})
        print(f"  ✓ google_jobs [{s.get('location','global')}] → {len(jobs)} results")
        return jobs
    except Exception as e:
        print(f"  ✗ google_jobs error: {e}"); return []


def call_google_search(s):
    params = {"engine":"google","q":s["query"],"api_key":SERPAPI_KEY,
              "hl":s.get("hl","en"),"gl":s.get("gl","us"),"num":10}
    try:
        data = requests.get(SERPAPI_URL, params=params, timeout=25).json()
        if "error" in data:
            print(f"  SerpAPI error: {data['error']}"); return []
        jobs = []
        for r in data.get("organic_results",[]):
            url     = r.get("link","")
            snippet = r.get("snippet","")
            t_raw   = r.get("title","")
            # Only ATS or LinkedIn job pages
            if not any(a in url for a in ["greenhouse.io","lever.co","ashbyhq.com",
                                           "jobs.ashbyhq","linkedin.com/jobs"]):
                continue
            # Parse role + company
            if " at " in t_raw:
                role, company = t_raw.split(" at ",1)
            else:
                role = t_raw; company = ""
            for sfx in ["|Greenhouse","- Lever","- Ashby","|LinkedIn",
                        " Jobs"," Careers","|"]:
                role    = role.replace(sfx,"").strip()
                company = company.replace(sfx,"").strip()

            src = ("Greenhouse" if "greenhouse.io" in url else
                   "Lever"      if "lever.co"      in url else
                   "Ashby"      if "ashbyhq.com"   in url else
                   "LinkedIn"   if "linkedin.com"  in url else "Google")

            region = detect_region(f"{role} {company} {snippet}", s.get("region"))
            jobs.append({"title":role,"company":company,"location":"",
                         "url":url,"source":src,"region":region,
                         "note":snippet[:120]})
        print(f"  ✓ google_search [{s['query'][:45]}…] → {len(jobs)} results")
        return jobs
    except Exception as e:
        print(f"  ✗ google_search error: {e}"); return []

# ─── FILTERS ─────────────────────────────────────────────────────────────────

SENIOR_KW = ["senior","staff","principal","lead","sr.","sr "]
SKIP_KW   = ["ios only","flutter","react native","intern","junior",
             "associate engineer","qa ","devops","backend only",
             "data engineer","data scientist","product manager",
             "frontend engineer","web engineer"]

def is_relevant(job):
    title = job.get("title","").lower()
    url   = job.get("url","")
    if not url or len(url) < 10: return False
    if not any(k in title for k in SENIOR_KW): return False
    if "android" not in title and "mobile" not in title: return False
    if any(k in title for k in SKIP_KW): return False
    if any(b in url for b in ["linkedin.com/company","glassdoor.com/Overview",
                               "serpapi.com","builtin.com/company"]): return False
    return True

# ─── ENTRY BUILDER ───────────────────────────────────────────────────────────

def build_entry(job):
    title    = esc(job.get("title","Android Engineer"))
    company  = esc(job.get("company","Unknown"))
    location = esc(job.get("location","Remote"))
    url      = job.get("url","")
    source   = esc(job.get("source","Google Jobs"))
    note     = esc(job.get("note","Auto-discovered"))
    region   = job.get("region", detect_region(f"{title} {location}"))
    level    = detect_level(title)
    visa     = detect_visa(region, company)
    return (f'  {{added:"{TODAY}",co:"{company}",role:"{title}",'
            f'loc:"{location}",region:"{region}",lv:"{level}",'
            f'visa:"{visa}",note:"{note}",src:"{source}",'
            f'url:"{url}",isNew:true}}')

# ─── INJECT ──────────────────────────────────────────────────────────────────

def inject(content, entries):
    if not entries: return content, 0
    content = re.sub(r',isNew:true}', ',isNew:false}', content)
    marker = '];\n\n// ─── LINKEDIN POSTS DATA ───'
    idx = content.find(marker)
    if idx == -1:
        marker = '];\nconst LI_POSTS'
        idx = content.find(marker)
    if idx == -1:
        print("✗ Injection point not found!"); return content, 0
    ts  = datetime.datetime.utcnow().strftime('%H:%M UTC')
    hdr = f"\n  // ─── AUTO · {TODAY} · {ts} ───\n"
    blk = hdr + ",\n".join(entries) + ",\n"
    return content[:idx] + blk + content[idx:], len(entries)

def update_title(content):
    my = datetime.date.today().strftime("%b %Y")
    return re.sub(r'Android Job Tracker · [A-Za-z]+ \d{4}',
                  f'Android Job Tracker · {my}', content)

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*55}")
    print(f"  Android Tracker Auto-Update  {TODAY}")
    print(f"  {datetime.datetime.utcnow().strftime('%H:%M UTC')}")
    print(f"{'='*55}\n")

    if not SERPAPI_KEY:
        print("✗ SERPAPI_KEY not set. Exiting."); sys.exit(1)

    utc_hour = datetime.datetime.utcnow().hour
    batches  = HOUR_TO_BATCHES.get(utc_hour, [0, 5])
    print(f"UTC {utc_hour}h → batches {batches}")

    if not batches:
        print("No searches this hour (budget save). Done."); return

    # Load tracker
    content       = load_tracker()
    existing_urls = get_existing_urls(content)
    print(f"Existing: {len(existing_urls)} URLs\n")

    # Run searches
    all_jobs = []
    for idx in batches:
        if idx >= len(SEARCHES): continue
        s = SEARCHES[idx]
        print(f"[{idx}] {s['engine']} | {s['query'][:55]}")
        if s["engine"] == "google_jobs":
            all_jobs.extend(call_google_jobs(s))
        else:
            all_jobs.extend(call_google_search(s))
        time.sleep(2)

    print(f"\nRaw: {len(all_jobs)} results")

    # Deduplicate + filter
    seen, new_jobs = set(existing_urls), []
    for job in all_jobs:
        url = re.sub(r'\?utm_.*', '', job.get("url","").strip())
        url = re.sub(r'&utm_[^&]*', '', url)
        if not url or url in seen: continue
        if not is_relevant(job):   continue
        seen.add(url)
        job["url"] = url
        new_jobs.append(job)

    print(f"New unique relevant: {len(new_jobs)}\n")

    if not new_jobs:
        print("Nothing new — tracker unchanged."); return

    entries = []
    for job in new_jobs:
        print(f"  + {job.get('company','?')} — {job.get('title','?')[:50]}")
        entries.append(build_entry(job))

    updated, count = inject(content, entries)
    updated = update_title(updated)
    save_tracker(updated)
    print(f"\n✅  +{count} jobs → {TRACKER_FILE}")

    # GitHub step summary
    sp = os.environ.get("GITHUB_STEP_SUMMARY","")
    if sp:
        with open(sp,"a") as f:
            f.write(f"## 🤖 Tracker Update · {TODAY}\n\n")
            f.write(f"**+{count} new jobs** | Batches: {batches}\n\n")
            for j in new_jobs:
                f.write(f"- [{j.get('company','?')} — {j.get('title','?')}]({j.get('url','#')})\n")

if __name__ == "__main__":
    main()
