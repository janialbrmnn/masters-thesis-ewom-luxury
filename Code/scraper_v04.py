#!/usr/bin/env python3
"""
scraper_v04.py — Reddit data collection for Master's thesis
eWOM in Luxury Watch Communities: Heritage vs. Contemporary Brands

Brand list (v04) — 5+5 design:
  Heritage:     PatekPhilippe, rolex, ALangeSohne, VacheronConstantin, IWCSchaffhausen
  Contemporary: AudemarsPiguet, Hublot, RichardMille, FranckMuller, MBandF

Strategy (r/watches-only):
  - ALL posts collected exclusively from r/watches
  - Title keyword filter: post title must contain a study-brand keyword
  - Single-brand exclusion filter: posts mentioning >1 study brand in title excluded
  - Posts only (no comments)
  - Minimum 25 words per post (comparative eWOM threshold)
  - Target: 1,000 posts per brand (min 500)
  - Multi-pass: each brand's api_keywords list is iterated as separate PullPush
    queries; results are deduplicated by post ID across passes.

Rationale:
  Using r/watches as the single source for all brands ensures identical community
  context, posting norms, and audience composition across all ten brands. Mixing
  dedicated brand subreddits (which attract narrower brand-specific audiences)
  with r/watches would introduce a community-type confound. With ~24,200 posts/week,
  r/watches provides sufficient volume for all brands including niche ones.

API: PullPush (api.pullpush.io) — public Reddit archive, no credentials needed
Output: reddit_data_v04.csv + reddit_data_v04_stats.txt
"""

import requests
import time
import csv
import re
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
import html as html_module   # for unescaping &amp; → & in PullPush-stored titles

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = os.path.join(
    os.path.expanduser("~"),
    "Desktop", "Jani", "ESMT", "Masters Thesis", "03_Data"
)
OUTPUT_CSV   = os.path.join(OUTPUT_DIR, "reddit_data_v04.csv")
OUTPUT_STATS = os.path.join(OUTPUT_DIR, "reddit_data_v04_stats.txt")

MIN_WORDS        = 25    # minimum word count per post
# Note: LIWC-22 recommends 50 words for maximum reliability, but comparative
# eWOM studies using LIWC on social media regularly use lower thresholds
# (Tausczik & Pennebaker, 2010; Boyd & Pennebaker, 2015). For brand-group
# comparisons, consistency across groups matters more than absolute score
# reliability, making 25 words a defensible and common choice.
TARGET_PER_BRAND = 1000  # scrape target per brand
MIN_PER_BRAND    = 500   # minimum acceptable per brand
BATCH_SIZE       = 100   # PullPush max per request
REQUEST_DELAY    = 1.0   # seconds between API calls
MAX_RETRIES      = 3     # retries on transient errors

# Collection window: January 2020 – May 2026 (matches thesis Table 5)
AFTER_TS  = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())   # 1 Jan 2020
BEFORE_TS = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp())  # 31 May 2026

PULLPUSH_URL = "https://api.pullpush.io/reddit/search/submission/"
SOURCE_SUBREDDIT = "watches"  # single source for all brands

# ──────────────────────────────────────────────────────────────────────────────
# BRAND DEFINITIONS  (5 Heritage + 5 Contemporary)
# ──────────────────────────────────────────────────────────────────────────────

