#!/usr/bin/env python3
"""Collect current stock from public UralPlit PVC edge category pages."""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

BASE = "https://uralplit.ru"
PREFIX = "/shop/kromochnye-materialy/kromka-pvkh-uralplit/"
STARTS = [BASE + PREFIX + "04-mm/"]
MAX_CATEGORY_PAGES = 350
WORKERS = 6
TIMEOUT = 30

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.links = []
        self.anchors = []
        self.current_anchor = None
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            self.current_anchor = {"href": href, "text": []}
    def handle_endtag(self, tag):
        if tag == "a" and self.current_anchor is not None:
            a = self.current_anchor
            self.anchors.append({"href": a["href"], "text": " ".join(" ".join(a["text"]).split())})
            if a["href"]:
                self.links.append(a["href"])
            self.current_anchor = None
    def handle_data(self, data):
        s = " ".join(data.split())
        if s:
            self.text_parts.append(s)
            if self.current_anchor is not None:
                self.current_anchor["text"].append(s)

def canonical(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.netloc.lower() not in ("uralplit.ru", "www.uralplit.ru"):
        return None
    if not (p.path.startswith(PREFIX)):
        return None
    return urlunparse(("https", "uralplit.ru", p.path, "", p.query, ""))

def is_generic_anchor(text):
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    return not t or t in {"image", "перейти в корзину", "в корзину", "купить", "подробнее"} or len(t) < 3

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

    # On category listings, every item has an article and a quantity on the same page.
    article_matches = list(re.finditer(r"Артикул\s*:?\s*(\d{5,})", text, re.I))
    title_by_article_index = []
    product_urls = set()
    category_leaves = {"04-mm", "1-mm", "15-mm", "2-mm", "kromka-pvkh-uralplit"}
    for a in parser.anchors:
        href = canonical(urljoin(url, a["href"] or ""))
        if not href or is_generic_anchor(a["text"]):
            continue
        parsed_href = urlparse(href)
        leaf = parsed_href.path.rstrip("/").rsplit("/", 1)[-1]
        if leaf in category_leaves or (leaf.startswith("page") and leaf[4:].isdigit()) or "PAGEN_" in parsed_href.query:
            continue
        # Product-name anchors are paired with article/quantity blocks in document order.
        # Skip query-string filter/sort links: they are navigation, not product names.
        if parsed_href.query:
            continue
        title_by_article_index.append((a["text"], href))
        product_urls.add(href)

    products = {}
    for i, match in enumerate(article_matches):
        article = match.group(1)
        next_start = article_matches[i + 1].start() if i + 1 < len(article_matches) else len(text)
        segment = text[match.end():next_start]
        qty = re.search(r"Кол-во\s*:?\s*([\d\s\u00a0.,]+?)\s*м\b", segment, re.I)
        if not qty:
            continue
        stock_digits = re.sub(r"\D", "", qty.group(1))
        if not stock_digits:
            continue
        title = ""
        product_url = ""
        if i < len(title_by_article_index):
            title, product_url = title_by_article_index[i]
        if not title:
            before = text[max(0, match.start() - 180):match.start()]
            title = re.split(r"(?:Перейти в корзину|В корзину)", before, flags=re.I)[-1]
            title = re.sub(r"\[?Image\]?", " ", title, flags=re.I).strip()[-130:]
        title = " ".join(title.replace("&nbsp;", " ").replace("&amp;", "&").split())
        dim = re.search(r"(\d{2})\s*[/x×]\s*(0[,.]4|1[,.]5|1|2)\s*мм", title, re.I)
        width = int(dim.group(1)) if dim else None
        thickness = float(dim.group(2).replace(",", ".")) if dim else None
        products[article] = {
            "url": product_url or url,
            "article": article,
            "title": title,
            "width_mm": width,
            "thickness_mm": thickness,
            "stock_m": int(stock_digits),
            "unit": "м",
        }

    # Don't crawl product pages again: stock is already present in the category listing.
    category_links = []
    for href in parser.links:
        resolved = canonical(urljoin(url, href))
        if not resolved or resolved in product_urls:
            continue
        # Keep category/filter/pagination links, not arbitrary links with a product-like slug.
        path = urlparse(resolved).path.rstrip("/")
        leaf = path.rsplit("/", 1)[-1]
        query = urlparse(resolved).query
        if leaf in {"04-mm", "1-mm", "15-mm", "2-mm", "kromka-pvkh-uralplit"} or (leaf.startswith("page") and leaf[4:].isdigit()) or "PAGEN_" in query:
            category_links.append(resolved)
    return list(products.values()), list(dict.fromkeys(category_links)), len(article_matches)

def main():
    queue = list(STARTS)
    seen = set()
    products = {}
    errors = []
    while queue and len(seen) < MAX_CATEGORY_PAGES:
        batch = []
        while queue and len(batch) < WORKERS and len(seen) + len(batch) < MAX_CATEGORY_PAGES:
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
                    items, links, raw_count = future.result()
                    for item in items:
                        products[item["article"]] = item
                    for link in links:
                        if link not in seen and link not in queue:
                            queue.append(link)
                    print(f"Checked {len(seen)}/{MAX_CATEGORY_PAGES} pages; products={len(products)}; queued={len(queue)}", flush=True)
                except Exception as exc:
                    errors.append({"url": url, "error": str(exc)[:240]})
    if len(seen) >= MAX_CATEGORY_PAGES and queue:
        raise SystemExit(f"Safety limit reached ({MAX_CATEGORY_PAGES} category pages); refusing to publish partial stock.")
    if len(products) < 100:
        raise SystemExit(f"Only {len(products)} products parsed from {len(seen)} category pages; refusing to publish incomplete stock.")
    if errors and len(errors) > max(3, int(len(seen) * 0.1)):
        raise SystemExit(f"Too many category page errors ({len(errors)}/{len(seen)}); refusing to publish partial stock.")
    output = {
        "source": STARTS,
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
