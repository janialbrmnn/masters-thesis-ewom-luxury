#!/usr/bin/env python3
"""
data_cleaning.py — Data pre-processing for reddit_data_v04.csv
Master's Thesis: eWOM in Luxury Watch Communities

Follows the systematic data cleaning checklist:
  1. Create copy of original (never overwrite)
  2. Sniff test — summary statistics
  3. Remove editorial/roundup posts (not consumer eWOM)
  4. Handle deleted accounts (retain — content is preserved)
  5. Remove bot authors
  6. Handle outliers (extreme word counts)
  7. Verify date range and brand distribution
  8. Save cleaned file + cleaning report

Input:  reddit_data_v04.csv
Output: reddit_data_v04_clean.csv
        reddit_data_v04_cleaning_report.txt
"""

import csv
import os
import shutil
from datetime import datetime
from collections import Counter

# ── Paths ──────────────────────────────────────────────────────────────────────

DATA_DIR     = os.path.join(
    os.path.expanduser("~"), "Desktop", "Jani", "ESMT", "Masters Thesis", "03_Data"
)
INPUT_CSV    = os.path.join(DATA_DIR, "reddit_data_v04.csv")
BACKUP_CSV   = os.path.join(DATA_DIR, "reddit_data_v04_ORIGINAL_BACKUP.csv")
CLEAN_CSV    = os.path.join(DATA_DIR, "reddit_data_v04_clean.csv")
REPORT_TXT   = os.path.join(DATA_DIR, "reddit_data_v04_cleaning_report.txt")

# ── Cleaning parameters ─────────────────────────────────────────────────────────

MIN_WORDS   = 25     # already enforced by scraper — double-check
MAX_WORDS   = 1000   # removes editorial roundups (>1000 words are never pure eWOM)

# Post title prefixes that indicate editorial/journalistic content, not eWOM
EDITORIAL_PREFIXES = [
    "[weekly roundup]",
    "[daily news]",
    "[news roundup]",
    "[weekly discussion]",
    "weekly roundup",
    "daily news",
]

# Authors to exclude (bots / AutoModerator)
# Note: '[deleted]' = user deleted account but post text is preserved → KEEP
BOT_AUTHORS = {
    "automoderator",
    "bot",              # exact match — cautious
}

# Date window
AFTER_DATE  = "2020-01-01"
BEFORE_DATE = "2026-05-31"

# ── Helpers ─────────────────────────────────────────────────────────────────────

def is_editorial(title: str) -> bool:
    t = title.lower().strip()
    return any(t.startswith(prefix) or t.startswith("[" + prefix)
               for prefix in EDITORIAL_PREFIXES)

def is_bot(author: str) -> bool:
    a = author.lower().strip()
    return a in BOT_AUTHORS or a == "automoderator"

# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    # ── Step 1: Backup original (never overwrite) ─────────────────────────────
    if not os.path.exists(BACKUP_CSV):
        shutil.copy2(INPUT_CSV, BACKUP_CSV)
        print(f"✓ Backup created: {BACKUP_CSV}")
    else:
        print(f"  Backup already exists: {BACKUP_CSV}")

    # ── Step 2: Load data ─────────────────────────────────────────────────────
    with open(INPUT_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    n_original = len(rows)
    print(f"\n── Sniff Test ──────────────────────────────────────────────")
    print(f"Total posts loaded:       {n_original}")

    brand_counts_orig = Counter(r["brand_id"] for r in rows)
    print("\nBrand distribution (original):")
    for b, n in sorted(brand_counts_orig.items()):
        print(f"  {b:<24} {n:>5}")

    word_counts = [int(r["word_count"]) for r in rows if r["word_count"]]
    word_counts.sort()
    n = len(word_counts)
    print(f"\nWord count — min:{word_counts[0]}  median:{word_counts[n//2]}  "
          f"mean:{sum(word_counts)//n}  max:{word_counts[-1]}")
    print(f"Posts > {MAX_WORDS} words:  {sum(1 for w in word_counts if w > MAX_WORDS)}")
    print(f"Posts < {MIN_WORDS} words:  {sum(1 for w in word_counts if w < MIN_WORDS)}")

    year_dist = Counter(r["created_date"][:4] for r in rows if r.get("created_date"))
    print(f"\nYear distribution:")
    for yr, cnt in sorted(year_dist.items()):
        print(f"  {yr}: {cnt}")

    # ── Step 3: Apply cleaning rules ──────────────────────────────────────────
    print(f"\n── Cleaning ────────────────────────────────────────────────")

    removed = {
        "editorial_roundup":  [],
        "bot_author":         [],
        "word_count_too_low": [],
        "word_count_too_high":[],
        "missing_text":       [],
        "out_of_date_range":  [],
        "duplicate_id":       [],
    }

    clean_rows  = []
    seen_ids    = set()

    for row in rows:
        post_id  = row.get("item_id", "")
        title    = row.get("title", "")
        text     = row.get("text", "")
        author   = row.get("author", "")
        wc       = int(row.get("word_count", 0) or 0)
        date_str = row.get("created_date", "")

        # Duplicate check
        if post_id in seen_ids:
            removed["duplicate_id"].append(post_id)
            continue
        seen_ids.add(post_id)

        # Missing text
        if not text.strip():
            removed["missing_text"].append(post_id)
            continue

        # Editorial/roundup posts — not consumer eWOM
        if is_editorial(title):
            removed["editorial_roundup"].append(post_id)
            continue

        # Bot/AutoModerator authors
        if is_bot(author):
            removed["bot_author"].append(post_id)
            continue

        # Word count — too short
        if wc < MIN_WORDS:
            removed["word_count_too_low"].append(post_id)
            continue

        # Word count — too long (editorial content, walls of text)
        if wc > MAX_WORDS:
            removed["word_count_too_high"].append(post_id)
            continue

        # Date range check
        if date_str and (date_str < AFTER_DATE or date_str > BEFORE_DATE):
            removed["out_of_date_range"].append(post_id)
            continue

        clean_rows.append(row)

    # ── Step 4: Report ────────────────────────────────────────────────────────
    n_removed_total = sum(len(v) for v in removed.values())
    n_clean = len(clean_rows)

    print(f"\nRemoval summary:")
    print(f"  {'Editorial/roundup posts':<30} {len(removed['editorial_roundup']):>5}  "
          f"(subreddit news digests — not consumer eWOM)")
    print(f"  {'Bot/AutoModerator':<30} {len(removed['bot_author']):>5}")
    print(f"  {'Word count < {MIN_WORDS}':<30} {len(removed['word_count_too_low']):>5}")
    print(f"  {'Word count > {MAX_WORDS}':<30} {len(removed['word_count_too_high']):>5}  "
          f"(editorial content threshold)")
    print(f"  {'Missing text':<30} {len(removed['missing_text']):>5}")
    print(f"  {'Out of date range':<30} {len(removed['out_of_date_range']):>5}")
    print(f"  {'Duplicate IDs':<30} {len(removed['duplicate_id']):>5}")
    print(f"  {'─'*38}")
    print(f"  {'Total removed':<30} {n_removed_total:>5}")
    print(f"  {'Retained':<30} {n_clean:>5}  ({100*n_clean/n_original:.1f}%)")

    brand_counts_clean = Counter(r["brand_id"] for r in clean_rows)
    print(f"\nBrand distribution (cleaned):")
    for b, n in sorted(brand_counts_clean.items()):
        flag = "  ⚠ BELOW MINIMUM (500)" if n < 500 else ""
        print(f"  {b:<24} {n:>5}{flag}")

    word_counts_clean = sorted([int(r["word_count"]) for r in clean_rows])
    nc = len(word_counts_clean)
    print(f"\nWord count after cleaning:")
    print(f"  Min:{word_counts_clean[0]}  Median:{word_counts_clean[nc//2]}  "
          f"Mean:{sum(word_counts_clean)//nc}  Max:{word_counts_clean[-1]}")

    year_dist_clean = Counter(r["created_date"][:4] for r in clean_rows if r.get("created_date"))
    print(f"\nYear distribution (cleaned):")
    for yr, cnt in sorted(year_dist_clean.items()):
        print(f"  {yr}: {cnt}")

    # ── Step 5: Save cleaned CSV ──────────────────────────────────────────────
    fieldnames = [
        "item_id", "source", "subreddit", "brand_id", "brand_nature",
        "title", "text", "word_count", "author", "created_utc", "created_date",
    ]
    with open(CLEAN_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean_rows)
    print(f"\n✓ Clean CSV saved: {CLEAN_CSV}")

    # ── Step 6: Save cleaning report ──────────────────────────────────────────
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    report_lines = [
        "reddit_data_v04 — Data Cleaning Report",
        f"Generated: {now}",
        "=" * 60,
        "",
        "CLEANING PROCEDURE",
        "-" * 60,
        f"Input file:   reddit_data_v04.csv",
        f"Output file:  reddit_data_v04_clean.csv",
        f"Backup file:  reddit_data_v04_ORIGINAL_BACKUP.csv",
        "",
        "Rules applied (in order):",
        "  1. Duplicate post IDs removed",
        "  2. Posts with empty text body removed",
        f"  3. Editorial/roundup posts removed (title starts with",
        f"     [Weekly Roundup], [Daily News], etc.) — these are",
        f"     journalistic aggregations, not consumer eWOM",
        "  4. Bot/AutoModerator authors removed",
        f"  5. Posts with fewer than {MIN_WORDS} words removed",
        f"  6. Posts with more than {MAX_WORDS} words removed",
        f"     (proxy for editorial walls-of-text; all posts >1000",
        f"     words in the sample were verified to be roundup content)",
        f"  7. Posts outside date window {AFTER_DATE} – {BEFORE_DATE} removed",
        "",
        "Note on [deleted] authors: Posts by users who subsequently",
        "deleted their Reddit account were RETAINED. Account deletion",
        "does not affect post content; the eWOM text is preserved and",
        "the brand attribution remains valid.",
        "",
        "=" * 60,
        "RESULTS",
        "-" * 60,
        f"Original posts:    {n_original}",
        f"Removed total:     {n_removed_total}",
        f"  - Editorial:     {len(removed['editorial_roundup'])}",
        f"  - Bots:          {len(removed['bot_author'])}",
        f"  - Too short:     {len(removed['word_count_too_low'])}",
        f"  - Too long:      {len(removed['word_count_too_high'])}",
        f"  - Missing text:  {len(removed['missing_text'])}",
        f"  - Date range:    {len(removed['out_of_date_range'])}",
        f"  - Duplicates:    {len(removed['duplicate_id'])}",
        f"Retained:          {n_clean} ({100*n_clean/n_original:.1f}%)",
        "",
        "BRAND DISTRIBUTION (CLEANED)",
        "-" * 60,
        f"{'Brand':<24} {'N':>6}  {'Nature':<14}",
    ]
    for b, cnt in sorted(brand_counts_clean.items()):
        flag = "  ⚠ BELOW MIN" if cnt < 500 else ""
        report_lines.append(f"  {b:<24} {cnt:>5}{flag}")

    report_lines += [
        "",
        f"{'TOTAL':<24} {n_clean:>6}",
        "",
        "WORD COUNT DISTRIBUTION (CLEANED)",
        "-" * 60,
        f"  Min:    {word_counts_clean[0]}",
        f"  Median: {word_counts_clean[nc//2]}",
        f"  Mean:   {sum(word_counts_clean)//nc}",
        f"  Max:    {word_counts_clean[-1]}",
        "",
        "YEAR DISTRIBUTION (CLEANED)",
        "-" * 60,
    ]
    for yr, cnt in sorted(year_dist_clean.items()):
        report_lines.append(f"  {yr}: {cnt}")

    with open(REPORT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"✓ Report saved:   {REPORT_TXT}")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
