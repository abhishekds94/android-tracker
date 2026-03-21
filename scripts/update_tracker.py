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

    # Index 9 — LinkedIn posts: "hiring" + "Android" US/global
    {"query": 'site:linkedin.com/posts "hiring" "Android" "Senior" "Kotlin" -inurl:jobs -inurl:company',
     "engine": "google", "location": None, "gl": "us", "hl": "en",
     "region": None, "chips": None, "is_li_post": True},

    # Index 10 — LinkedIn posts: "hiring" + "Android" EU
    {"query": 'site:linkedin.com/posts "hiring" "Android" ("Berlin" OR "Amsterdam" OR "Dublin" OR "Germany" OR "Netherlands")',
     "engine": "google", "location": None, "gl": "us", "hl": "en",
     "region": "EU", "chips": None, "is_li_post": True},
]

# ─── BUDGET ROTATION: UTC hour → which search indices to run ─────────────────
# US is primary → runs EVERY day
# EU is secondary → runs every ODD calendar day only
#
# Daily search count:
#   Odd days  (EU active):  9am(2)+12pm(2)+3pm(1)+6pm(3)+9pm(2) = 10
#   Even days (EU skipped): 3pm(1)+6pm(3)+9pm(2) = 6
#   Monthly: (10×15)+(6×15) = 150+90 = 240 ✅ under 250
#
HOUR_TO_BATCHES = {
    14: [4, 5],      # 9am  EST — EU Dublin + India      (odd days only)
    17: [2, 3],      # 12pm EST — EU Germany + Amsterdam (odd days only)
    20: [0],         # 3pm  EST — US Senior              (EVERY day — US is primary)
    23: [6, 7, 8],   # 6pm  EST — Greenhouse + Lever + Ashby
    2:  [9, 10],     # 9pm  EST — LinkedIn posts US + EU
}

def get_batches_for_hour(utc_hour):
    batches = HOUR_TO_BATCHES.get(utc_hour, [])
    # Skip EU slots (9am + 12pm) on even calendar days
    if utc_hour in (14, 17) and datetime.date.today().day % 2 == 0:
        return []
    return batches

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
    is_li_post = s.get("is_li_post", False)
    try:
        data = requests.get(SERPAPI_URL, params=params, timeout=25).json()
        if "error" in data:
            print(f"  SerpAPI error: {data['error']}"); return []

        results = data.get("organic_results", [])
        jobs = []

        for r in results:
            url     = r.get("link","")
            snippet = r.get("snippet","")
            t_raw   = r.get("title","")

            # ── LinkedIn POST handling ─────────────────────────────────────
            if is_li_post:
                if "linkedin.com/posts" not in url: continue
                # Extract poster name from title e.g. "John Smith on LinkedIn: ..."
                poster = ""
                post_title = ""
                if " on LinkedIn:" in t_raw:
                    parts = t_raw.split(" on LinkedIn:", 1)
                    poster = parts[0].strip()
                    post_title = parts[1].strip().strip('"').strip()
                else:
                    post_title = t_raw

                # Extract company from snippet — look for capitalized names
                co = ""
                co_match = re.search(
                    r'(?:at|@|from|joining)\s+([A-Z][a-zA-Z0-9& ]{2,30}?)(?:\s+(?:is|we|are|for|\.|,|!|–))',
                    snippet)
                if co_match: co = co_match.group(1).strip()
                if not co: co = poster  # fallback: poster IS the contact

                region = detect_region(snippet + " " + url, s.get("region"))

                jobs.append({
                    "title":    f"LinkedIn Post — {poster}" if poster else "LinkedIn Hiring Post",
                    "company":  co or "Unknown",
                    "location": "",
                    "url":      url,
                    "source":   "LinkedIn Post",
                    "region":   region,
                    "note":     f"{poster}: {snippet[:120]}" if poster else snippet[:120],
                    "is_li_post": True,
                    "poster":   poster,
                    "desc":     snippet[:300],
                    "post_title": post_title,
                })
                continue

            # ── Regular ATS / job page handling ───────────────────────────
            if not any(a in url for a in ["greenhouse.io","lever.co","ashbyhq.com",
                                           "jobs.ashbyhq","linkedin.com/jobs"]):
                continue
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

        label = "linkedin_posts" if is_li_post else s['query'][:45]
        print(f"  ✓ google [{label}…] → {len(jobs)} results")
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
    # LinkedIn posts go through a separate path — always allow
    if job.get("is_li_post"): return bool(job.get("url",""))

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


