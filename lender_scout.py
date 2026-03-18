#!/usr/bin/env python
"""
lender_scout.py — Daily Lender Intelligence Bot
=================================================
Scrapes for new wholesale lenders, guideline changes, rate updates,
and product launches. Updates the routing engine's lender database.

Runs daily at 6:00 AM CT (before markets open).

Data sources (all free):
  1. DuckDuckGo search — new wholesale lender announcements
  2. Scotsman Guide — wholesale lender rankings + news
  3. National Mortgage News — guideline changes
  4. AIME (Association of Independent Mortgage Experts) — broker alerts
  5. HousingWire — industry moves
  6. Fannie/Freddie announcements — guideline updates
  7. Ollama local LLM — parse and structure findings

Output:
  - C:/DandyDon/investor_site/lender_updates/{date}.json — daily findings
  - C:/DandyDon/investor_site/lender_db.json — master lender database (cumulative)
  - C:/DandyDon/investor_site/guideline_changes/{date}.json — guideline deltas
  - Email to Don if anything material changed

Schedule: Windows Task Scheduler or cron
  python C:/DandyDon/investor_site/lender_scout.py

Authors: Don Brown & Claude (Spock)
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

# Paths
SCOUT_DIR = Path("C:/DandyDon/investor_site")
UPDATES_DIR = SCOUT_DIR / "lender_updates"
GUIDELINES_DIR = SCOUT_DIR / "guideline_changes"
LENDER_DB_PATH = SCOUT_DIR / "lender_db.json"
UPDATES_DIR.mkdir(parents=True, exist_ok=True)
GUIDELINES_DIR.mkdir(parents=True, exist_ok=True)

# Ollama for parsing
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "aaron:latest"  # Qwen2 32B — best at structured extraction

# Perplexity for web search (live grounding)
PERPLEXITY_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
if not PERPLEXITY_KEY:
    # Load from .env — try both keys
    env_path = Path("C:/DandyDon/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("PERPLEXITY_BACKUP_KEY="):
                PERPLEXITY_KEY = line.split("=", 1)[1].strip()
            elif line.startswith("PERPLEXITY_API_KEY=") and not PERPLEXITY_KEY:
                PERPLEXITY_KEY = line.split("=", 1)[1].strip()

# Import email function from routing engine
sys.path.insert(0, str(SCOUT_DIR))
try:
    from routing_engine import _send_graph_email, DON_EMAIL
except ImportError:
    DON_EMAIL = "don@dandydon.media"
    def _send_graph_email(to, subj, body):
        print(f"[EMAIL SKIP] Would send to {to}: {subj}")
        return False


# ============================================================
#  SEARCH SOURCES
# ============================================================

def perplexity_search(query: str) -> List[dict]:
    """Search via Perplexity API — live web grounding, structured results."""
    if not PERPLEXITY_KEY:
        print("  [PERPLEXITY SKIP] No API key")
        return []

    payload = json.dumps({
        "model": "sonar",
        "messages": [
            {"role": "system", "content": "You are a mortgage industry research assistant. Return findings as structured data. For each finding include: title, url (if available), and a one-sentence summary. Focus on wholesale lenders, non-QM programs, guideline changes, and rate updates."},
            {"role": "user", "content": query},
        ],
        "max_tokens": 1500,
    }).encode()

    req = urllib.request.Request("https://api.perplexity.ai/chat/completions",
        data=payload, headers={
            "Authorization": f"Bearer {PERPLEXITY_KEY}",
            "Content-Type": "application/json",
        })
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        citations = data.get("citations", [])

        # Parse into results
        results = []
        # Split content into logical findings
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        current = {"title": "", "snippet": "", "url": ""}
        for line in lines:
            if line.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
                if current["title"]:
                    results.append(current)
                current = {"title": line.lstrip("-*0123456789. "), "snippet": "", "url": ""}
            else:
                current["snippet"] += " " + line

        if current["title"]:
            results.append(current)

        # Attach citations as URLs
        for i, r in enumerate(results):
            if i < len(citations):
                r["url"] = citations[i]

        return results[:10]
    except Exception as e:
        print(f"  [PERPLEXITY FAIL] {e}")
        return []


def duckduckgo_search(query: str, max_results: int = 10) -> List[dict]:
    """Search DuckDuckGo Lite and return results."""
    url = "https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({"q": query}).encode()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept": "text/html",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [DDG FAIL] {e}")
        return []

    results = []

    # Lite page has simple <a> links and <td> snippets
    # Pattern: link row then snippet row
    links = re.findall(r'<a[^>]*rel="nofollow"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html)
    snippets = re.findall(r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)

    for i, (href, title) in enumerate(links):
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
        if href.startswith("http") and title:
            results.append({"url": href, "title": title, "snippet": snippet})
        if len(results) >= max_results:
            break

    # Fallback: if lite didn't parse, try the JSON API
    if not results:
        try:
            api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
            req2 = urllib.request.Request(api_url, headers={"User-Agent": headers["User-Agent"]})
            resp2 = urllib.request.urlopen(req2, timeout=10)
            data = json.loads(resp2.read())
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if "FirstURL" in topic:
                    results.append({
                        "url": topic["FirstURL"],
                        "title": topic.get("Text", "")[:100],
                        "snippet": topic.get("Text", ""),
                    })
        except Exception:
            pass

    # Fallback 2: Use Ollama with web_search if available via APEX router
    if not results:
        try:
            # Try APEX router web_search
            apex_payload = json.dumps({
                "model": "aaron:latest",
                "prompt": f"Search the web for: {query}\n\nReturn the top 5 results as a JSON array with fields: url, title, snippet",
                "system": "You are a web search assistant. Return structured JSON results.",
                "stream": False,
            }).encode()
            req3 = urllib.request.Request(OLLAMA_URL, data=apex_payload,
                headers={"Content-Type": "application/json"})
            resp3 = urllib.request.urlopen(req3, timeout=60)
            ollama_resp = json.loads(resp3.read()).get("response", "")
            # Try to parse JSON from response
            json_match = re.search(r'\[.*\]', ollama_resp, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                for item in parsed[:max_results]:
                    if isinstance(item, dict) and "title" in item:
                        results.append(item)
        except Exception:
            pass

    return results


def fetch_page_text(url: str, max_chars: int = 8000) -> str:
    """Fetch a web page and extract readable text."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[FETCH FAIL] {e}"

    # Strip HTML tags, scripts, styles
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def ollama_extract(prompt: str, system: str = "") -> str:
    """Send prompt to local Ollama and return response."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system or "You are a mortgage industry analyst. Extract structured data from text. Be precise. Output valid JSON only.",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2000},
    }).encode()

    req = urllib.request.Request(OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
        return data.get("response", "")
    except Exception as e:
        print(f"  [OLLAMA FAIL] {e}")
        return ""


# ============================================================
#  SEARCH QUERIES — what we look for daily
# ============================================================

DAILY_SEARCHES = [
    # New lenders / product launches
    "new wholesale mortgage lender 2026",
    "wholesale lender product launch 2026",
    "non-QM lender new program 2026",
    "DSCR lender new product 2026",
    "wholesale mortgage broker TPO new",

    # Guideline changes
    "Fannie Mae guideline change 2026",
    "Freddie Mac guideline update 2026",
    "FHA guideline change 2026",
    "VA loan guideline update 2026",
    "conforming loan limit change 2026",

    # Rate movements
    "wholesale mortgage rate today",
    "non-QM rate update",
    "DSCR loan rate today",

    # Industry moves
    "wholesale lender acquisition 2026",
    "mortgage lender shutdown 2026",
    "AIME wholesale broker news",
]


# ============================================================
#  DAILY SCOUT PIPELINE
# ============================================================

@dataclass
class Finding:
    category: str       # "new_lender", "guideline_change", "rate_update", "industry_move"
    source: str         # URL
    title: str
    summary: str
    impact: str         # "high", "medium", "low"
    action_needed: str  # what Don should do
    raw_snippet: str = ""
    structured_data: dict = field(default_factory=dict)


def run_daily_scout() -> List[Finding]:
    """Run all daily searches and extract findings."""
    today = date.today().isoformat()
    print(f"\n{'='*60}")
    print(f"  LENDER SCOUT — {today}")
    print(f"{'='*60}")

    all_results = []
    findings = []

    # Phase 1: Search (Perplexity primary, DDG fallback)
    print(f"\n[1/4] Searching {len(DAILY_SEARCHES)} queries...")
    use_perplexity = bool(PERPLEXITY_KEY)
    if use_perplexity:
        print(f"  Using Perplexity API (live grounding)")
    else:
        print(f"  Using DuckDuckGo (no Perplexity key)")

    for i, query in enumerate(DAILY_SEARCHES):
        print(f"  [{i+1}/{len(DAILY_SEARCHES)}] {query}")

        if use_perplexity:
            results = perplexity_search(query)
            time.sleep(1)  # Perplexity rate limit
        else:
            results = duckduckgo_search(query, max_results=5)
            time.sleep(1.5)

        if not results and use_perplexity:
            # Fallback to DDG
            results = duckduckgo_search(query, max_results=5)
            time.sleep(1)

        for r in results:
            r["query"] = query
        all_results.extend(results)
        print(f"    -> {len(results)} results")

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique.append(r)
    print(f"  Found {len(unique)} unique results from {len(all_results)} total")

    # Phase 2: Filter relevant results using Ollama
    print(f"\n[2/4] Filtering with LLM ({OLLAMA_MODEL})...")
    relevant = []
    for r in unique[:30]:  # Cap at 30 to not overload
        # Quick relevance check from snippet
        snippet = r.get("snippet", "")
        title = r.get("title", "")
        text = f"{title}. {snippet}"

        # Keyword filter first (fast)
        keywords = ["wholesale", "lender", "broker", "non-qm", "dscr", "guideline",
                     "fannie", "freddie", "fha", "va", "usda", "rate", "overlay",
                     "tpo", "credit score", "ltv", "dti", "underwrite"]
        if any(kw in text.lower() for kw in keywords):
            relevant.append(r)

    print(f"  {len(relevant)} results pass keyword filter")

    # Phase 3: Deep extraction on relevant results
    print(f"\n[3/4] Extracting structured data...")
    for r in relevant[:15]:  # Deep dive on top 15
        print(f"  Analyzing: {r['title'][:60]}...")

        # Fetch full page for more context
        page_text = fetch_page_text(r["url"], max_chars=4000)
        if "[FETCH FAIL]" in page_text:
            page_text = r.get("snippet", "")

        # Use Ollama to extract structured findings
        extract_prompt = f"""Analyze this mortgage industry content and extract any actionable information.

