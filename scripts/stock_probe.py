#!/usr/bin/env python3
"""Probe the public UralPlit product page without publishing cached stock."""
import json
import re
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from html.parser import HTMLParser

URL = "https://uralplit.ru/shop/kromochnye-materialy/kromka-pvkh-uralplit/belyy-ws-296-352-mm-100m-bez-kleya--ul-/"

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)

def main():
    req = Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; UralPlitStockProbe/1.0)"})
    with urlopen(req, timeout=30) as response:
        status = response.status
        html = response.read().decode("utf-8", errors="replace")
    parser = TextExtractor()
    parser.feed(html)
    text = " ".join(parser.parts)
    article = re.search(r"Артикул\s*:\s*(\d{6})", text, re.I)
    qty = re.search(r"Кол-во\s*:\s*([\d\s\u00a0.,]+)\s*(м\.?)(?=\s|$)", text, re.I)
    title = re.search(r"(Белый\s+WS\s+296\s+35/2\s*мм[^.]{0,100})", text, re.I)
    width = re.search(r"Ширина,\s*мм\s*:?\s*(\d+)\s*мм", text, re.I)
    thickness = re.search(r"Толщина,\s*мм\s*:?\s*([\d,.]+)\s*мм", text, re.I)
    if status != 200 or not article or not qty:
        raise SystemExit("Probe failed: expected product article and stock quantity were not found; no stock output written.")
    result = {
        "source": URL,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "article": article.group(1),
        "title": title.group(1).strip() if title else None,
        "width_mm": int(width.group(1)) if width else None,
        "thickness_mm": float(thickness.group(1).replace(",", ".")) if thickness else None,
        "stock_m": int(re.sub(r"\D", "", qty.group(1))),
        "unit": qty.group(2),
        "note": "Single-page connectivity/parser probe only; not a complete catalog sync."
    }
    with open("stock-probe.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
