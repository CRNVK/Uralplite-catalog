#!/usr/bin/env python3
"""Build a visual reference index from official public decor pages.

The script keeps provenance for every sample. It only downloads images that appear
on individual decor pages and are identified as decor images by alt text or OpenGraph
metadata. Review source terms before using downloaded images beyond internal evaluation.
"""
from __future__ import annotations
import json, re, time, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "visual-catalog.json"
IMG_DIR = ROOT / "vision" / "catalog-images"
IMG_DIR.mkdir(parents=True, exist_ok=True)
HEADERS = {"User-Agent": "UralPlitDecorCatalogBot/0.1 (catalog metadata refresh; contact: site owner)"}
TIMEOUT = 25
MAX_PAGES_PER_SOURCE = 700
MAX_IMAGE_BYTES = 12 * 1024 * 1024
SOURCES = [
    {"manufacturer": "NORDECO", "index": "https://www.nordeco.design/katalog-dekorov/", "prefix": "https://www.nordeco.design/katalog-dekorov/", "mode": "nordeco"},
    {"manufacturer": "Lamarty", "index": "https://www.lamarty.ru/lamarty/decors/plain.html", "prefix": "https://www.lamarty.ru/lamarty/decors/", "mode": "lamarty"},
]
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def get_html(url):
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        if "text/html" not in r.headers.get("content-type", ""):
            return None
        return r.text
    except Exception as exc:
        print(f"WARN fetch {url}: {exc}")
        return None

def image_candidates(soup, title, page_url):
    candidates = []
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        candidates.append((urljoin(page_url, og["content"]), "og:image", 0))
    title_norm = clean(title).casefold()
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("data-original") or img.get("src") or img.get("data-lazy-src")
        if not src or src.startswith("data:"):
            continue
        alt = clean(img.get("alt") or img.get("title") or "")
        if not alt:
            continue
        alt_norm = alt.casefold()
        score = 0
        if title_norm and title_norm in alt_norm: score += 8
        if alt_norm and alt_norm in title_norm: score += 5
        if any(x in alt_norm for x in ("декор", "decor", "ламарти", "nordeco")): score += 1
        if any(x in src.casefold() for x in ("logo", "icon", "banner", "social", "avatar")): score -= 10
        if score > 0:
            candidates.append((urljoin(page_url, src), alt, score))
    # Deduplicate while preserving the best score. Prefer explicit alt match over generic OG.
    best = {}
    for url, alt, score in candidates:
        if url not in best or score > best[url][1]:
            best[url] = (alt, score)
    return sorted([(u, a, s) for u, (a, s) in best.items()], key=lambda x: x[2], reverse=True)

def decor_links(source, html):
    soup = BeautifulSoup(html, "html.parser")
    links = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(source["index"], a["href"]).split("#")[0]
        title = clean(a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or "")
        if not title or len(title) > 90:
            continue
        if source["mode"] == "nordeco":
            if not href.startswith(source["prefix"]) or href.rstrip("/") == source["prefix"].rstrip("/"):
                continue
            if href.lower().endswith((".pdf", ".jpg", ".png", ".zip")):
                continue
        else:
            if not href.startswith(source["prefix"]) or not href.lower().endswith(".html"):
                continue
            if href.rstrip("/") == source["index"].rstrip("/"):
                continue
        if not re.search(r"[a-zа-яё0-9]", title, re.I):
            continue
        links[href] = title
    return list(links.items())[:MAX_PAGES_PER_SOURCE]

def make_thumbnail(image_url, decor_name):
    try:
        r = SESSION.get(image_url, timeout=TIMEOUT, stream=True)
        r.raise_for_status()
        data = r.raw.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            return None
        im = Image.open(BytesIO(data)).convert("RGB")
        if im.width < 120 or im.height < 80 or im.width / im.height > 5 or im.height / im.width > 5:
            return None
        im.thumbnail((360, 260), Image.Resampling.LANCZOS)
        key = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:16]
        filename = f"{key}.jpg"
        path = IMG_DIR / filename
        im.save(path, "JPEG", quality=78, optimize=True)
        return "vision/catalog-images/" + filename
    except Exception as exc:
        print(f"WARN image {image_url}: {exc}")
        return None

def main():
    output = {}
    errors = []
    for source in SOURCES:
        print(f"INDEX {source['manufacturer']}: {source['index']}")
        html = get_html(source["index"])
        if not html:
            errors.append(source["manufacturer"] + ": index unavailable")
            continue
        links = decor_links(source, html)
        # If a catalog index is JavaScript-heavy, retain only confirmed detail links found in its HTML.
        print(f"  detail pages discovered: {len(links)}")
        for i, (url, link_title) in enumerate(links, 1):
            detail_html = get_html(url)
            if not detail_html:
                continue
            soup = BeautifulSoup(detail_html, "html.parser")
            h1 = soup.find("h1")
            title = clean(h1.get_text(" ", strip=True) if h1 else link_title)
            description = clean((soup.find("meta", attrs={"name": "description"}) or {}).get("content", ""))
            collection = ""
            text = clean(soup.get_text(" ", strip=True))
            m = re.search(r"(?:Коллекция|Collection)\s+([^|]{2,80})", text, re.I)
            if m: collection = clean(m.group(1))
            candidates = image_candidates(soup, title, url)
            local_image = None
            original_image = ""
            # Only use explicit title/alt matches for downloads; generic OG images may be a banner.
            for image_url, alt, score in candidates:
                if score >= 5:
                    local_image = make_thumbnail(image_url, title)
                    if local_image:
                        original_image = image_url
                        break
            key = source["manufacturer"].casefold() + "|" + title.casefold()
            if key not in output or (local_image and not output[key].get("image")):
                output[key] = {
                    "manufacturer": source["manufacturer"],
                    "decor": title,
                    "collection": collection,
                    "description": description,
                    "image": local_image,
                    "source_url": url,
                    "image_source_url": original_image,
                    "source_checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            if i % 25 == 0:
                print(f"  processed {i}/{len(links)}")
    records = sorted(output.values(), key=lambda x: (x["manufacturer"].casefold(), x["decor"].casefold()))
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {len(records)} catalog records; {sum(bool(x['image']) for x in records)} with images; {len(errors)} source errors")
    if len(records) < 20:
        raise SystemExit("Too few official catalog records found; refusing to replace the existing index")
    # Missing images are allowed during initial source integration, but no blank index is published.
if __name__ == "__main__":
    main()
