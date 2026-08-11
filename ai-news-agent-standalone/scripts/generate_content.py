#!/usr/bin/env python3
"""
Агент 2.5: Контент-мейкер — берёт топ-новость и делает пост + ищет картинку.

На вход:  data/analyzed_news.json (отфильтрованные записи от Агента 2)
На выход: data/latest_draft.json (черновик поста с реальной картинкой)

Логика:
1. Берём новость с наивысшим скором
2. Генерируем текст поста для VK
3. Ищем картинку через Bing Images (или берём og:image из новости)
4. Сохраняем черновик
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html import unescape
from urllib.parse import quote_plus

DATA_DIR = "data"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

CATEGORY_EMOJI = {
    "Исследования": "🔬",
    "Инструменты": "🛠️",
    "Компании": "🏢",
    "Индустрия": "⚖️",
    "Другое": "📌",
}


def search_image_bing(query, count=5):
    """Ищет картинки через Bing Images. Возвращает список URL."""
    url = f"https://www.bing.com/images/search?q={quote_plus(query)}&form=HDRSC2"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Bing оборачивает URL картинок как murl&quot;:&quot;URL&quot;
        murls = re.findall(r'murl&quot;:&quot;(https?://[^&]+)&quot;', html)

        # Дедупликация
        seen = set()
        urls = []
        for u in murls:
            if u not in seen:
                seen.add(u)
                urls.append(u)
                if len(urls) >= count:
                    break
        return urls
    except Exception as e:
        print(f"  [!] Ошибка поиска Bing: {e}")
        return []


def validate_image(url, timeout=8):
    """Проверяет что URL — рабочая картинка (>10KB, content-type image)."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        req.method = "HEAD"
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("content-type", "")
            cl = int(resp.headers.get("content-length", 0))
            if "image" in ct and cl > 10000:
                return True
    except Exception:
        pass
    return False


def extract_hashtags(text):
    """Извлекает релевантные хэштеги из текста."""
    keywords = {
        "ai": "#AI", "нейросеть": "#нейросети", "нейросети": "#нейросети",
        "маркетинг": "#маркетинг", "стартап": "#стартап", "бизнес": "#бизнес",
        "openai": "#OpenAI", "google": "#Google", "meta": "#Meta",
        "исследования": "#исследования", "модель": "#модель",
        "регулирование": "#регулирование", "безопасность": "#безопасность",
        "инструмент": "#инструменты", "платформа": "#платформа",
        "контент": "#контент", "текст": "#текст", "генерация": "#генерация",
    }
    text_lower = text.lower()
    tags = set()
    for kw, tag in keywords.items():
        if kw in text_lower:
            tags.add(tag)
    return list(tags)[:5] or ["#AI", "#тренды"]


def generate_post(item):
    """Генерирует текст поста для VK из новости."""
    title = item.get("title", "")
    desc = item.get("summary", "") or item.get("description", "")
    source = item.get("source", "")
    cat = item.get("category", "Другое")
    emoji = CATEGORY_EMOJI.get(cat, "📌")

    post = f"{emoji} {title}\n\n"
    if desc:
        # Берём первые 2 предложения
        sentences = re.split(r'[.!?]\s', desc)
        short = ". ".join(s.strip() for s in sentences[:2] if s.strip())
        if short and not short.endswith(('.', '!', '?')):
            short += "."
        post += f"{short}\n\n"
    post += f"Источник: {source}\n\n"
    post += "💬 Что думаете? Делитесь опытом!\n\n"
    post += " ".join(extract_hashtags(title + " " + desc))

    return post


def find_image(item):
    """Ищет картинку: сначала og:image из новости, потом Bing."""
    # 1. Пробуем og:image из новости
    existing_image = item.get("image", "")
    if existing_image:
        print(f"  [*] Картинка из RSS: {existing_image[:80]}...")
        return existing_image

    # 2. Ищем через Bing
    title = item.get("title", "")
    # Берём ключевые слова из заголовка (убираем стоп-слова)
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
                  "to", "for", "of", "with", "by", "from", "as", "into", "new",
                  "has", "have", "had", "will", "can", "may", "might", "says", "said"}
    words = [w for w in re.findall(r'[a-zA-Zа-яА-Я]{3,}', title) if w.lower() not in stop_words]
    query = " ".join(words[:5]) or title[:50]

    print(f"  [*] Ищу картинку через Bing: '{query}'")
    urls = search_image_bing(query, count=5)

    for url in urls:
        if validate_image(url):
            print(f"  [+] Найдена: {url[:80]}...")
            return url

    print("  [!] Картинка не найдена")
    return None


def main():
    print("=" * 60)
    print("АГЕНТ 2.5: Генерация контента")
    print("=" * 60)

    analyzed_file = os.path.join(DATA_DIR, "analyzed_news.json")
    if not os.path.exists(analyzed_file):
        print("  [!] analyzed_news.json не найден. Запустите analyze_news.py")
        return 1

    with open(analyzed_file, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not items:
        print("  [!] Нет новостей для контента")
        return 1

    # Берём топ-1 новость
    item = items[0]
    print(f"  [*] Топ-новость: {item['title'][:80]}")
    print(f"  [*] Скор: {item.get('score', 0)} | Категория: {item.get('category', '?')}")

    # Генерируем пост
    post_text = generate_post(item)
    print(f"  [*] Пост: {len(post_text)} символов")

    # Ищем картинку
    image_url = find_image(item)

    # Собираем черновик
    draft = {
        "post": post_text,
        "image_url": image_url,
        "trend_title": item.get("title", ""),
        "trend_source": item.get("source", ""),
        "category": item.get("category", "Другое"),
        "score": item.get("score", 0),
        "link": item.get("link", ""),
        "date": datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    draft_file = os.path.join(DATA_DIR, "latest_draft.json")
    with open(draft_file, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    print(f"  [+] Сохранено в {draft_file}")
    print(f"  [+] Картинка: {'есть' if image_url else 'нет'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
