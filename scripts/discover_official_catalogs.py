#!/usr/bin/env python3
"""Discover public decor catalogue links and image metadata; never republishes source images."""
import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / "catalog-sources.json").read_text(encoding="utf-8"))["sources"]
OUT = ROOT / "catalog-discovery.json"
HEADERS = {"User-Agent": "UralPlitCatalogResearch/1.0 (+catalog metadata discovery)"}

class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.images = [], []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append({"href": a["href"], "text": ""})
            self.current = self.links[-1]
        elif tag == "img" and (a.get("src") or a.get("data-src")):
            self.images.append({"src": a.get("data-src") or a.get("src"), "alt": a.get("alt", "")})
    def handle_data(self, data):
        if getattr(self, "current", None):
            self.current["text"] += data.strip() + " "

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=35) as response:
        if "text/html" not in response.headers.get("Content-Type", ""):
            return None
        return response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")

def main():
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "sources": []}
    for source in SOURCES:
        item = {**source, "status": "skipped", "decor_links": [], "image_references": [], "error": ""}
        if source.get("enabled") and source["mode"] == "html_catalog":
            try:
                html = fetch(source["url"])
                parser = Collector()
                parser.feed(html or "")
                base_host = urlparse(source["url"]).netloc
                for link in parser.links:
                    url = urljoin(source["url"], link["href"])
                    if urlparse(url).netloc.endswith(base_host) and re.search(r"decor|dekor|catalog|promo", url, re.I):
                        item["decor_links"].append({"url": url, "label": link["text"].strip()[:180]})
                for image in parser.images:
                    url = urljoin(source["url"], image["src"])
                    if url.startswith("https://"):
                        item["image_references"].append({"url": url, "alt": image["alt"][:180]})
                item["decor_links"] = list({x["url"]: x for x in item["decor_links"]}.values())
                item["image_references"] = list({x["url"]: x for x in item["image_references"]}.values())
                item["status"] = "ok"
            except Exception as exc:
                item["status"] = "error"
                item["error"] = str(exc)[:500]
        result["sources"].append(item)
        print(f'{source["manufacturer"]}: {item["status"]}; decor links={len(item["decor_links"])}; images={len(item["image_references"])}')
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
