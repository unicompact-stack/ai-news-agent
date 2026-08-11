#!/usr/bin/env python3
"""
bridge/bridge_adapters.py — адаптеры для 3 агентов AI Office.

Агенты:
  1. Сканер трендов (trend_scan) — RSS на русском, дедупликация
  2. Контент-мейкер (content_generate, image_prompt) — посты и промты
  3. Издатель (report_build, vk_post) — отчёты и публикация в ВК
"""

import hashlib
import html
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BRIDGE_DIR.parent
SITE_DIR = REPO_ROOT / "site"
DATA_DIR = BRIDGE_DIR / "data"
SEEN_FILE = DATA_DIR / "seen_articles.json"

# ===== Русскоязычные RSS-источники =====
TREND_SOURCES = [
    {"name": "Хабр", "url": "https://habr.com/ru/rss/articles/", "tags": ["технологии", "маркетинг", "IT"]},
    {"name": "vc.ru", "url": "https://vc.ru/rss", "tags": ["бизнес", "стартап", "маркетинг", "продукт"]},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/news.xml", "tags": ["бизнес", "экономика", "политика"]},
    {"name": "Газета: Бизнес", "url": "https://www.gazeta.ru/export/rss/business.xml", "tags": ["бизнес", "финансы", "экономика"]},
    {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml", "tags": ["новости", "политика", "экономика"]},
]

# ===== Хранилище_seen =====
def _load_seen():
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"hashes": [], "last_scan": None}