BRANDS = [
    # ── HERITAGE ──────────────────────────────────────────────────────────────
    {
        "brand_id":       "PatekPhilippe",
        "display_name":   "Patek Philippe",
        "brand_nature":   "Heritage",
        "api_keywords":   [
            "patek philippe",   # full name first
            "patek",
            "nautilus",         # iconic model — unambiguous on r/watches
            "aquanaut",
            "calatrava",
        ],
        "title_keywords": [
            "patek", "philippe", "patek philippe",
            "nautilus", "aquanaut", "calatrava", "5711", "5726",
            "grand complications",
        ],
    },
    {
        "brand_id":       "rolex",
        "display_name":   "Rolex",
        "brand_nature":   "Heritage",
        # Rolex already hits 1,000 with brand name alone
        "api_keywords":   ["rolex"],
        "title_keywords": ["rolex"],
    },
    {
        "brand_id":       "ALangeSohne",
        "display_name":   "A. Lange & Söhne",
        "brand_nature":   "Heritage",
        # "&" and "ö" may not survive PullPush indexing — ASCII variants used.
        "api_keywords":   [
            "a. lange sohne",
            "a. lange soehne",
            "a lange sohne",
            "lange sohne",
            "lange soehne",
            "a. lange",
            "lange",
            "zeitwerk",
            "datograph",
            "odysseus",
            "saxonia",
            "lange 1",
            "triple split",
            "1815",           # iconic collection, widely referenced by number
        ],
        "title_keywords": [
            "lange", "sohne", "soehne", "söhne",
            "a. lange", "a lange", "a.lange",
            "a. lange & söhne", "a. lange & sohne", "a. lange sohne",
            "lange & söhne", "lange & sohne", "lange & soehne",
            "lange sohne", "lange soehne", "lange 1",
            "zeitwerk", "datograph", "saxonia", "odysseus",
            "triple split", "1815", "tourbograph",
        ],
    },
    {
        "brand_id":       "VacheronConstantin",
        "display_name":   "Vacheron Constantin",
        "brand_nature":   "Heritage",
        "api_keywords":   [
            "vacheron constantin",  # full name
            "vacheron",
            "vc",
        ],
        "title_keywords": [
            "vacheron", "constantin", "vacheron constantin", "vc",
            "patrimony", "overseas",
        ],
    },
    {
        "brand_id":       "IWCSchaffhausen",
        "display_name":   "IWC Schaffhausen",
        "brand_nature":   "Heritage",
        "api_keywords":   [
            "iwc schaffhausen",     # full name
            "iwc",
            "portugieser",
            "big pilot",
        ],
        "title_keywords": [
            "iwc", "schaffhausen", "iwc schaffhausen",
            "portuguese", "portofino", "pilot's watch",
            "portugieser", "big pilot", "spitfire", "ingenieur",
        ],
    },
    # ── CONTEMPORARY ──────────────────────────────────────────────────────────
    {
        "brand_id":       "AudemarsPiguet",
        "display_name":   "Audemars Piguet",
        "brand_nature":   "Contemporary",
        "api_keywords":   [
            "audemars piguet",  # full name
            "audemars",
            "royal oak",
            " ap ",
        ],
        "title_keywords": [
            "audemars", "piguet", "audemars piguet", "royal oak", " ap ",
            "royal oak offshore", "code 11.59",
        ],
    },
    {
        "brand_id":       "Hublot",
        "display_name":   "Hublot",
        "brand_nature":   "Contemporary",
        "api_keywords":   [
            "hublot",
            "big bang",             # flagship — unambiguous on r/watches
            "classic fusion",
            "spirit of big bang",
            "big bang unico",
            "big bang integral",
            "mp-11",
        ],
        "title_keywords": [
            "hublot", "big bang", "classic fusion",
            "spirit of big bang", "big bang unico", "big bang integral",
            "mp-11", "mp-05", "techframe",
        ],
    },
    {
        "brand_id":       "RichardMille",
        "display_name":   "Richard Mille",
        "brand_nature":   "Contemporary",
        # Model numbers (RM 11, RM 27, etc.) are the most common references —
        # many posts never spell out "Richard Mille" in the title.
        # NOTE: " rm " with spaces misses titles where RM starts the sentence.
        "api_keywords":   [
            "richard mille",
            "richardmille",
            "rm 11",            # Felipe Massa Flyback — one of the most discussed
            "rm 27",            # Nadal Tourbillon
            "rm 35",            # Rafa Nadal
            "rm 50",            # split-seconds — iconic collab piece
            "rm 67",            # Extra Flat
            "rm 72",            # Lifestyle collection
            "rm watch",         # generic but catches casual refs
        ],
        "title_keywords": [
            "richard mille", "richardmille",
            "rm 11", "rm 27", "rm 35", "rm 50", "rm 67", "rm 72",
            "rm watch", " rm ",
        ],
    },
    {
        "brand_id":       "FranckMuller",
        "display_name":   "Franck Muller",
        "brand_nature":   "Contemporary",
        "api_keywords":   [
            "franck muller",
            "franckmuller",
            "franck",
            "curvex",
            "crazy hours",
            "vanguard",
            "conquistador",     # Conquistador collection
            "master banker",    # dual time zone model
            "cintrée",          # Cintrée Curvex — note: ée may not index
            "cintree",          # ASCII fallback
        ],
        "title_keywords": [
            "franck muller", "franckmuller", "franck",
            "curvex", "crazy hours", "vanguard",
            "conquistador", "master banker", "cintrée", "cintree",
        ],
    },
    {
        "brand_id":       "MBandF",
        "display_name":   "MB&F",
        "brand_nature":   "Contemporary",
        # "&" in "MB&F" gets URL-encoded correctly by fetch_batch (MB%26F).
        # PullPush also stores some titles with HTML entities ("MB&amp;F") —
        # html_module.unescape() in _scrape_single_pass resolves this so
        # client-side "mb&f" matching works on those posts too.
        # Diagnostic (test_mbf.py, 2026-05-25): confirmed working terms only:
        #   "MB&F" → results, "legacy machine" → results, "horological machine" → results
        #   "mad gallery" → results, "hm9" → results, "lm101" → results, "lm perpetual" → results
        #   "buesser" → 0 results (REMOVED), "hm10" → 0 results (REMOVED)
        "api_keywords":   [
            "MB&F",                 # primary — URL-encoded as MB%26F
            "mb&f",                 # lowercase variant
            "legacy machine",       # LM series (LM1, LM101, LM Perpetual…)
            "horological machine",  # HM series (HM9…)
            "maximilian buesser",   # founder full name
            "mad gallery",          # MB&F's retail concept
            "hm9",
            "lm101",
            "lm perpetual",
        ],
        "title_keywords": [
            "mb&f", "mb&amp;f", "[mb&f", "mb f", "mbf",
            "horological machine", "legacy machine",
            "maximilian", "buesser", "mad gallery",
            "lm1", "lm101", "lm perpetual", "hm9", "hm10",
        ],
    },
]

