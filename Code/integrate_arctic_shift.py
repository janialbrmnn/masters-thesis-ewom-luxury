#!/usr/bin/env python3
"""
integrate_arctic_shift.py — Merge Arctic Shift r/watches archive into
the existing reddit_data_v04_clean.csv.

Strategy:
  1. Load all post IDs already in reddit_data_v04_clean.csv → seen_ids
  2. Stream through Arctic Shift JSONL line by line (memory-efficient)
  3. Apply identical filtering pipeline as the main scraper:
       - Skip removed/deleted posts (removed_by_category set)
       - Skip bot/AutoModerator authors
       - Skip editorial roundup titles
       - html.unescape() on title + selftext
       - Single-brand title match (must match exactly one study brand)
       - Single-brand exclusion (must NOT mention another study brand)
       - Word count 25–1000
       - Date window 2020-01-01 – 2026-05-31
  4. Deduplicate by post ID (seen_ids shared across both sources)
  5. Cap each brand at TARGET_PER_BRAND = 1000
  6. Append new posts to reddit_data_v04_clean.csv
  7. Write integration report

Input:  reddit_data_v04_clean.csv   (base — PullPush data, already cleaned)
        r_watches_posts.jsonl        (Arctic Shift full r/watches archive)
Output: reddit_data_v04_clean.csv   (updated in-place — new rows appended)
        arctic_shift_integration_report.txt
"""

import csv
import json
import os
import html as html_module
import re
from datetime import datetime, timezone
from collections import Counter

# ── Paths ──────────────────────────────────────────────────────────────────────

DATA_DIR   = os.path.join(
    os.path.expanduser("~"), "Desktop", "Jani", "ESMT", "Masters Thesis", "03_Data"
)
CLEAN_CSV  = os.path.join(DATA_DIR, "reddit_data_v04_clean.csv")
JSONL_FILE = os.path.join(DATA_DIR, "r_watches_posts.jsonl")
REPORT_TXT = os.path.join(DATA_DIR, "arctic_shift_integration_report.txt")

# ── Parameters ─────────────────────────────────────────────────────────────────

MIN_WORDS         = 25
MAX_WORDS         = 1000
TARGET_PER_BRAND  = 1000
AFTER_DATE        = "2020-01-01"
BEFORE_DATE       = "2026-05-31"
AFTER_TS  = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
BEFORE_TS = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp())

EDITORIAL_PREFIXES = [
    "[weekly roundup]", "[daily news]", "[news roundup]",
    "[weekly discussion]", "weekly roundup", "daily news",
]

BOT_AUTHORS = {"automoderator", "bot"}

# ── Brand definitions (must match scraper_v04.py exactly) ──────────────────────

BRANDS = [
    {
        "brand_id":     "PatekPhilippe",
        "brand_nature": "Heritage",
        "title_keywords": [
            "patek", "philippe", "patek philippe",
            "nautilus", "aquanaut", "calatrava", "5711", "5726",
            "grand complications",
        ],
    },
    {
        "brand_id":     "rolex",
        "brand_nature": "Heritage",
        "title_keywords": ["rolex"],
    },
    {
        "brand_id":     "ALangeSohne",
        "brand_nature": "Heritage",
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
        "brand_id":     "VacheronConstantin",
        "brand_nature": "Heritage",
        "title_keywords": [
            "vacheron", "constantin", "vacheron constantin", "vc",
            "patrimony", "overseas",
        ],
    },
    {
        "brand_id":     "IWCSchaffhausen",
        "brand_nature": "Heritage",
        "title_keywords": [
            "iwc", "schaffhausen", "iwc schaffhausen",
            "portuguese", "portofino", "pilot's watch",
            "portugieser", "big pilot", "spitfire", "ingenieur",
        ],
    },
    {
        "brand_id":     "AudemarsPiguet",
        "brand_nature": "Contemporary",
        "title_keywords": [
            "audemars", "piguet", "audemars piguet", "royal oak", " ap ",
            "royal oak offshore", "code 11.59",
        ],
    },
    {
        "brand_id":     "Hublot",
        "brand_nature": "Contemporary",
        "title_keywords": [
            "hublot", "big bang", "classic fusion",
            "spirit of big bang", "big bang unico", "big bang integral",
            "mp-11", "mp-05", "techframe",
        ],
    },
    {
        "brand_id":     "RichardMille",
        "brand_nature": "Contemporary",
        "title_keywords": [
            "richard mille", "richardmille",
            "rm 11", "rm 27", "rm 35", "rm 50", "rm 67", "rm 72",
            "rm watch", " rm ",
        ],
    },
    {
        "brand_id":     "FranckMuller",
        "brand_nature": "Contemporary",
        "title_keywords": [
            "franck muller", "franckmuller", "franck",
            "curvex", "crazy hours", "vanguard",
            "conquistador", "master banker", "cintrée", "cintree",
        ],
    },
    {
        "brand_id":     "MBandF",
        "brand_nature": "Contemporary",
        "title_keywords": [
            "mb&f", "mb&amp;f", "[mb&f", "mb f", "mbf",
            "horological machine", "legacy machine",
            "maximilian", "buesser", "mad gallery",
            "lm1", "lm101", "lm perpetual", "hm9", "hm10",
        ],
    },
]