def _save_seen(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _article_hash(title, link):
    key = f"{title.strip().lower()}|{link.strip().lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def esc_html(text):
    return html.escape(str(text or ""), quote=False)


# ===== 1. Сканер трендов =====
def adapter_trend_scan(task, emit):
    """Парсит рус. RSS-источники. Дедупликация: повторы пропускаются."""
    emit("status", "running", "Запускаю сканирование трендов…")

    seen = _load_seen()
    seen_hashes = set(seen.get("hashes", []))
    new_items = []
    skipped = 0
    errors = 0

    for src in TREND_SOURCES:
        emit("status", "running", f"Читаю {src['name']}…")
        try:
            req = urllib.request.Request(src["url"], headers={
                "User-Agent": "Mozilla/5.0 (AI Office)",
                "Accept-Language": "ru-RU,ru;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            # Пытаемся определить кодировку
            try:
                root = ET.fromstring(data.decode("utf-8"))
            except (UnicodeDecodeError, ET.ParseError):
                try:
                    root = ET.fromstring(data.decode("windows-1251", errors="replace"))
                except ET.ParseError:
                    continue
            for item in root.iter("item"):
                title = unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", item.findtext("title") or "")).strip())
                link = (item.findtext("link") or "").strip()
                desc = unescape(re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip())[:300]

                if not title or not link:
                    continue

                h = _article_hash(title, link)
                if h in seen_hashes:
                    skipped += 1
                    continue

                new_items.append({
                    "source": src["name"],
                    "title": title,
                    "link": link,
                    "description": desc,
                    "hash": h,
                })
                seen_hashes.add(h)
        except Exception as e:
            emit("status", "running", f"Ошибка {src['name']}: {e}")
            errors += 1

    # СохраняемSeen (сначала старые, потом новые — чтобы не терять)
    all_hashes = seen.get("hashes", []) + [h for h in seen_hashes if h not in set(seen.get("hashes", []))]
    seen["hashes"] = all_hashes[-1000:]  # храним последние 1000
    seen["last_scan"] = datetime.now(timezone.utc).isoformat()
    _save_seen(seen)

    if not new_items:
        msg = f"Новых трендов нет (пропущено повторов: {skipped})"
        emit("status", "succeeded", msg)
        return {"ok": True, "text": msg, "data": [], "count": 0, "skipped": skipped}

    # Ограничиваем 15
    new_items = new_items[:15]

    # Формируем вывод
    lines = []
    for i, it in enumerate(new_items, 1):
        lines.append(f"{i}. [{it['source']}] {it['title']}")
        if it["description"]:
            lines.append(f"   {it['description'][:150]}…")
        lines.append(f"   {it['link']}")
        lines.append("")

    text = f"🆕 Новых трендов: {len(new_items)}\n"
    if skipped:
        text += f"⏭️ Пропущено повторов: {skipped}\n"
    if errors:
        text += f"⚠️ Ошибок источников: {errors}\n"
    text += "\n" + "\n".join(lines)

    # Сохраняем в файл для Контент-мейкера
    trends_file = DATA_DIR / "latest_trends.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(trends_file, "w", encoding="utf-8") as f:
        json.dump(new_items, f, ensure_ascii=False, indent=2)

    emit("result", "done", {"count": len(new_items), "skipped": skipped})
    return {"ok": True, "text": text, "data": new_items, "count": len(new_items)}


# ===== 2. Контент-мейкер =====
def adapter_content_generate(task, emit):
    """Генерирует пост/статью из тренда. Ввод: номер тренда или тема."""
    emit("status", "running", "Генерирую контент…")

    query = (task.get("input") or "").strip()
    trends_file = DATA_DIR / "latest_trends.json"

    # Загружаем тренды
    trends = []
    if trends_file.exists():
        try:
            with open(trends_file, "r", encoding="utf-8") as f:
                trends = json.load(f)
        except Exception:
            pass

    # Определяем какой тренд
    trend = None
    if query.isdigit() and trends:
        idx = int(query) - 1
        if 0 <= idx < len(trends):
            trend = trends[idx]
    elif query.lower().startswith("тема:"):
        topic = query[5:].strip()
        trend = {"title": topic, "source": "Ручной ввод", "description": ""}
    elif trends:
        trend = trends[0]  # первый тренд по умолчанию

    if not trend:
        emit("status", "failed", "Нет трендов. Сначала запустите «Сканер трендов».")
        return {"ok": False, "error": "Нет трендов"}

    title = trend.get("title", "")
    desc = trend.get("description", "")
    source = trend.get("source", "")

    # Генерируем пост
    post_text = f"📊 {title}\n\n"
    if desc:
        post_text += f"{desc}\n\n"
    post_text += f"Источник: {source}\n\n"
    post_text += "💬 Что думаете? Делитесь опытом в комментариях!\n\n"
    post_text += f"#{' '.join(_extract_hashtags(title + ' ' + desc))}"

    # Генерируем промт для картинки
    image_prompt = _generate_image_prompt(title, desc)

    result = {
        "post": post_text,
        "image_prompt": image_prompt,
        "trend_title": title,
        "trend_source": source,
    }

    # Сохраняем
    draft_file = DATA_DIR / "latest_draft.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(draft_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    emit("result", "done", {"post_length": len(post_text)})
    return {
        "ok": True,
        "text": f"✅ Пост готов!\n\n--- Текст поста ---\n{post_text}\n\n--- Промт для картинки ---\n{image_prompt}",
        "data": result,
    }


def _extract_hashtags(text):
    """Извлекает релевантные хэштеги из текста."""
    keywords = {
        "маркетинг": "#маркетинг", "трафик": "#трафик", "продвижение": "#продвижение",
        "реклама": "#реклама", "seo": "#SEO", "контент": "#контент",
        "соцсети": "#соцсети", "блог": "#блог", "аудитория": "#аудитория",
        "конверсия": "#конверсия", "стратегия": "#стратегия", "аналитика": "#аналитика",
        "stартап": "#стартап", "бизнес": "#бизнес", "клиент": "#клиенты",
        "продажи": "#продажи", "telegram": "#telegram", "вконтакте": "#вконтакте",
        "ai": "#AI", "нейросеть": "#нейросети", "автоматизация": "#автоматизация",
    }
    text_lower = text.lower()
    tags = set()
    for kw, tag in keywords.items():
        if kw in text_lower:
            tags.add(tag)
    return list(tags)[:5] or ["#маркетинг", "#тренды"]


def _generate_image_prompt(title, description):
    """Генерирует промт для Кандинского/Мидджурни."""
    base = f"Modern digital illustration about: {title}. "
    style = "Clean minimalist style, blue-purple gradient background, professional marketing visual, tech aesthetic, no text, high quality, 4k"
    if any(w in title.lower() for w in ["ai", "нейросеть", "искусственный интеллект"]):
        style += ", neural network visualization, glowing nodes"
    elif any(w in title.lower() for w in ["маркетинг", "реклама", "трафик"]):
        style += ", growth chart, ascending arrows, business analytics"
    elif any(w in title.lower() for w in ["контент", "блог", "пост"]):
        style += ", content creation, social media icons, creative workspace"
    return base + style


# ===== 3. Издатель =====
def adapter_report_build(task, emit):
    """Генерирует HTML-отчёт из последних данных в site/."""
    emit("status", "running", "Генерирую HTML-отчёт…")

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    reports_dir = SITE_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    # Собираем данные
    trends = []
    trends_file = DATA_DIR / "latest_trends.json"
    if trends_file.exists():
        try:
            with open(trends_file, "r", encoding="utf-8") as f:
                trends = json.load(f)
        except Exception:
            pass

    draft = None
    draft_file = DATA_DIR / "latest_draft.json"
    if draft_file.exists():
        try:
            with open(draft_file, "r", encoding="utf-8") as f:
                draft = json.load(f)
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    report_id = now.strftime("%Y-%m-%d-%H%M")
    report_title = f"Отчёт {now.strftime('%d.%m.%Y %H:%M')} UTC"

    # Карточки трендов
    cards = []
    for it in trends[:20]:
        title = esc_html(it.get("title", ""))
        link = esc_html(it.get("link", "#"))
        source = esc_html(it.get("source", ""))
        desc = esc_html(it.get("description", "")[:150])
        cards.append(f"""      <article class="card">
        <div class="card-body">
          <h3><a href="{link}" target="_blank" rel="noopener">{title}</a></h3>
          <p class="desc">{desc}</p>
          <div class="card-bottom"><span class="source">{source}</span></div>
        </div>
      </article>""")

    cards_html = "\n".join(cards) if cards else "      <p>Нет данных. Запустите «Сканер трендов».</p>"

    # Черновик поста
    draft_html = ""
    if draft:
        post_text = esc_html(draft.get("post", ""))
        img_prompt = esc_html(draft.get("image_prompt", ""))
        draft_html = f"""
    <section class="rubric" style="margin-top: 2rem;">
      <h2>📝 Черновик поста</h2>
      <div class="card" style="margin-top: 1rem;">
        <div class="card-body">
          <pre style="color: rgba(255,255,255,.9); white-space: pre-wrap; word-break: break-word; font-size: 13px;">{post_text}</pre>
        </div>
      </div>
      <h3 style="color: #c792ea; margin-top: 1.5rem; font-size: 14px;">🖼️ Промт для картинки</h3>
      <div class="card" style="margin-top: 0.5rem;">
        <div class="card-body">
          <pre style="color: rgba(255,255,255,.48); white-space: pre-wrap; word-break: break-word; font-size: 12px;">{img_prompt}</pre>
        </div>
      </div>
    </section>"""

    page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc_html(report_title)} — AI Office</title>
  <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
  <header>
    <div class="container">
      <a href="../index.html" class="logo">🤖 AI Office</a>
      <p class="subtitle">Тренды · Контент · Публикации</p>
    </div>
  </header>

  <main class="container">
    <div class="report-header">
      <h1>{esc_html(report_title)}</h1>
      <p class="meta">{len(trends)} трендов · {now.strftime('%d.%m.%Y %H:%M')} UTC</p>
    </div>

    <section class="rubric">
      <h2>📈 Тренды <span class="rubric-count">({len(trends)})</span></h2>
      <div class="cards-grid">
  {cards_html}
      </div>
    </section>
    {draft_html}
  </main>

  <footer>
    <div class="container">
      <p>Сгенерировано AI Office 🤖</p>
    </div>
  </footer>
</body>
</html>"""

    report_file = reports_dir / f"{report_id}.html"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(page)

    # Обновляем index.json
    index_file = SITE_DIR / "index.json"
    reports_meta = []
    if index_file.exists():
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                reports_meta = json.load(f)
        except Exception:
            reports_meta = []
    reports_meta.insert(0, {
        "title": report_title,
        "file": f"reports/{report_id}.html",
        "trends_count": len(trends),
        "date": now.isoformat(),
    })
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(reports_meta, f, ensure_ascii=False, indent=2)

    emit("result", "done", {"report": f"reports/{report_id}.html"})
    return {
        "ok": True,
        "text": f"📄 Отчёт создан: reports/{report_id}.html\nТрендов: {len(trends)}\nСмотрите: site/",
        "data": {"report": f"reports/{report_id}.html"},
    }


def adapter_vk_post(task, emit):
    """Публикует пост в ВК. Ввод: текст (или берёт из черновика)."""
    emit("status", "running", "Подключаюсь к VK API…")

    query = (task.get("input") or "").strip()

    # Пытаемся загрузить черновик
    post_text = query
    image_prompt = None
    if not post_text:
        draft_file = DATA_DIR / "latest_draft.json"
        if draft_file.exists():
            try:
                with open(draft_file, "r", encoding="utf-8") as f:
                    draft = json.load(f)
                post_text = draft.get("post", "")
                image_prompt = draft.get("image_prompt")
            except Exception:
                pass

    if not post_text:
        emit("status", "failed", "Нет текста для поста. Введите текст или сначала создайте черновик.")
        return {"ok": False, "error": "Нет текста"}

    # Загружаем токен
    token = os.environ.get("VK_TOKEN", "")
    group_id = os.environ.get("VK_GROUP_ID", "")

    if not token:
        emit("status", "failed", "Нет VK_TOKEN в переменных окружения. Добавьте в .env")
        return {"ok": False, "error": "Нет VK_TOKEN"}

    if not group_id:
        emit("status", "failed", "Нет VK_GROUP_ID в переменных окружения. Добавьте в .env")
        return {"ok": False, "error": "Нет VK_GROUP_ID"}

    # Публикуем
    try:
        url = f"https://api.vk.com/method/wall.post?owner_id=-{group_id}&from_group=1&message={urllib.parse.quote(post_text)}&v=5.199&access_token={token}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if "response" in data:
            post_id = data["response"]
            emit("result", "done", {"post_id": post_id, "group_id": group_id})
            return {
                "ok": True,
                "text": f"✅ Пост опубликован!\nГруппа: {group_id}\nПост: wall-{group_id}_{post_id}\nhttps://vk.com/wall-{group_id}_{post_id}",
                "data": {"post_id": post_id},
            }
        else:
            error = data.get("error", {}).get("error_msg", "Неизвестная ошибка")
            emit("status", "failed", f"Ошибка VK: {error}")
            return {"ok": False, "error": error}
    except Exception as e:
        emit("status", "failed", f"Ошибка VK API: {e}")
        return {"ok": False, "error": str(e)}


# ===== Регистрация адаптеров =====
ADAPTERS = {
    "trend_scan": adapter_trend_scan,
    "content_generate": adapter_content_generate,
    "image_prompt": lambda task, emit: {
        "ok": True,
        "text": "Промт генерируется вместе с постом. Используйте «Создать пост».",
        "data": {},
    },
    "report_build": adapter_report_build,
    "vk_post": adapter_vk_post,
}