# All brand keywords combined — used to EXCLUDE multi-brand posts
ALL_BRAND_KEYWORDS: list = []
for b in BRANDS:
    ALL_BRAND_KEYWORDS.extend(b["title_keywords"])

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def word_count(text: str) -> int:
    return len(text.split())


def clean_text(title: str, selftext: str) -> str:
    combined = f"{title}\n\n{selftext}" if selftext else title
    combined = re.sub(r'\[deleted\]|\[removed\]', '', combined)
    combined = re.sub(r'\s+', ' ', combined).strip()
    return combined


def title_matches_brand(title: str, keywords: list) -> bool:
    t = title.lower()
    return any(kw.lower() in t for kw in keywords)


def title_has_other_brand(title: str, own_keywords: list) -> bool:
    t = title.lower()
    own_lower = {kw.lower() for kw in own_keywords}
    other_keywords = [kw for kw in ALL_BRAND_KEYWORDS if kw.lower() not in own_lower]
    return any(kw.lower() in t for kw in other_keywords)


def fetch_batch(subreddit: str, before: int, size: int = BATCH_SIZE, title_keyword: str = None) -> list:
    base_params = {
        "subreddit": subreddit,
        "size":      size,
        "before":    before,
        "after":     AFTER_TS,
        "sort":      "desc",
        "sort_type": "created_utc",
    }
    # Build URL manually so special chars in title_keyword (esp. '&' in "MB&F")
    # are percent-encoded as %26 rather than acting as query-param separators.
    # requests' params= dict encodes '&' correctly too, but some PullPush
    # deployments fail to decode %26 — manual construction avoids the ambiguity.
    query = urlencode(base_params)
    if title_keyword:
        query += "&title=" + quote(str(title_keyword), safe="")
    full_url = PULLPUSH_URL + "?" + query
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(full_url, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("data", [])
            elif resp.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"    Rate limited — waiting {wait}s …", flush=True)
                time.sleep(wait)
            else:
                print(f"    HTTP {resp.status_code} — retrying ({attempt+1}/{MAX_RETRIES})", flush=True)
                time.sleep(5)
        except requests.exceptions.RequestException as e:
            print(f"    Request error: {e} — retrying ({attempt+1}/{MAX_RETRIES})", flush=True)
            time.sleep(5)
    return []


