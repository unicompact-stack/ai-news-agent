#!/usr/bin/env python3
"""
Опциональный скрипт: подтягивает og:image для новостей без картинок из RSS.

Используется для топ-N новостей, у которых нет image из RSS.
Парсит HTML-страницу и ищет <meta property="og:image">.
"""

import json
import os
import re
import sys
import urllib.request
from html import unescape


def fetch_og_image(url, timeout=10):
    """Получает og:image из HTML-страницы."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AI News Agent)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Читаем только первые 50KB — og:image обычно в <head>
            data = resp.read(50000).decode("utf-8", errors="ignore")

        # Ищем og:image
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            data, re.IGNORECASE
        )
        if match:
            return unescape(match.group(1))

        # Обратный порядок: content перед property
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            data, re.IGNORECASE
        )
        if match:
            return unescape(match.group(1))

        # Twitter card
        match = re.search(
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            data, re.IGNORECASE
        )
        if match:
            return unescape(match.group(1))

    except Exception:
        pass
    return None


def main():
    print("=" * 60)
    print("Подтягиваю og:image для новостей без картинок")
    print("=" * 60)

    if not os.path.exists("data/analyzed_news.json"):
        print("  [!] analyzed_news.json не найден")
        return 1

    with open("data/analyzed_news.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    # Берём топ-15 без картинок
    without_image = [it for it in items if not it.get("image")][:15]
    print(f"  [*] Новостей без картинок (из топ-15): {len(without_image)}")

    if not without_image:
        print("  [+] У всех уже есть картинки")
        return 0

    fetched = 0
    for i, item in enumerate(without_image):
        print(f"  [{i+1}/{len(without_image)}] {item['title'][:50]}...")
        og = fetch_og_image(item["link"])
        if og:
            item["image"] = og
            fetched += 1
            print(f"        -> OK: {og[:60]}...")
        else:
            print(f"        -> нет og:image")

    # Сохраняем обновлённый файл
    with open("data/analyzed_news.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"\n  [+] Подтянуто картинок: {fetched}/{len(without_image)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
