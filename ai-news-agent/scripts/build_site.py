#!/usr/bin/env python3
"""
Агент 3: Публикатор — генерирует HTML-страницы отчётов с картинками и "Главное за день".

На вход:  data/analyzed_news.json (отфильтрованные записи от Агента 2)
На выход:
  site/index.html                    — главная лента всех отчётов
  site/reports/YYYY-MM-DD-HHMM.html  — отдельный отчёт за запуск
  data/history.json                  — история опубликованных новостей
"""

import json
import os
import re
import sys
import html
from datetime import datetime, timezone

SITE_DIR = "site"
REPORTS_DIR = os.path.join(SITE_DIR, "reports")
HISTORY_FILE = "data/history.json"

BLOG_TITLE = "AI News Agent"
BLOG_SUBTITLE = "Автоматические отчёты о новостях ИИ и технологий"

CATEGORY_EMOJI = {
    "Исследования": "🔬",
    "Инструменты": "🛠️",
    "Компании": "🏢",
    "Индустрия": "⚖️",
    "Другое": "📌",
}

CATEGORY_COLORS = {
    "Исследования": "#8b5cf6",
    "Инструменты": "#06b6d4",
    "Компании": "#f97316",
    "Индустрия": "#ef4444",
    "Другое": "#6b7280",
}


def esc(text):
    return html.escape(str(text or ""))


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"published_guids": []}


def save_history(history):
    os.makedirs("data", exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def format_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except (ValueError, TypeError):
        return iso_str


def score_style(score):
    if score >= 75:
        return "#ff6b6b", "🔥"
    elif score >= 55:
        return "#ffd93d", "⭐"
    else:
        return "#6bcb77", "💡"


def card_html(item, featured=False):
    """HTML-карточка новости с картинкой."""
    score = item.get("score", 0)
    cat = item.get("category", "Другое")
    emoji = CATEGORY_EMOJI.get(cat, "📌")
    color = CATEGORY_COLORS.get(cat, "#6b7280")
    score_color, score_label = score_style(score)
    image_url = item.get("image", "")

    image_html = ""
    if image_url:
        image_html = f"""
        <div class="card-image">
          <img src="{esc(image_url)}" alt="" loading="lazy" onerror="this.parentElement.style.display='none'">
        </div>"""

    summary = esc(item.get("summary", ""))[:300]
    if len(item.get("summary", "")) > 300:
        summary += "..."

    return f"""
    <article class="card{' card-featured' if featured else ''}">
      {image_html}
      <div class="card-body">
        <div class="card-top">
          <span class="badge" style="background:{color}20;color:{color}">{emoji} {esc(cat)}</span>
          <span class="score" style="color:{score_color}">{score_label} {score}</span>
        </div>
        <h3><a href="{esc(item['link'])}" target="_blank" rel="noopener">{esc(item['title'])}</a></h3>
        <p class="summary">{summary}</p>
        <div class="card-bottom">
          <span class="source">{esc(item['source'])}</span>
          <span class="date">{format_date(item.get('published', ''))}</span>
        </div>
      </div>
    </article>"""


def hero_html(top_items, ai_summary=""):
    """Главный блок — AI-резюме + топ-3 новости с картинками."""
    if not top_items:
        return ""

    # AI-резюме (если есть)
    summary_block = ""
    if ai_summary:
        summary_block = f"""
        <div class="ai-summary">
          <p>{esc(ai_summary)}</p>
        </div>"""

    cards = []
    for i, item in enumerate(top_items[:3]):
        score = item.get("score", 0)
        cat = item.get("category", "Другое")
        emoji = CATEGORY_EMOJI.get(cat, "📌")
        color = CATEGORY_COLORS.get(cat, "#6b7280")
        score_color, score_label = score_style(score)
        image_url = item.get("image", "")

        image_html = ""
        if image_url:
            image_html = f"""
            <div class="hero-card-image">
              <img src="{esc(image_url)}" alt="" loading="lazy" onerror="this.parentElement.style.display='none'">
            </div>"""

        summary = esc(item.get("summary", ""))[:200]

        cards.append(f"""
        <div class="hero-card">
          {image_html}
          <div class="hero-card-body">
            <span class="badge" style="background:{color}20;color:{color}">{emoji} {esc(cat)}</span>
            <h3><a href="{esc(item['link'])}" target="_blank" rel="noopener">{esc(item['title'])}</a></h3>
            <p>{summary}...</p>
            <div class="hero-card-meta">
              <span class="source">{esc(item['source'])}</span>
              <span class="score" style="color:{score_color}">{score_label} {score}</span>
            </div>
          </div>
        </div>""")

    return f"""
    <section class="hero">
      <h2>🔥 Главное за день</h2>
      {summary_block}
      <div class="hero-grid">
        {"".join(cards)}
      </div>
    </section>"""


def rubrics_html(items):
    """Новости, сгруппированные по рубрикам."""
    rubrics = {}
    for item in items:
        cat = item.get("category", "Другое")
        if cat not in rubrics:
            rubrics[cat] = []
        rubrics[cat].append(item)

    # Сортируем рубрики по количеству новостей
    sorted_rubrics = sorted(rubrics.items(), key=lambda x: -len(x[1]))

    html_parts = []
    for cat, cat_items in sorted_rubrics:
        emoji = CATEGORY_EMOJI.get(cat, "📌")
        color = CATEGORY_COLORS.get(cat, "#6b7280")

        cards = "\n".join(card_html(it) for it in cat_items[:10])

        html_parts.append(f"""
    <section class="rubric">
      <h2 style="border-left:4px solid {color};padding-left:12px">
        {emoji} {esc(cat)} <span class="rubric-count">({len(cat_items)})</span>
      </h2>
      <div class="cards-grid">
        {cards}
      </div>
    </section>""")

    return "\n".join(html_parts)


def report_page_html(report_id, report_title, items, articles_count, ai_summary=""):
    """Полная HTML-страница отчёта с картинками и рубриками."""
    top_items = items[:3]
    hero = hero_html(top_items, ai_summary)
    rubrics = rubrics_html(items[3:])

    # Статистика по категориям
    cats = {}
    for it in items:
        c = it.get("category", "Другое")
        cats[c] = cats.get(c, 0) + 1
    cat_stats = " · ".join(
        f"{CATEGORY_EMOJI.get(c, '📌')} {esc(c)}: {n}"
        for c, n in sorted(cats.items(), key=lambda x: -x[1])
    ) or "Нет данных"

    # Считаем картинки
    with_images = sum(1 for it in items if it.get("image"))

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(report_title)} — {BLOG_TITLE}</title>
  <meta name="description" content="{esc(report_title)} — {articles_count} новостей ИИ">
  <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
  <header>
    <div class="container">
      <a href="../index.html" class="logo">🤖 {BLOG_TITLE}</a>
      <p class="subtitle">{BLOG_SUBTITLE}</p>
    </div>
  </header>

  <main class="container">
    <div class="report-header">
      <h1>{esc(report_title)}</h1>
      <p class="meta">{articles_count} новостей · {cat_stats} · 🖼️ {with_images} с картинками</p>
    </div>

    {hero}

    {rubrics}
  </main>

  <footer>
    <div class="container">
      <p>Сгенерировано автоматически 🤖 · {BLOG_TITLE}</p>
    </div>
  </footer>