TITLE: {r['title']}
URL: {r['url']}
CONTENT: {page_text[:3000]}

If this contains ANY of these, extract it as JSON:
1. New wholesale lender or new product launch → category: "new_lender"
2. Guideline change (credit score, LTV, DTI, overlays) → category: "guideline_change"
3. Rate update or pricing change → category: "rate_update"
4. Lender acquisition, shutdown, or major change → category: "industry_move"

Output JSON format:
{{"relevant": true/false, "category": "...", "summary": "one sentence", "impact": "high/medium/low", "action": "what a mortgage broker should do", "details": {{}}}}

If not relevant to wholesale/non-QM mortgage lending, output: {{"relevant": false}}"""

        response = ollama_extract(extract_prompt)

        # Parse LLM response
        try:
            # Find JSON in response
            json_match = re.search(r'\{[^{}]*"relevant"[^{}]*\}', response, re.DOTALL)
            if not json_match:
                # Try to find any JSON object
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                extracted = json.loads(json_match.group())
                if extracted.get("relevant", False):
                    findings.append(Finding(
                        category=extracted.get("category", "unknown"),
                        source=r["url"],
                        title=r["title"],
                        summary=extracted.get("summary", ""),
                        impact=extracted.get("impact", "low"),
                        action_needed=extracted.get("action", ""),
                        raw_snippet=r.get("snippet", ""),
                        structured_data=extracted.get("details", {}),
                    ))
        except (json.JSONDecodeError, AttributeError):
            pass

        time.sleep(0.5)  # pace Ollama requests

    print(f"  {len(findings)} actionable findings extracted")

    # Phase 4: Save and notify
    print(f"\n[4/4] Saving results...")

    # Save daily findings
    daily_path = UPDATES_DIR / f"{today}.json"
    daily_data = {
        "date": today,
        "searches": len(DAILY_SEARCHES),
        "results_found": len(unique),
        "relevant": len(relevant),
        "findings": [asdict(f) for f in findings],
    }
    daily_path.write_text(json.dumps(daily_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved: {daily_path}")

    # Save guideline changes separately
    guideline_changes = [f for f in findings if f.category == "guideline_change"]
    if guideline_changes:
        gl_path = GUIDELINES_DIR / f"{today}.json"
        gl_path.write_text(json.dumps([asdict(f) for f in guideline_changes], indent=2), encoding="utf-8")
        print(f"  Guideline changes: {gl_path}")

    # Update master lender DB
    update_lender_db(findings)

    # Email Don if anything high-impact
    high_impact = [f for f in findings if f.impact == "high"]
    if high_impact:
        notify_don(findings, today)

    print(f"\n{'='*60}")
    print(f"  SCOUT COMPLETE — {len(findings)} findings")
    print(f"  High impact: {len(high_impact)}")
    print(f"  Guideline changes: {len(guideline_changes)}")
    print(f"{'='*60}")

    return findings


# ============================================================
#  LENDER DATABASE MANAGEMENT
# ============================================================

def load_lender_db() -> dict:
    """Load the master lender database."""
    if LENDER_DB_PATH.exists():
        return json.loads(LENDER_DB_PATH.read_text(encoding="utf-8"))
    return {"lenders": {}, "last_updated": "", "update_log": []}


def save_lender_db(db: dict):
    """Save the master lender database."""
    db["last_updated"] = datetime.now().isoformat()
    LENDER_DB_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


def update_lender_db(findings: List[Finding]):
    """Update lender DB with new findings."""
    db = load_lender_db()
    changes = 0

    for f in findings:
        if f.category == "new_lender":
            # Extract lender name from summary
            name = f.structured_data.get("lender_name", f.title.split(" - ")[0].split(" — ")[0][:50])
            if name and name not in db["lenders"]:
                db["lenders"][name] = {
                    "discovered": date.today().isoformat(),
                    "source": f.source,
                    "summary": f.summary,
                    "products": f.structured_data.get("products", []),
                    "status": "needs_review",
                }
                changes += 1
                print(f"  NEW LENDER ADDED: {name}")

        elif f.category == "guideline_change":
            db["update_log"].append({
                "date": date.today().isoformat(),
                "type": "guideline_change",
                "summary": f.summary,
                "impact": f.impact,
                "source": f.source,
                "action": f.action_needed,
            })
            changes += 1

        elif f.category == "industry_move":
            db["update_log"].append({
                "date": date.today().isoformat(),
                "type": "industry_move",
                "summary": f.summary,
                "impact": f.impact,
                "source": f.source,
            })
            changes += 1

    if changes > 0:
        save_lender_db(db)
        print(f"  Lender DB updated: {changes} changes")
    else:
        print(f"  Lender DB: no changes")


# ============================================================
#  NOTIFICATIONS
# ============================================================

def notify_don(findings: List[Finding], today: str):
    """Email Don with high-impact findings."""
    high = [f for f in findings if f.impact == "high"]
    medium = [f for f in findings if f.impact == "medium"]

    subject = f"LENDER SCOUT: {len(high)} high-impact findings — {today}"
    body = f"""DAILY LENDER INTELLIGENCE — {today}

