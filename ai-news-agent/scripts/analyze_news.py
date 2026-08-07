#!/usr/bin/env python3
"""
Агент 2: Аналитик — фильтрует, дедуплицирует и сортирует новости по значимости.

На вход:  data/raw_news.json   (сырые записи от Агента 1)
На выход: data/analyzed_news.json (отфильтрованные, оценённые записи)

Логика:
1. Убирает мусор (пустые заголовки/ссылки)
2. Дедупликация — по нормализованным ключевым словам из заголовка
3. Скоринг значимости (0-100):
   - свежесть (до 40 баллов)
   - "крупные игроки" OpenAI/Anthropic/Google/Meta (до 20 баллов)
   - маркеры важности: release/launch/funding/etc (до 15 баллов)
   - авторитетный источник (до 15 баллов)
   - длина заголовка (до 10 баллов)
4. Фильтр: оставляем оценки >= 40, максимум 40 записей на отчёт
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from collections import Counter

# Категории для новостей
CATEGORY_RULES = [
    ("Исследования", ["research", "paper", "study", "arxiv", "benchmark", "dataset", "model release", "fine-tun"]),
    ("Инструменты", ["tool", "launch", "releases", "announces", "introduces", "api", "app", "platform", "open source", "open-source"]),
    ("Компании", ["openai", "anthropic", "google", "meta", "microsoft", "nvidia", "apple", "amazon", "funding", "raises", "acqui"]),
    ("Индустрия", ["regulation", "law", "policy", "ethic", "safety", "agreement", "court", "ban"]),
]

MAJOR_COMPANIES = ["openai", "anthropic", "google", "deepmind", "meta", "microsoft", "nvidia", "apple", "amazon", "xai", "mistral", "meta ai"]

IMPORTANT_MARKERS = [
    "release", "launch", "announces", "introduces", "funding", "raises",
    "acquires", "breakthrough", "first", "state-of-the-art", "sota",
    "open source", "open-source", "milestone", "record", "billion", "million",
]

PRIORITY_SOURCES = ["OpenAI News", "Anthropic News", "Google AI Blog", "TechCrunch AI"]

# Мусорные слова в названии — такие записи пропускаем
JUNK_TITLES = [
    "sponsored", "advertorial", "webinar", "watch:", "podcast ep",
    "daily deal", "giveaway", "promo code",
]


def normalize_title(title):
    """Нормализует заголовок для дедупликации: нижний регистр, только слова."""
    words = re.findall(r"[a-zа-я0-9]{4,}", title.lower())
    # Убираем стоп-слова
    stop = {"with", "from", "that", "this", "have", "will", "your", "about", "what", "their", "they", "the", "and", "for", "are", "was", "its", "you", "can", "has", "not", "but", "all", "new", "how", "why", "into"}
    return [w for w in words if w not in stop]


def deduplicate(items):
    """Убирает дубликаты: ищет совпадение по 2+ значимым словам."""
    seen = []
    unique = []
    for item in items:
        words = normalize_title(item["title"])
        if len(words) < 3:
            continue
        # Проверка на дубликат по пересечению слов
        is_dup = False
        for prev_words, _ in seen:
            overlap = len(set(words) & set(prev_words))
            if overlap >= min(3, max(2, len(prev_words) // 2)):
                is_dup = True
                break
        if not is_dup:
            seen.append((words, item["guid"]))
            unique.append(item)
    return unique


def score_item(item):
    """Скоринг значимости (0-100)."""
    score = 0
    title_lower = item["title"].lower()

    # 1. Свежесть (до 40 баллов)
    try:
        pub = datetime.fromisoformat(item["published"])
        now = datetime.now(timezone.utc)
        age_hours = (now - pub).total_seconds() / 3600
        if age_hours < 24:
            score += 40
        elif age_hours < 48:
            score += 30
        elif age_hours < 72:
            score += 20
        else:
            score += 10
    except (ValueError, TypeError):
        score += 20

    # 2. Крупные игроки (до 20 баллов)
    if any(c in title_lower for c in MAJOR_COMPANIES):
        score += 20

    # 3. Маркеры важности (до 15 баллов)
    marker_hits = sum(1 for m in IMPORTANT_MARKERS if m in title_lower)
    score += min(15, marker_hits * 5)

    # 4. Авторитетный источник (до 15 баллов)
    if item["source"] in PRIORITY_SOURCES:
        score += 15

    # 5. Длина заголовка (до 10 баллов) — слишком короткие/длинные хуже
    words = len(title_lower.split())
    if 5 <= words <= 16:
        score += 10
    elif words < 5:
        score += 4
    else:
        score += 6

    return min(100, score)


def categorize(title):
    """Определяет категорию новости."""
    title_lower = title.lower()
    for cat, keywords in CATEGORY_RULES:
        if any(k in title_lower for k in keywords):
            return cat
    return "Другое"


def main():
    print("=" * 60)
    print("АГЕНТ 2: Анализ, фильтрация и скоринг")
    print("=" * 60)

    if not os.path.exists("data/raw_news.json"):
        print("  [!] data/raw_news.json не найден. Сначала запустите fetch_sources.py")
        return 1

    with open("data/raw_news.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"  [*] Получено записей: {len(items)}")

    # 1. Отбрасываем мусор
    clean = [
        it for it in items
        if it["title"] and it["link"]
        and not any(j in it["title"].lower() for j in JUNK_TITLES)
    ]
    print(f"  [*] После фильтра мусора: {len(clean)}")

    # 2. Отбрасываем дубликаты
    unique = deduplicate(clean)
    print(f"  [*] После дедупликации: {len(unique)}")

    # 3. Скоринг и категоризация
    for it in unique:
        it["score"] = score_item(it)
        it["category"] = categorize(it["title"])

    # 4. Сортируем по скору и берём топ
    unique.sort(key=lambda x: (x["score"], x["published"]), reverse=True)
    top = [it for it in unique if it["score"] >= 40][:40]

    print(f"  [+] Итог для отчёта: {len(top)} записей")

    # Статистика
    if top:
        cats = Counter(it["category"] for it in top)
        print("  [+] Категории:", dict(cats))

    # Сохраняем
    os.makedirs("data", exist_ok=True)
    with open("data/analyzed_news.json", "w", encoding="utf-8") as f:
        json.dump(top, f, ensure_ascii=False, indent=2)

    print("  [+] Сохранено в data/analyzed_news.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())