</body>
</html>"""


def index_page_html(reports_meta):
    """Главная страница блога."""
    if not reports_meta:
        reports_html = """
        <div class="empty">
          <p>📭 Пока нет отчётов</p>
          <p>Агенты запустятся по расписанию (утро и вечер) или вручную через Actions.</p>
        </div>
        """
    else:
        cards = []
        for r in reports_meta[:12]:  # Последние 12 отчётов
            cards.append(f"""
            <a href="{esc(r['file'])}" class="report-card">
              <h3>{esc(r['title'])}</h3>
              <p>{esc(r['articles_count'])} новостей · {esc(r['categories'])}</p>
            </a>""")
        reports_html = "\n".join(cards)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{BLOG_TITLE}</title>
  <meta name="description" content="{BLOG_SUBTITLE}">
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <header>
    <div class="container">
      <h1 class="logo">🤖 {BLOG_TITLE}</h1>
      <p class="subtitle">{BLOG_SUBTITLE}</p>
    </div>
  </header>

  <main class="container">
    <section class="hero">
      <h2>🗞️ Все отчёты</h2>
      <p>Утро и вечер — агенты собирают свежие новости по ИИ, отбирают значимые и публикуют здесь.</p>
    </section>
    <div class="reports-list">
      {reports_html}
    </div>
  </main>

  <footer>
    <div class="container">
      <p>Сгенерировано автоматически 🤖 · {BLOG_TITLE}</p>
    </div>
  </footer>
</body>
</html>"""


