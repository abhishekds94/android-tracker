#!/usr/bin/env python3
"""
Android Job Tracker Auto-Updater
Scrapes Greenhouse, Lever, Ashby for new Senior Android roles
and injects them into index.html
Runs via GitHub Actions on schedule.
"""

import re
import os
import json
import time
import datetime
import requests
from urllib.parse import quote

# ── CONFIG ────────────────────────────────────────────────────────────────────

TRACKER_FILE = "index.html"
TODAY = datetime.date.today().strftime("%Y-%m-%d")

SEARCH_QUERIES = [
    # Greenhouse
    'site:greenhouse.io "Senior Android Engineer" OR "Android Engineer" -"iOS"',
    'site:greenhouse.io "Staff Android Engineer" OR "Principal Android Engineer"',
    'site:greenhouse.io "Senior Software Engineer" "Android" "Kotlin"',
    # Lever
    'site:lever.co "Senior Android Engineer" OR "Android Engineer" "Kotlin"',
    'site:lever.co "Senior Mobile Engineer" "Android"',
    # Ashby
    'site:ashbyhq.com "Senior Android Engineer" OR "Android Engineer"',
    'site:jobs.ashbyhq.com "Android" "Senior"',
    # EU specific
    'site:greenhouse.io "Android" "Berlin" OR "Amsterdam" OR "Dublin" "Senior"',
    'site:lever.co "Android" "Berlin" OR "Amsterdam" OR "Dublin"',
]

REGION_KEYWORDS = {
    "US": ["remote us", "united states", "san francisco", "new york", "seattle",
           "austin", "chicago", "boston", "remote - us", "us remote", "remote (us"],
    "EU": ["berlin", "amsterdam", "dublin", "london", "munich", "hamburg",
           "stockholm", "paris", "europe", "remote eu", "eu remote"],
    "Remote": ["remote global", "worldwide", "fully remote", "work from anywhere"],
    "🇮🇳 India": ["bangalore", "bengaluru", "india", "mumbai", "hyderabad", "pune"],
}

LEVEL_KEYWORDS = {
    "Staff": ["staff android", "staff software", "staff mobile"],
    "Principal": ["principal android", "principal engineer"],
    "Senior": ["senior android", "senior software", "senior mobile", "senior engineer"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; job-tracker-bot/1.0)"
}

# ── HELPERS ───────────────────────────────────────────────────────────────────

def load_tracker():
    with open(TRACKER_FILE, "r", encoding="utf-8") as f:
        return f.read()

def save_tracker(content):
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def get_existing_urls(content):
    """Extract all URLs already in the tracker for deduplication."""
    return set(re.findall(r'url:"([^"]+)"', content))

def get_existing_cos(content):
    """Extract company names already in tracker."""
    return set(re.findall(r'co:"([^"]+)"', content))

def detect_region(text):
    text_lower = text.lower()
    for region, kws in REGION_KEYWORDS.items():
        if any(kw in text_lower for kw in kws):
            return region
    return "Remote"

def detect_level(title):
    title_lower = title.lower()
    for level, kws in LEVEL_KEYWORDS.items():
        if any(kw in title_lower for kw in kws):
            return level
    return "Senior"

def detect_visa(region, company_name):
    known_sponsors = ["google", "airbnb", "meta", "apple", "amazon", "netflix",
                      "stripe", "robinhood", "verkada", "reddit", "snap", "lyft",
                      "uber", "doordash", "coinbase", "spotify"]
    co_lower = company_name.lower()
    if region == "EU":
        return "EU Blue Card eligible"
    if region == "🇮🇳 India":
        return "No visa needed"
    if region == "Remote":
        return "Global remote · verify"
    if any(s in co_lower for s in known_sponsors):
        return "Known H-1B ✓"
    return "Verify H-1B"

