#!/usr/bin/env python3
"""
Агент 1: Поисковик — собирает свежие новости по ИИ из бесплатных RSS-источников.

На выходе: data/raw_news.json — сырые записи со всех источников.
Использует только стандартную библиотеку Python (urllib + xml.etree).
"""

import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

# ---------------------------------------------------------------------------
# Источники (бесплатные RSS, без API-ключей)
# None = забираем все записи | список = фильтр по ключевым словам в заголовке
# ---------------------------------------------------------------------------
SOURCES = [
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "keywords": None},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "keywords": None},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "keywords": None},
    {"name": "Hacker News", "url": "https://hnrss.org/newest?q=AI&points=50", "keywords": None},
    {"name": "arXiv AI", "url": "https://export.arxiv.org/rss/cs.AI", "keywords": None},
    {"name": "Reddit r/artificial", "url": "https://www.reddit.com/r/artificial/.rss", "keywords": None},
    {"name": "Reddit r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/.rss", "keywords": None},
    {"name": "MIT News AI", "url": "https://news.mit.edu/rss/topic/artificial-intelligence2", "keywords": None},
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "keywords": None},
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "keywords": None},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/ai/latest/rss", "keywords": None},
    {"name": "ScienceDaily AI", "url": "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml", "keywords": None},
    {"name": "MarkTechPost", "url": "https://www.marktechpost.com/feed/", "keywords": None},
    {"name": "AI News", "url": "https://artificialintelligence-news.com/feed/", "keywords": None},
    {"name": "KDnuggets", "url": "https://www.kdnuggets.com/feed", "keywords": None},
]

# Убираем мусор из текста
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)          # HTML-теги
    text = re.sub(r"\s+", " ", text)              # множественные пробелы
    return unescape(text).strip()


def extract_image(item):
    """Извлекает URL картинки из RSS-item (media:content, enclosure, media:thumbnail)."""
    # media:content
    for ns in ["media:content", "{http://search.yahoo.com/mrss/}content"]:
        el = item.find(ns)
        if el is not None:
            url = el.get("url", "")
            if url:
                return url

    # media:thumbnail
    for ns in ["media:thumbnail", "{http://search.yahoo.com/mrss/}thumbnail"]:
        el = item.find(ns)
        if el is not None:
            url = el.get("url", "")
            if url:
                return url

    # enclosure (type=image)
    enc = item.find("enclosure")
    if enc is not None and "image" in enc.get("type", ""):
        url = enc.get("url", "")
        if url:
            return url

    # og:image из description (если есть <img> тег)
    desc = item.findtext("description") or ""
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc)
    if img_match:
        return img_match.group(1)

    return None

def parse_date(date_str):
    """Пытается распарсить дату в ISO, иначе возвращает текущее время."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    # Распространённые форматы
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()

def fetch_feed(source):
    """Загружает и парсит один RSS-фид. Возвращает список записей."""
    items = []
    try:
        req = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "Mozilla/5.0 (AI News Agent; +https://github.com/)"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()

        root = ET.fromstring(data)

        # RSS 2.0: <rss><channel><item>
        for item in root.iter("item"):
            title = clean_text(item.findtext("title"))
            link = clean_text(item.findtext("link"))
            desc = clean_text(item.findtext("description"))
            pub_date = parse_date(item.findtext("pubDate"))
            guid = clean_text(item.findtext("guid")) or link

            items.append({
                "source": source["name"],
                "title": title,
                "link": link,
                "summary": desc[:500],
                "published": pub_date,
                "guid": guid,
                "image": extract_image(item),
            })

        # Atom: <feed><entry>
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = clean_text(entry.findtext("{http://www.w3.org/2005/Atom}title"))
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href") if link_el is not None else ""
            desc_el = entry.find("{http://www.w3.org/2005/Atom}summary")
            desc = clean_text(desc_el.text if desc_el is not None else "")
            date_el = entry.find("{http://www.w3.org/2005/Atom}updated")
            pub_date = parse_date(date_el.text if date_el is not None else "")
            id_el = entry.find("{http://www.w3.org/2005/Atom}id")
            guid = clean_text(id_el.text if id_el is not None else "") or link

            items.append({
                "source": source["name"],
                "title": title,
                "link": link,
                "summary": desc[:500],
                "published": pub_date,
                "guid": guid,
                "image": extract_image(entry),
            })

    except Exception as e:
        print(f"  [!] Ошибка {source['name']}: {e}")

    return items

def main():
    print("=" * 60)
    print("АГЕНТ 1: Сбор новостей из RSS-источников")
    print("=" * 60)

    all_items = []
    for source in SOURCES:
        print(f"  [*] {source['name']}...")
        items = fetch_feed(source)

        # Фильтр по ключевым словам, если заданы
        if source["keywords"]:
            keywords = [k.lower() for k in source["keywords"]]
            items = [
                it for it in items
                if any(k in it["title"].lower() for k in keywords)
            ]

        all_items.extend(items)
        print(f"      -> {len(items)} записей")

    # Сортировка по дате (новые сверху)
    all_items.sort(key=lambda x: x["published"], reverse=True)

    print(f"\n  [+] Всего собрано: {len(all_items)} записей")

    # Сохраняем результат
    os.makedirs("data", exist_ok=True)
    with open("data/raw_news.json", "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)

    print("  [+] Сохранено в data/raw_news.json")
    return 0

if __name__ == "__main__":
    sys.exit(main())