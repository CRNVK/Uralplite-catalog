#!/usr/bin/env python3
"""Diagnostic: inspect raw product-card markup and extraction alignment."""
import json
import re
from urllib.request import Request, urlopen
from scripts.sync_stock import STARTS, parse_page

url=STARTS[0]
req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; UralPlitPublicCatalogSync/1.0)"})
with urlopen(req,timeout=30) as response:
    html=response.read().decode("utf-8",errors="replace")
items, links, raw_count = parse_page(url)
# Print source context around the first article occurrence, which reveals the card's DOM structure.
m=re.search(r"Артикул\s*:?\s*024017",html,re.I)
print("RAW_HTML_CONTEXT_START")
print(html[max(0,m.start()-1800):m.end()+900] if m else "ARTICLE_NOT_FOUND")
print("RAW_HTML_CONTEXT_END")
print(json.dumps({
 "category_url":url,"article_blocks_seen":raw_count,"products_parsed":len(items),
 "category_links_found":len(links),"samples":items[:5]
},ensure_ascii=False,indent=2))
if len(items)<20:
 raise SystemExit(f"Expected at least 20 parsed products from first category page, got {len(items)}")