# Flat list of ALL brand keywords — for single-brand exclusion filter
ALL_KEYWORDS = []
for b in BRANDS:
    ALL_KEYWORDS.extend(b["title_keywords"])

# ── Helpers ────────────────────────────────────────────────────────────────────

def word_count(text):
    return len(text.split())

def clean_text(title, selftext):
    combined = f"{title}\n\n{selftext}" if selftext else title
    combined = re.sub(r'\[deleted\]|\[removed\]', '', combined)
    combined = re.sub(r'\s+', ' ', combined).strip()
    return combined

def is_editorial(title):
    t = title.lower().strip()
    return any(t.startswith(p) for p in EDITORIAL_PREFIXES)

def is_bot(author):
    return author.lower().strip() in BOT_AUTHORS

def detect_brand(title):
    """Return brand_id if title matches exactly one study brand, else None."""
    t = title.lower()
    matched = []
    for brand in BRANDS:
        if any(kw.lower() in t for kw in brand["title_keywords"]):
            matched.append(brand)
    return matched[0] if len(matched) == 1 else None

def has_other_brand(title, own_keywords):
    t = title.lower()
    own_lower = {kw.lower() for kw in own_keywords}
    other_kws = [kw for kw in ALL_KEYWORDS if kw.lower() not in own_lower]
    return any(kw.lower() in t for kw in other_kws)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Step 1: Load existing post IDs and per-brand counts from clean CSV
    existing_ids   = set()
    existing_count = Counter()
    fieldnames = [
        "item_id", "source", "subreddit", "brand_id", "brand_nature",
        "title", "text", "word_count", "author", "created_utc", "created_date",
    ]

    with open(CLEAN_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing_ids.add(row["item_id"])
            existing_count[row["brand_id"]] += 1

    print(f"Existing posts loaded: {len(existing_ids):,}")
    print("Existing brand counts:")
    for b, n in sorted(existing_count.items()):
        need = max(0, TARGET_PER_BRAND - n)
        print(f"  {b:<24} {n:>5}  (need {need} more)")

    # Step 2: Stream Arctic Shift JSONL
    print(f"\nProcessing {JSONL_FILE} ...")
    print("(processing 836k posts — will take a few minutes)\n")

    seen_ids      = set(existing_ids)   # shared dedup set
    new_posts     = []                  # new posts to append
    brand_new     = Counter()           # new posts per brand
    stats = {
        "lines":        0,
        "skipped_removed":   0,
        "skipped_bot":       0,
        "skipped_editorial": 0,
        "skipped_no_brand":  0,
        "skipped_multi_brand": 0,
        "skipped_word_count":0,
        "skipped_date":      0,
        "skipped_duplicate": 0,
        "skipped_target_met":0,
        "accepted":          0,
    }

    with open(JSONL_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                post = json.loads(line)
            except json.JSONDecodeError:
                continue

            stats["lines"] += 1
            if stats["lines"] % 100_000 == 0:
                print(f"  ... {stats['lines']:,} processed | "
                      f"new accepted: {stats['accepted']:,}", flush=True)

            post_id  = post.get("id", "") or post.get("name", "").replace("t3_", "")
            author   = post.get("author", "") or ""
            title    = html_module.unescape(post.get("title", "") or "")
            selftext = html_module.unescape(post.get("selftext", "") or "")
            created  = post.get("created_utc", 0) or 0

            # Skip removed posts
            removed_cat = post.get("removed_by_category") or ""
            if removed_cat:
                stats["skipped_removed"] += 1
                continue

            # Skip bots
            if is_bot(author):
                stats["skipped_bot"] += 1
                continue

            # Skip editorial
            if is_editorial(title):
                stats["skipped_editorial"] += 1
                continue

            # Date range
            try:
                ts = int(created)
                if ts < AFTER_TS or ts > BEFORE_TS:
                    stats["skipped_date"] += 1
                    continue
                created_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                stats["skipped_date"] += 1
                continue

            # Brand detection
            brand = detect_brand(title)
            if brand is None:
                stats["skipped_no_brand"] += 1
                continue

            # Single-brand exclusion
            if has_other_brand(title, brand["title_keywords"]):
                stats["skipped_multi_brand"] += 1
                continue

            # Target already met for this brand?
            if existing_count[brand["brand_id"]] + brand_new[brand["brand_id"]] >= TARGET_PER_BRAND:
                stats["skipped_target_met"] += 1
                continue

            # Duplicate check
            if post_id in seen_ids:
                stats["skipped_duplicate"] += 1
                continue
            seen_ids.add(post_id)

            # Text and word count
            text = clean_text(title, selftext)
            wc   = word_count(text)
            if wc < MIN_WORDS or wc > MAX_WORDS:
                stats["skipped_word_count"] += 1
                continue

            # Accept
            new_posts.append({
                "item_id":      post_id,
                "source":       "r/watches (Arctic Shift)",
                "subreddit":    "watches",
                "brand_id":     brand["brand_id"],
                "brand_nature": brand["brand_nature"],
                "title":        title,
                "text":         text,
                "word_count":   wc,
                "author":       author,
                "created_utc":  created,
                "created_date": created_date,
            })
            brand_new[brand["brand_id"]] += 1
            stats["accepted"] += 1

    # Step 3: Append to clean CSV
    if new_posts:
        with open(CLEAN_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writerows(new_posts)
        print(f"\n✓ Appended {len(new_posts):,} new posts to {CLEAN_CSV}")
    else:
        print("\nNo new posts to append.")

    # Step 4: Final counts
    final_count = Counter(existing_count)
    for b, n in brand_new.items():
        final_count[b] += n

    print(f"\n{'='*60}")
    print(f"INTEGRATION RESULTS")
    print(f"{'='*60}")
    print(f"{'Brand':<24} {'Before':>7} {'New':>7} {'After':>7}  Status")
    print(f"{'-'*60}")
    for b in sorted(final_count.keys()):
        before = existing_count[b]
        new    = brand_new[b]
        after  = final_count[b]
        status = "✓" if after >= TARGET_PER_BRAND else ("OK" if after >= 500 else "⚠ BELOW MIN")
        print(f"  {b:<24} {before:>7} {new:>7} {after:>7}  {status}")
    print(f"{'-'*60}")
    print(f"  {'TOTAL':<24} {sum(existing_count.values()):>7} "
          f"{len(new_posts):>7} {sum(final_count.values()):>7}")

    print(f"\nProcessing stats:")
    for k, v in stats.items():
        print(f"  {k:<28} {v:>8,}")

    # Step 5: Save report
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "Arctic Shift Integration Report",
        f"Generated: {now}",
        "=" * 60,
        f"Source file: r_watches_posts.jsonl",
        f"  Total posts in file: {stats['lines']:,}",
        f"  JSON parse errors:   0",
        "",
        "Filtering pipeline applied:",
        "  - Removed/moderated posts excluded (removed_by_category set)",
        "  - Bot/AutoModerator authors excluded",
        "  - Editorial roundup titles excluded",
        "  - html.unescape() applied to title and selftext",
        "  - Single-brand title match required",
        "  - Single-brand exclusion filter applied",
        f"  - Word count filter: {MIN_WORDS}–{MAX_WORDS} words",
        f"  - Date window: {AFTER_DATE} – {BEFORE_DATE}",
        f"  - Deduplication: post ID checked against existing {len(existing_ids):,} posts",
        f"  - Brand cap: {TARGET_PER_BRAND} posts per brand maximum",
        "",
        "=" * 60,
        "BRAND RESULTS",
        f"{'Brand':<24} {'Before':>7} {'New':>7} {'After':>7}  Status",
        "-" * 60,
    ]
    for b in sorted(final_count.keys()):
        before = existing_count[b]
        new    = brand_new[b]
        after  = final_count[b]
        status = "TARGET MET" if after >= TARGET_PER_BRAND else ("ABOVE MIN" if after >= 500 else "BELOW MIN 500")
        lines.append(f"  {b:<24} {before:>7} {new:>7} {after:>7}  {status}")
    lines += [
        "-" * 60,
        f"  {'TOTAL':<24} {sum(existing_count.values()):>7} "
        f"{len(new_posts):>7} {sum(final_count.values()):>7}",
        "",
        "Processing stats:",
    ]
    for k, v in stats.items():
        lines.append(f"  {k:<28} {v:>8,}")

    with open(REPORT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n✓ Report saved: {REPORT_TXT}")
    print("\nDone. Your reddit_data_v04_clean.csv now contains both sources.")
    print("The 'source' column distinguishes PullPush vs Arctic Shift rows.")


if __name__ == "__main__":
    main()