def main():
    print("=" * 60)
    print("АГЕНТ 3: Генерация блога с картинками и рубриками")
    print("=" * 60)

    if not os.path.exists("data/analyzed_news.json"):
        print("  [!] data/analyzed_news.json не найден. Сначала запустите analyze_news.py")
        return 1

    with open("data/analyzed_news.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    history = load_history()
    published = set(history.get("published_guids", []))

    # Читаем AI-резюме (если есть)
    ai_summary = ""
    summary_file = "data/summary.txt"
    if os.path.exists(summary_file):
        with open(summary_file, "r", encoding="utf-8") as f:
            ai_summary = f.read().strip()
        print(f"  [*] Загружено AI-резюме: {len(ai_summary)} символов")

    new_items = [it for it in items if it["guid"] not in published]
    print(f"  [*] Новых (ещё не публиковались): {len(new_items)} из {len(items)}")

    if not new_items:
        print("  [+] Новых новостей нет — отчёт не создаём.")
        return 0

    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(os.path.join(SITE_DIR, "assets"), exist_ok=True)

    now = datetime.now(timezone.utc)
    report_id = now.strftime("%Y-%m-%d-%H%M")
    report_file = f"reports/{report_id}.html"
    report_title = f"Отчёт {now.strftime('%d.%m.%Y %H:%M')} UTC"

    cats = {}
    for it in new_items:
        c = it.get("category", "Другое")
        cats[c] = cats.get(c, 0) + 1
    cats_str = ", ".join(sorted(cats.keys()))

    page = report_page_html(report_id, report_title, new_items, len(new_items), ai_summary)
    with open(os.path.join(SITE_DIR, report_file), "w", encoding="utf-8") as f:
        f.write(page)
    print(f"  [+] Создан отчёт: {report_file} ({len(new_items)} новостей)")

    # Обновляем индекс
    index_file = os.path.join(SITE_DIR, "index.json")
    reports_meta = []
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            reports_meta = json.load(f)

    # Дедупликация при загрузке: оставляем одну запись на файл,
    # выбираем с наибольшим числом новостей (самую полную)
    best_by_file = {}
    for r in reports_meta:
        key = r.get("file", "")
        if not key:
            continue
        cur = best_by_file.get(key)
        if cur is None or r.get("articles_count", 0) > cur.get("articles_count", 0):
            best_by_file[key] = r
    reports_meta = list(best_by_file.values())

    # Убираем текущий файл (заменим его свежим)
    reports_meta = [r for r in reports_meta if r.get("file") != report_file]

    reports_meta.insert(0, {
        "title": report_title,
        "file": report_file,
        "articles_count": len(new_items),
        "categories": cats_str,
        "date": now.isoformat(),
    })

    # Сортируем по дате (новые сверху), на случай дублей
    reports_meta.sort(key=lambda r: r.get("date", ""), reverse=True)

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(reports_meta, f, ensure_ascii=False, indent=2)

    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page_html(reports_meta))

    print(f"  [+] Обновлён site/index.html (всего отчётов: {len(reports_meta)})")

    # Создаём report.html — редирект на последний отчёт
    # (чтобы ссылка .../report.html всегда показывала свежий отчёт)
    last_report = reports_meta[0]["file"] if reports_meta else "index.html"
    report_redirect = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url=%s">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI News Agent — Последний отчёт</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <header>
    <div class="container">
      <a href="index.html" class="logo">🤖 AI News Agent</a>
      <p class="subtitle">Автоматические отчёты о новостях ИИ и технологий</p>
    </div>
  </header>
  <main class="container">
    <div class="hero">
      <h2>📄 Последний отчёт</h2>
      <p>Перенаправляем на свежий отчёт... <a href="%s">Открыть сейчас</a></p>
    </div>
  </main>
  <footer>
    <div class="container">
      <p>Сгенерировано автоматически 🤖 · AI News Agent</p>
    </div>
  </footer>
</body>
</html>""" % (last_report, last_report)

    with open(os.path.join(SITE_DIR, "report.html"), "w", encoding="utf-8") as f:
        f.write(report_redirect)
    print(f"  [+] Обновлён site/report.html (редирект на {last_report})")

    for it in new_items:
        published.add(it["guid"])
    history["published_guids"] = sorted(published)
    save_history(history)

    print()
    print("  [+] ГОТОВО. Блог обновлён с картинками и рубриками.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
