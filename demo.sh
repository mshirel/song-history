#!/usr/bin/env bash
# Demo script for Worship Catalog Phase 1
# Run this to see the parsing functions in action

set -e

echo "=========================================="
echo "Worship Catalog - Phase 1 Demo"
echo "=========================================="
echo ""

# Step 1: Show the demo code
echo "DEMO: Title Normalization & Parsing"
echo "------------------------------------------"
echo ""

python3 << 'EOF'
from worship_catalog.normalize import (
    strip_title_prefix,
    select_best_title,
    canonicalize_title,
    parse_credits,
    detect_publisher
)

# Demo 1: Title Stripping
print("1. TITLE PREFIX STRIPPING")
print("-" * 40)
examples = [
    "1 - We Will Glorify",
    "C - Amazing Grace",
    "1-1 Ancient Words",
    "V1a – Create In Me",
    "Bridge Mighty To Save",
    "tag Holy Ground",
]

for title in examples:
    stripped = strip_title_prefix(title)
    print(f"  Input:  '{title}'")
    print(f"  Output: '{stripped}'")
    print()

# Demo 2: Candidate Selection
print("\n2. BEST CANDIDATE SELECTION")
print("-" * 40)
candidates = [
    ["1-1 Ancient Words", "Ancient Words"],
    ["PaperlessHymnal.com", "Copyright © 2020", "We Will Glorify"],
    ["C – Amazing Grace", "Amazing Grace"],
]

for cand_list in candidates:
    best = select_best_title(cand_list)
    print(f"  Candidates: {cand_list}")
    print(f"  Best choice: '{best}'")
    print()

# Demo 3: Title Canonicalization
print("\n3. TITLE CANONICALIZATION (for deduplication)")
print("-" * 40)
titles = [
    "We Will Glorify!",
    "'Amazing Grace'",
    "We  Will   Glorify",
]

for title in titles:
    canonical = canonicalize_title(title)
    print(f"  Input:  '{title}'")
    print(f"  Canonical key: '{canonical}'")
    print()

# Demo 4: Credits Parsing
print("\n4. CREDITS PARSING")
print("-" * 40)
credit_examples = [
    "Words and Music by: Twila Paris / Arr.: Ken Young",
    "Words & Music: Traditional / Arr.: Pam Stephenson",
    "Words by: Samuel Stone\nMusic by: John B. Dykes",
]

for example in credit_examples:
    result = parse_credits(example)
    print(f"  Text: {example.replace(chr(10), ' | ')}")
    print(f"  → words_by: {result['words_by']}")
    print(f"  → music_by: {result['music_by']}")
    print(f"  → arranger: {result['arranger']}")
    print()

# Demo 5: Publisher Detection
print("\n5. PUBLISHER DETECTION")
print("-" * 40)
publisher_examples = [
    "Amazing Grace\nPaperlessHymnal.com",
    "Copyright © Taylor Publications LLC",
    "Presentation © 2020 Publications",
    "Just a regular hymn",
]

for example in publisher_examples:
    publisher = detect_publisher(example)
    print(f"  Text: {example.replace(chr(10), ' | ')}")
    print(f"  → Publisher: {publisher}")
    print()

print("\n" + "=" * 40)
print("✅ All parsing functions demonstrated!")
print("=" * 40)
EOF

echo ""
echo "Running test suite..."
echo "------------------------------------------"
python -m pytest tests/ -v --tb=short -q

echo ""
echo "=========================================="
echo "Demo Complete!"
echo "=========================================="
