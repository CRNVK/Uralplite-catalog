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

class ProductCardParser(HTMLParser):
    """Extract article, title, URL and quantity from each actual product-card container."""
    def __init__(self):
        super().__init__()
        self.card = None
        self.cards = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "div":
            if self.card is None and "shop-row-block" in classes:
                self.card = {"depth": 1, "text": [], "title_parts": [], "url": "", "in_title": False}
            elif self.card is not None:
                self.card["depth"] += 1
        if self.card is not None and tag == "a" and "shop-item-title" in classes:
            self.card["url"] = attrs.get("href") or self.card["url"]
            self.card["in_title"] = True

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag == "a":
            self.card["in_title"] = False
        if tag == "div":
            self.card["depth"] -= 1
            if self.card["depth"] <= 0:
                self.cards.append(self.card)
                self.card = None

    def handle_data(self, data):
        if self.card is None:
            return
        value = " ".join(data.split())
        if value:
            self.card["text"].append(value)
            if self.card["in_title"]:
                self.card["title_parts"].append(value)

    def products(self, page_url):
        found = {}
        for card in self.cards:
            body = " ".join(card["text"])
            article_match = re.search(r"Артикул\s*:?\s*(\d{5,})", body, re.I)
            qty_match = re.search(r"Кол-во\s*:?\s*([\d\s\u00a0.,]+?)\s*м\b", body, re.I)
            title = " ".join(" ".join(card["title_parts"]).split())
            if not article_match or not qty_match or not title:
                continue
            article = article_match.group(1)
            stock_digits = re.sub(r"\D", "", qty_match.group(1))
            if not stock_digits:
                continue
            dim = re.search(r"(\d{2})\s*[/x×]\s*(0[,.]4|1[,.]5|1|2)\s*мм", title, re.I)
            if not dim or not card["url"]:
                continue
            width = int(dim.group(1))
            thickness = float(dim.group(2).replace(",", "."))
            item = {
                "url": urljoin(page_url, card["url"]),
                "article": article,
                "title": title,
                "width_mm": width,
                "thickness_mm": thickness,
                "stock_m": int(stock_digits),
                "unit": "м",
            }
            # If desktop/mobile cards repeat, retain the first complete card per article.
            found.setdefault(article, item)
        return list(found.values())


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

    # Parse each product card as a unit so its title, URL, article and stock cannot drift apart.
    card_parser = ProductCardParser()
    card_parser.feed(html)
    parsed_products = card_parser.products(url)
    product_urls = {item["url"] for item in parsed_products}

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
        if leaf in {"04-mm", "1-mm", "15-mm", "20-mm", "2-mm", "kromka-pvkh-uralplit"} or (leaf.startswith("page") and leaf[4:].isdigit()) or "PAGEN_" in query:
            category_links.append(resolved)
    return parsed_products, list(dict.fromkeys(category_links)), len(parsed_products)

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
    if len(products) < 800:
        raise SystemExit(f"Only {len(products)} products parsed from {len(seen)} category pages; expected at least 800 across the 0.4/1/1.5/2 mm PVC categories, refusing to publish incomplete stock.")
    invalid = [p for p in products.values() if not p.get("title") or not p.get("url") or not p.get("width_mm") or p.get("thickness_mm") not in (0.4, 1.0, 1.5, 2.0)]
    if invalid:
        raise SystemExit(f"{len(invalid)} products have invalid title/URL/dimensions; refusing to publish questionable stock.")
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