def search_google(query, serpapi_key=None):
    """
    Search using SerpAPI (free tier: 100 searches/month).
    Falls back to direct URL scraping if no key.
    """
    if not serpapi_key:
        return []
    
    url = "https://serpapi.com/search"
    params = {
        "q": query,
        "api_key": serpapi_key,
        "num": 10,
        "engine": "google",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        results = []
        for r in data.get("organic_results", []):
            results.append({
                "url": r.get("link", ""),
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
            })
        return results
    except Exception as e:
        print(f"SerpAPI error: {e}")
        return []

def scrape_ats_directly():
    """
    Direct ATS scraping without search API.
    Hits known job board listing pages directly.
    """
    sources = [
        # Greenhouse Android searches
        ("https://job-boards.greenhouse.io/embed/job_board?for=&q=android+senior&limit=25", "Greenhouse"),
        # Ashby - no public listing API, skip
    ]
    
    jobs = []
    
    # Fetch from known high-signal pages
    greenhouse_companies = [
        "airbnb", "robinhood", "reddit", "duolingo", "grammarly", "coinbase",
        "stripe", "lyft", "snap", "pinterest", "instacart", "doordash",
        "wealthsimple", "nytimes", "figma", "notion", "linear", "vercel",
        "ramp", "brex", "plaid", "chime", "earnin", "acorns", "strava",
        "headspace", "calm", "peloton", "fetch", "duckduckgo", "revenuecat",
        "gamechanger", "fullstory", "honor", "hungryroot", "verkada", "toast",
        "omadahealth", "hinge", "bumble", "meetup", "eventbrite",
    ]
    
    for company in greenhouse_companies:
        url = f"https://job-boards.greenhouse.io/{company}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            
            # Find Android jobs in the page
            content = resp.text
            android_pattern = re.compile(
                r'href="(/[^"]*jobs/(\d+)[^"]*)"[^>]*>[^<]*(?:android|mobile)[^<]*</a>',
                re.IGNORECASE
            )
            for match in android_pattern.finditer(content):
                path = match.group(1)
                job_id = match.group(2)
                # Get job title from surrounding context
                title_match = re.search(
                    rf'href="{re.escape(path)}"[^>]*>([^<]+)</a>',
                    content, re.IGNORECASE
                )
                title = title_match.group(1).strip() if title_match else "Android Engineer"
                
                # Filter for senior+ roles
                if not any(kw in title.lower() for kw in ["senior", "staff", "principal", "lead"]):
                    continue
                    
                full_url = f"https://job-boards.greenhouse.io{path}"
                jobs.append({
                    "url": full_url,
                    "title": title,
                    "company": company.replace("-", " ").title(),
                    "source": "Greenhouse",
                })
            
            time.sleep(0.5)  # Be polite
            
        except Exception as e:
            print(f"Error scraping {company}: {e}")
            continue
    
    return jobs

def fetch_job_details(url):
    """Fetch individual job page to get location and description."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return {}, ""
        
        content = resp.text
        
        # Extract location
        loc_match = re.search(
            r'(?:location|office)[^>]*>([^<]{3,60})</(?:span|div|p)',
            content, re.IGNORECASE
        )
        location = loc_match.group(1).strip() if loc_match else "Remote"
        
        # Extract description snippet for notes
        desc_match = re.search(
            r'<(?:div|section)[^>]*class="[^"]*(?:content|description|body)[^"]*"[^>]*>([\s\S]{100,500})',
            content, re.IGNORECASE
        )
        description = ""
        if desc_match:
            raw = desc_match.group(1)
            description = re.sub(r'<[^>]+>', ' ', raw)
            description = re.sub(r'\s+', ' ', description).strip()[:200]
        
        return {"location": location}, description
        
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return {}, ""

def build_entry(job, existing_cos):
    """Build a tracker JS entry object string from a job dict."""
    url = job.get("url", "")
    title = job.get("title", "Android Engineer")
    company = job.get("company", "Unknown")
    location = job.get("location", "Remote")
    source = job.get("source", "Greenhouse")
    note = job.get("note", "")
    
    region = detect_region(location)
    level = detect_level(title)
    visa = detect_visa(region, company)
    
    # Escape any quotes in strings
    def esc(s):
        return s.replace('"', "'").replace('\n', ' ').strip()
    
    return (
        f'  {{added:"{TODAY}",'
        f'co:"{esc(company)}",'
        f'role:"{esc(title)}",'
        f'loc:"{esc(location)}",'
        f'region:"{region}",'
        f'lv:"{level}",'
        f'visa:"{visa}",'
        f'note:"{esc(note)}",'
        f'src:"{source}",'
        f'url:"{url}",'
        f'isNew:true}}'
    )

def inject_new_jobs(content, new_entries):
    """Inject new job entries just before the closing ]; of the RAW array."""
    if not new_entries:
        return content, 0
    
    # Reset all isNew flags on existing entries
    content = re.sub(r',isNew:true}', ',isNew:false}', content)
    
    # Find injection point - just before ]; followed by LI_POSTS
    marker = '];\n\n// ─── LINKEDIN POSTS DATA ───'
    idx = content.find(marker)
    if idx == -1:
        print("Could not find injection marker!")
        return content, 0
    
    batch_comment = f"\n  // ─── AUTO-UPDATE · {TODAY} ───\n"
    entries_str = batch_comment + ",\n".join(new_entries) + ",\n"
    
    updated = content[:idx] + entries_str + content[idx:]
    return updated, len(new_entries)

def update_header_date(content):
    """Update the title date in the tracker header."""
    month_year = datetime.date.today().strftime("%b %Y")
    content = re.sub(
        r'Android Job Tracker · [A-Za-z]+ \d{4}',
        f'Android Job Tracker · {month_year}',
        content
    )
    return content

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Android Tracker Auto-Update · {TODAY} ===\n")
    
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    
    # Load tracker
    content = load_tracker()
    existing_urls = get_existing_urls(content)
    existing_cos = get_existing_cos(content)
    print(f"Existing entries: {len(existing_urls)} URLs tracked\n")
    
    all_jobs = []
    
    # ── Strategy 1: SerpAPI search (if key available) ──
    if serpapi_key:
        print("Running SerpAPI searches...")
        for query in SEARCH_QUERIES:
            results = search_google(query, serpapi_key)
            for r in results:
                url = r["url"]
                # Only ATS urls
                if not any(ats in url for ats in ["greenhouse.io", "lever.co", "ashbyhq.com"]):
                    continue
                title = r["title"].split(" at ")[0].strip() if " at " in r["title"] else r["title"]
                company = r["title"].split(" at ")[-1].strip() if " at " in r["title"] else "Unknown"
                # Remove ATS suffix from company
                for suffix in [" | Greenhouse", " - Lever", " - Ashby", " Jobs"]:
                    company = company.replace(suffix, "").strip()
                all_jobs.append({
                    "url": url, "title": title,
                    "company": company, "source": "Greenhouse",
                })
            time.sleep(1)
        print(f"SerpAPI found {len(all_jobs)} raw results\n")
    else:
        print("No SERPAPI_KEY — using direct ATS scraping...\n")
        all_jobs = scrape_ats_directly()
        print(f"Direct scraping found {len(all_jobs)} raw results\n")
    
    # ── Deduplicate ──
    new_jobs = []
    seen_urls = set(existing_urls)
    
    for job in all_jobs:
        url = job.get("url", "")
        if not url or url in seen_urls:
            continue
        # Skip if URL is just a base ATS URL (not a specific job)
        if re.search(r'greenhouse\.io/\w+$|lever\.co/\w+$', url):
            continue
        # Skip non-senior roles
        title = job.get("title", "")
        if not any(kw in title.lower() for kw in ["senior", "staff", "principal", "lead"]):
            continue
        # Skip iOS-only
        if "ios" in title.lower() and "android" not in title.lower():
            continue
        
        seen_urls.add(url)
        new_jobs.append(job)
    
    print(f"New unique jobs after dedup: {len(new_jobs)}\n")
    
    if not new_jobs:
        print("No new jobs found. Tracker unchanged.")
        return
    
    # ── Fetch details & build entries ──
    entries = []
    for job in new_jobs:
        print(f"  + {job['company']} — {job['title']}")
        details, description = fetch_job_details(job["url"])
        job.update(details)
        if description:
            # Extract key tech keywords for note
            techs = []
            for kw in ["Kotlin", "Compose", "KMP", "MVI", "MVVM", "Hilt", "Coroutines", "Flow"]:
                if kw.lower() in description.lower():
                    techs.append(kw)
            job["note"] = " · ".join(techs[:4]) if techs else "Auto-discovered"
        
        entry = build_entry(job, existing_cos)
        entries.append(entry)
        time.sleep(0.3)
    
    # ── Inject & save ──
    updated_content, count = inject_new_jobs(content, entries)
    updated_content = update_header_date(updated_content)
    save_tracker(updated_content)
    
    print(f"\n✅ Injected {count} new jobs into tracker")
    print(f"📄 Tracker saved to {TRACKER_FILE}")
    
    # Write summary for GitHub Actions step summary
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(f"## 🤖 Tracker Auto-Update · {TODAY}\n\n")
            f.write(f"**{count} new jobs added**\n\n")
            for job in new_jobs:
                f.write(f"- [{job['company']} — {job['title']}]({job['url']})\n")

if __name__ == "__main__":
    main()
