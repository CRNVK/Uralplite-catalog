#!/usr/bin/env python3
"""Fast diagnostic of article/stock/title extraction on one public category page."""
import json
from scripts.sync_stock import STARTS, parse_page

items, links, raw_count = parse_page(STARTS[0])
print(json.dumps({
    "category_url": STARTS[0],
    "article_blocks_seen": raw_count,
    "products_parsed": len(items),
    "category_links_found": len(links),
    "samples": items[:12],
}, ensure_ascii=False, indent=2))
if len(items) < 20:
    raise SystemExit(f"Expected at least 20 parsed products from first category page, got {len(items)}")
if any(not p.get("article") or not p.get("stock_m") for p in items):
    raise SystemExit("Some extracted products lack article or stock quantity")