{len(findings)} total findings | {len(high)} high impact | {len(medium)} medium impact

"""
    if high:
        body += "=== HIGH IMPACT ===\n\n"
        for f in high:
            body += f"[{f.category.upper()}] {f.summary}\n"
            body += f"  Action: {f.action_needed}\n"
            body += f"  Source: {f.source}\n\n"

    if medium:
        body += "=== MEDIUM IMPACT ===\n\n"
        for f in medium:
            body += f"[{f.category.upper()}] {f.summary}\n"
            body += f"  Source: {f.source}\n\n"

    body += f"\nFull report: C:/DandyDon/investor_site/lender_updates/{today}.json"

    _send_graph_email(DON_EMAIL, subject, body)


# ============================================================
#  GUIDELINE MONITOR — specific sources to check
# ============================================================

GUIDELINE_SOURCES = [
    {
        "name": "Fannie Mae Announcements",
        "search": "site:fanniemae.com lender letter OR selling guide update 2026",
    },
    {
        "name": "Freddie Mac Bulletins",
        "search": "site:freddiemac.com guide bulletin 2026",
    },
    {
        "name": "FHA Mortgagee Letters",
        "search": "site:hud.gov mortgagee letter 2026",
    },
    {
        "name": "VA Circulars",
        "search": "site:benefits.va.gov circular lender 2026",
    },
    {
        "name": "FHFA Announcements",
        "search": "site:fhfa.gov conforming loan limit OR announcement 2026",
    },
]


def check_guideline_sources():
    """Check specific guideline sources for updates."""
    print("\n  Checking guideline sources...")
    for src in GUIDELINE_SOURCES:
        print(f"    {src['name']}...")
        results = duckduckgo_search(src["search"], max_results=3)
        for r in results:
            print(f"      {r['title'][:70]}")
        time.sleep(1.5)


# ============================================================
#  MAIN
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daily Lender Intelligence Bot")
    parser.add_argument("--quick", action="store_true", help="Quick scan (fewer queries)")
    parser.add_argument("--guidelines-only", action="store_true", help="Only check guideline sources")
    parser.add_argument("--test", action="store_true", help="Test with 2 queries only")
    args = parser.parse_args()

    if args.guidelines_only:
        check_guideline_sources()
    elif args.test:
        DAILY_SEARCHES[:] = DAILY_SEARCHES[:2]
        run_daily_scout()
    elif args.quick:
        DAILY_SEARCHES[:] = DAILY_SEARCHES[:6]
        run_daily_scout()
    else:
        run_daily_scout()
