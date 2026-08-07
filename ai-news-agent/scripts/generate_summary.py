#!/usr/bin/env python3
"""
Агент 2.5: AI-резюме — генерирует «Главное за день» через BossYoki прокси.

На вход:  data/analyzed_news.json (от Агента 2)
На выход: data/summary.txt (текст резюме для Hero-блока)

Вызывает BossYoki на Render (bossyoki-bot.onrender.com/summary),
который делает API-запросы к Groq/OpenRouter/GitHub Models.
"""

import json
import os
import sys
import urllib.request

# URL BossYoki прокси
PROXY_URL = os.environ.get("AI_PROXY_URL", "https://bossyoki-bot.onrender.com/summary")


def call_proxy(news_items):
    """Вызывает BossYoki прокси для генерации резюме."""
    payload = json.dumps({"news": news_items}).encode()

    req = urllib.request.Request(PROXY_URL, data=payload, headers={
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("summary")
    except Exception as e:
        print(f"  [!] Ошибка прокси: {e}")
        return None


def generate_summary(items):
    """Генерирует резюме «Главное за день»."""
    # Подготавливаем данные для прокси
    news_for_proxy = []
    for item in items[:15]:
        news_for_proxy.append({
            "title": item.get("title", ""),
            "category": item.get("category", "Другое"),
            "score": item.get("score", 0),
        })

    return call_proxy(news_for_proxy)


def main():
    print("=" * 60)
    print("АГЕНТ 2.5: AI-резюме «Главное за день»")
    print("=" * 60)

    if not os.path.exists("data/analyzed_news.json"):
        print("  [!] analyzed_news.json не найден")
        return 1

    with open("data/analyzed_news.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"  [*] Новостей для анализа: {len(items)}")
    print(f"  [*] Вызываю BossYoki прокси для AI-резюме...")

    summary = generate_summary(items)

    if summary:
        os.makedirs("data", exist_ok=True)
        with open("data/summary.txt", "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"  [+] Резюме сохранено в data/summary.txt")
        print(f"  [+] Длина: {len(summary)} символов")
        print()
        print("--- РЕЗЮМЕ ---")
        print(summary)
        print("--- КОНЕЦ ---")
    else:
        print("  [!] Не удалось сгенерировать резюме (BossYoki недоступен?)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