# ──────────────────────────────────────────────────────────────────────────────
# SCRAPING: MULTI-PASS
# ──────────────────────────────────────────────────────────────────────────────

def _scrape_single_pass(
    brand_id: str,
    brand_nature: str,
    title_keywords: list,
    target: int,
    api_keyword: str,
    seen_ids: set,
) -> list:
    """
    Single PullPush pass using one api_keyword as a server-side title filter.
    Adds every processed post ID to seen_ids (accepted or rejected) to prevent
    duplicates across passes.
    """
    posts = []
    before = BEFORE_TS
    empty_batches = 0
    max_empty = 3

    print(f"    Pass [{api_keyword!r}] — need {target} more posts …", flush=True)

    while len(posts) < target:
        batch = fetch_batch(SOURCE_SUBREDDIT, before, BATCH_SIZE, title_keyword=api_keyword)
        time.sleep(REQUEST_DELAY)

        if not batch:
            empty_batches += 1
            if empty_batches >= max_empty:
                print(f"    Pass [{api_keyword!r}]: no more data after {len(posts)} posts.", flush=True)
                break
            continue
        empty_batches = 0

        oldest_ts = min(int(item.get("created_utc", 0)) for item in batch)
        oldest_date = datetime.fromtimestamp(oldest_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        print(
            f"      batch={len(batch)} | accepted={len(posts)} | oldest={oldest_date}",
            flush=True,
        )

        for item in batch:
            post_id  = item.get("id", "")
            # html_module.unescape converts &amp; → &, &amp;amp; → &amp;, etc.
            # PullPush stores some titles with HTML entities (e.g. "MB&amp;F"),
            # so the server-side search finds them but client-side substring
            # matching silently fails without this step.
            title    = html_module.unescape(item.get("title", "") or "")
            selftext = html_module.unescape(item.get("selftext", "") or "")
            author   = item.get("author", "[unknown]")
            created  = item.get("created_utc", 0)

            if post_id in seen_ids:
                continue

            # Register regardless of outcome (prevents re-processing in later passes)
            seen_ids.add(post_id)

            # Must mention this brand in title
            if not title_matches_brand(title, title_keywords):
                continue

            # Must NOT also mention another study brand in title
            if title_has_other_brand(title, title_keywords):
                continue

            text = clean_text(title, selftext)
            if word_count(text) < MIN_WORDS:
                continue

            posts.append({
                "item_id":      post_id,
                "source":       "r/watches",
                "subreddit":    SOURCE_SUBREDDIT,
                "brand_id":     brand_id,
                "brand_nature": brand_nature,
                "title":        title,
                "text":         text,
                "word_count":   word_count(text),
                "author":       author,
                "created_utc":  created,
                "created_date": datetime.fromtimestamp(
                                    int(created), tz=timezone.utc
                                ).strftime("%Y-%m-%d"),
            })

            if len(posts) % 100 == 0 and len(posts) > 0:
                print(f"      … {len(posts)} posts accepted in this pass", flush=True)

            if len(posts) >= target:
                break

        oldest = min(int(item.get("created_utc", before)) for item in batch)
        if oldest >= before:
            break
        before = oldest

    print(f"    Pass [{api_keyword!r}] done: +{len(posts)} posts", flush=True)
    return posts


def scrape_rwatch_for_brand(
    brand_id: str,
    brand_nature: str,
    title_keywords: list,
    api_keywords: list,
    target: int,
) -> list:
    """
    Multi-pass collection for one brand.
    Iterates over api_keywords; each is sent as a separate server-side title
    filter to PullPush. Results are deduplicated by post ID across all passes.
    Stops early if the target is reached before all passes complete.
    """
    all_posts = []
    seen_ids  = set()

    print(f"\n  Brand '{brand_id}' — target {target} | passes: {api_keywords}", flush=True)

    for kw in api_keywords:
        if len(all_posts) >= target:
            break
        remaining = target - len(all_posts)
        new_posts = _scrape_single_pass(
            brand_id, brand_nature, title_keywords, remaining, kw, seen_ids
        )
        all_posts.extend(new_posts)
        print(
            f"    After pass [{kw!r}]: total accepted = {len(all_posts)}/{target}",
            flush=True,
        )

    print(f"  → {len(all_posts)} posts accepted for '{brand_id}'", flush=True)
    return all_posts


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_posts   = []
    brand_stats = {}

    for brand in BRANDS:
        brand_id     = brand["brand_id"]
        display_name = brand["display_name"]
        brand_nature = brand["brand_nature"]
        keywords     = brand["title_keywords"]
        api_kws      = brand["api_keywords"]

        print(f"\n{'='*60}", flush=True)
        print(f"Brand: {display_name} ({brand_nature})", flush=True)
        print(f"Source: r/watches | api_keywords: {api_kws}", flush=True)
        print(f"{'='*60}", flush=True)

        brand_posts = scrape_rwatch_for_brand(
            brand_id       = brand_id,
            brand_nature   = brand_nature,
            title_keywords = keywords,
            api_keywords   = api_kws,
            target         = TARGET_PER_BRAND,
        )

        brand_total = len(brand_posts)
        brand_stats[brand_id] = {
            "display_name": display_name,
            "brand_nature": brand_nature,
            "n_total":      brand_total,
            "warning":      "BELOW MINIMUM" if brand_total < MIN_PER_BRAND else "",
        }

        all_posts.extend(brand_posts)
        print(f"  TOTAL for {display_name}: {brand_total}", flush=True)

    # ── Write CSV ─────────────────────────────────────────────────────────────
    fieldnames = [
        "item_id", "source", "subreddit", "brand_id", "brand_nature",
        "title", "text", "word_count", "author", "created_utc", "created_date",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_posts)

    print(f"\n{'='*60}", flush=True)
    print(f"CSV saved: {OUTPUT_CSV}", flush=True)
    print(f"Total posts: {len(all_posts)}", flush=True)

    # ── Write stats ───────────────────────────────────────────────────────────
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    stats_lines = [
        "reddit_data_v04 — Collection Report",
        f"Generated: {now}",
        "API:    api.pullpush.io (PullPush)",
        "Source: r/watches (all brands)",
        f"Window: 2020-01-01 – 2026-05-31",
        f"Min words per post: {MIN_WORDS} (comparative eWOM threshold; LIWC-22 default is 50)",
        f"Target per brand:   {TARGET_PER_BRAND}",
        f"Min per brand:      {MIN_PER_BRAND}",
        "",
        f"{'Brand':<24} {'Nature':<14} {'Total':>8}  Notes",
        "-" * 60,
    ]
    for bid, s in brand_stats.items():
        stats_lines.append(
            f"{s['display_name']:<24} {s['brand_nature']:<14} "
            f"{s['n_total']:>8}  {s['warning']}"
        )
    stats_lines += [
        "-" * 60,
        f"{'TOTAL':<24} {'':<14} "
        f"{len(all_posts):>8}",
        "",
        "Heritage brands (5):     Patek Philippe, Rolex, A. Lange & Söhne,",
        "                         Vacheron Constantin, IWC Schaffhausen",
        "Contemporary brands (5): Audemars Piguet, Hublot, Richard Mille,",
        "                         Franck Muller, MB&F",
        "",
        "Collection strategy: r/watches exclusively.",
        "  Multi-pass: each brand's api_keywords list sent as separate PullPush",
        "  title-filter queries; results deduplicated by post ID across passes.",
        "  Single-brand exclusion: posts mentioning >1 study brand excluded.",
        "  Date window: 2020-01-01 to 2026-05-31.",
    ]

    stats_text = "\n".join(stats_lines)
    with open(OUTPUT_STATS, "w", encoding="utf-8") as f:
        f.write(stats_text)

    print(stats_text, flush=True)
    print(f"\nStats saved: {OUTPUT_STATS}", flush=True)

    for bid, s in brand_stats.items():
        if s["warning"]:
            print(
                f"\n⚠  WARNING: {s['display_name']} only has {s['n_total']} posts "
                f"(minimum is {MIN_PER_BRAND}). Consider widening the date range.",
                flush=True,
            )


if __name__ == "__main__":
    main()
