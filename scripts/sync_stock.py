#!/usr/bin/env python3
"""Collect public UralPlit PVC edge product stock pages for a controlled prototype, tested by CI."""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

BASE = "https://uralplit.ru"
START = BASE + "/shop/kromochnye-materialy/kromka-pvkh-uralplit/"
PREFIX = "/shop/kromochnye-materialy/kromka-pvkh-uralplit/"
MAX_PAGES = 1200
WORKERS = 8
TIMEOUT = 25

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.links = []
        self._anchor = False
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._anchor = True
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
    def handle_endtag(self, tag):
        if tag == "a":
            self._anchor = False
    def handle_data(self, data):
        s = " ".join(data.split())
        if s:
            self.text_parts.append(s)

def canonical(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.netloc.lower() not in ("uralplit.ru", "www.uralplit.ru"):
        return None
    path = p.path or "/"
    if not path.startswith(PREFIX):
        return None
    return urlunparse(("https", "uralplit.ru", path, "", p.query, ""))

def parse_page(url):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; UralPlitPublicCatalogSync/1.0)",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    with urlopen(req, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        html = response.read().decode("utf-8", errors="replace")
    parser = PageParser()
    parser.feed(html)
    text = " ".join(parser.text_parts)
    article = re.search(r"Артикул\s*:?\s*(\d{5,})", text, re.I)
    qty = re.search(r"Кол-во\s*:?\s*([\d\s\u00a0.,]+?)\s*(м\.?)(?=\s|$)", text, re.I)
    if article and qty:
        stock_digits = re.sub(r"\D", "", qty.group(1))
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"<[^>]+>", " ", title_match.group(1)) if title_match else ""
        title = " ".join(title.replace("&nbsp;", " ").replace("&amp;", "&").split())
        width = re.search(r"Ширина,\s*мм\s*:?\s*(\d+)\s*мм", text, re.I)
        thickness = re.search(r"Толщина,\s*мм\s*:?\s*([\d,.]+)\s*мм", text, re.I)
        return {
            "url": url,
            "article": article.group(1),
            "title": title,
            "width_mm": int(width.group(1)) if width else None,
            "thickness_mm": float(thickness.group(1).replace(",", ".")) if thickness else None,
            "stock_m": int(stock_digits) if stock_digits else 0,
            "unit": "м",
        }, []
    links = []
    for href in parser.links:
        resolved = canonical(urljoin(url, href))
        if resolved and resolved not in links:
            links.append(resolved)
    return None, links

def main():
    queue = [START]
    seen = set()
    products = {}
    errors = []
    while queue and len(seen) < MAX_PAGES:
        batch = []
        while queue and len(batch) < WORKERS * 3 and len(seen) + len(batch) < MAX_PAGES:
            u = queue.pop(0)
            if u not in seen:
                seen.add(u)
                batch.append(u)
        if not batch:
            continue
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(parse_page, u): u for u in batch}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    product, links = future.result()
                    if product:
                        products[product["article"]] = product
                    else:
                        for link in links:
                            if link not in seen and link not in queue:
                                queue.append(link)
                except Exception as exc:
                    errors.append({"url": url, "error": str(exc)[:240]})
    if len(seen) >= MAX_PAGES and queue:
        raise SystemExit(f"Safety limit reached ({MAX_PAGES} pages) before crawl completed; refusing to publish partial stock.")
    if len(products) < 10:
        raise SystemExit(f"Only {len(products)} products parsed from {len(seen)} pages; refusing to publish incomplete stock.")
    output = {
        "source": START,
        "region": "Екатеринбург",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages_checked": len(seen),
        "products_count": len(products),
        "products": sorted(products.values(), key=lambda p: (p["title"].lower(), p["article"])),
        "errors_count": len(errors),
        "errors_sample": errors[:10],
        "freshness_note": "Метраж считан со страниц публичного каталога во время последнего успешного запуска; это не гарантия остатков в реальном времени."
    }
    with open("stock-data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: output[k] for k in ("region", "retrieved_at_utc", "pages_checked", "products_count", "errors_count")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