def inject_li_posts(content, li_entries):
    """Inject new LinkedIn post entries into the LI_POSTS array."""
    if not li_entries: return content, 0

    # Find end of LI_POSTS array
    li_start = content.find('const LI_POSTS=[')
    if li_start == -1: return content, 0
    # Find the closing ]; of LI_POSTS
    li_end = content.find('];\n', li_start)
    if li_end == -1: return content, 0

    ts  = datetime.datetime.utcnow().strftime('%H:%M UTC')
    hdr = f"\n  // ─── AUTO LI · {TODAY} · {ts} ───\n"
    blk = hdr + ",\n".join(li_entries) + ",\n"
    return content[:li_end] + blk + content[li_end:], len(li_entries)


def build_li_entry(job):
    """Build a LI_POSTS JS entry from a scraped LinkedIn post."""
    co      = esc(job.get("company","Unknown"))
    poster  = esc(job.get("poster",""))
    desc    = esc(job.get("desc",""))
    url     = job.get("url","")
    region  = job.get("region","Remote")
    note    = esc(job.get("note",""))
    title   = esc(job.get("post_title","Android Hiring Post"))
    lv      = "Senior"

    return (
        f'  {{co:"{co}",role:"{title}",'
        f'loc:"",region:"{region}",lv:"{lv}",'
        f'postType:"LinkedIn Post",'
        f'desc:"{desc}",'
        f'posted:"{TODAY}",'
        f'url:"{url}",'
        f'contact:"{poster}"}}'
    )

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
    batches  = get_batches_for_hour(utc_hour)
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

    # Split LinkedIn posts from regular job listings
    raw_posts = [j for j in all_jobs if j.get("is_li_post")]
    raw_jobs  = [j for j in all_jobs if not j.get("is_li_post")]

    # Deduplicate + filter regular jobs
    seen, new_jobs = set(existing_urls), []
    for job in raw_jobs:
        url = re.sub(r'\?utm_.*', '', job.get("url","").strip())
        url = re.sub(r'&utm_[^&]*', '', url)
        if not url or url in seen: continue
        if not is_relevant(job):   continue
        seen.add(url)
        job["url"] = url
        new_jobs.append(job)

    # Deduplicate LinkedIn posts (by URL)
    seen_li = set(re.findall(r'url:"([^"]+)"', content))  # existing LI post URLs
    new_li_posts = []
    for post in raw_posts:
        url = post.get("url","").strip()
        if not url or url in seen_li: continue
        seen_li.add(url)
        new_li_posts.append(post)

    print(f"New jobs: {len(new_jobs)} | New LI posts: {len(new_li_posts)}\n")

    if not new_jobs and not new_li_posts:
        print("Nothing new — tracker unchanged."); return

    # Build + inject job entries
    job_entries = []
    for job in new_jobs:
        print(f"  + {job.get('company','?')} — {job.get('title','?')[:50]}")
        job_entries.append(build_entry(job))

    # Build + inject LinkedIn post entries
    li_entries = []
    for post in new_li_posts:
        print(f"  📣 LI post: {post.get('poster','?')} — {post.get('desc','')[:60]}")
        li_entries.append(build_li_entry(post))

    updated = content
    job_count = li_count = 0

    if job_entries:
        updated, job_count = inject(updated, job_entries)
    if li_entries:
        updated, li_count = inject_li_posts(updated, li_entries)

    updated = update_title(updated)
    save_tracker(updated)
    print(f"\n✅  +{job_count} jobs, +{li_count} LinkedIn posts → {TRACKER_FILE}")

    # GitHub step summary
    sp = os.environ.get("GITHUB_STEP_SUMMARY","")
    if sp:
        with open(sp,"a") as f:
            f.write(f"## 🤖 Tracker Update · {TODAY}\n\n")
            f.write(f"**+{job_count} jobs, +{li_count} LinkedIn posts** | Batches: {batches}\n\n")
            for j in new_jobs:
                f.write(f"- [{j.get('company','?')} — {j.get('title','?')}]({j.get('url','#')})\n")
            for p in new_li_posts:
                f.write(f"- 📣 [{p.get('poster','?')}]({p.get('url','#')}): {p.get('desc','')[:80]}\n")

if __name__ == "__main__":
    main()