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


def _push_to_github(emit):
    """Пушит site/ на GitHub Pages."""
    emit("status", "running", "Пушу на GitHub…")
    try:
        import subprocess

        # Проверяем есть ли токен в .env
        env_file = REPO_ROOT / "ai-news-agent" / ".env"
        token = None
        if env_file.exists():
            with open(env_file, "r") as f:
                for line in f:
                    if line.startswith("GITHUB_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break

        if not token:
            emit("status", "running", "Нет GITHUB_TOKEN — пропускаю пуш")
            return False

        # Меняем remote на URL с токеном (нужен username)
        remote_url = f"https://unicompact-stack:{token}@github.com/unicompact-stack/ai-news-agent.git"
        subprocess.run(
            ["git", "remote", "set-url", "news-agent", remote_url],
            cwd=str(REPO_ROOT), capture_output=True, timeout=10
        )

        # git add site/
        subprocess.run(
            ["git", "add", "site/"],
            cwd=str(REPO_ROOT), capture_output=True, timeout=10
        )

        # git commit
        subprocess.run(
            ["git", "commit", "-m", "auto: update reports", "--allow-empty"],
            cwd=str(REPO_ROOT), capture_output=True, timeout=10
        )

        # git push
        result = subprocess.run(
            ["git", "push", "news-agent", "main"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30
        )

        # Восстанавливаем remote
        subprocess.run(
            ["git", "remote", "set-url", "news-agent", "https://github.com/unicompact-stack/ai-news-agent.git"],
            cwd=str(REPO_ROOT), capture_output=True, timeout=10
        )

        if result.returncode == 0:
            return True
        else:
            emit("status", "running", f"Ошибка push: {result.stderr[:200]}")
            return False

    except Exception as e:
        emit("status", "running", f"Ошибка push: {e}")
        return False

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

    # Ищем картинку через Bing
    image_url = _find_image_for_post(title, desc)

    result = {
        "post": post_text,
        "image_url": image_url,
        "trend_title": title,
        "trend_source": source,
    }

    # Сохраняем
    draft_file = DATA_DIR / "latest_draft.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(draft_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    emit("result", "done", {"post_length": len(post_text)})
    img_info = f"\n🖼️ Картинка: {'найдена' if image_url else 'не найдена'}"
    if image_url:
        img_info += f"\n{image_url}"
    return {
        "ok": True,
        "text": f"✅ Пост готов!\n\n--- Текст поста ---\n{post_text}{img_info}",
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


def _search_image_bing(query, count=5):
    """Ищет картинки через Bing Images. Возвращает список URL."""
    try:
        from urllib.parse import quote_plus
        url = f"https://www.bing.com/images/search?q={quote_plus(query)}&form=HDRSC2"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        murls = re.findall(r'murl&quot;:&quot;(https?://[^&]+)&quot;', html)
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
        print(f"  [!] Ошибка Bing: {e}")
        return []


def _find_image_for_post(title, description=""):
    """Ищет картинку для поста через Bing. Возвращает URL или None."""
    stop_words = {"the", "a", "an", "is", "are", "was", "in", "on", "to",
                  "for", "of", "with", "by", "new", "has", "will", "can"}
    words = [w for w in re.findall(r'[a-zA-Zа-яА-Я]{3,}', title) if w.lower() not in stop_words]
    query = " ".join(words[:5]) or title[:50]

    urls = _search_image_bing(query, count=5)
    for img_url in urls:
        try:
            req = urllib.request.Request(img_url, method="HEAD", headers={
                "User-Agent": "Mozilla/5.0"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                ct = resp.headers.get("content-type", "")
                cl = int(resp.headers.get("content-length", 0))
                # Некоторые серверы не отдают content-length в HEAD — пропускаем проверку размера
                if "image" in ct and (cl == 0 or cl > 10000):
                    return img_url
        except Exception:
            continue
    return None


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
        image_url = draft.get("image_url", "")
        image_section = ""
        if image_url:
            image_section = f"""
      <h3 style="color: #06b6d4; margin-top: 1.5rem; font-size: 14px;">🖼️ Картинка</h3>
      <div class="card" style="margin-top: 0.5rem;">
        <div class="card-body">
          <img src="{esc_html(image_url)}" alt="" style="max-width:100%;border-radius:8px;" onerror="this.style.display='none'">
        </div>
      </div>"""
        draft_html = f"""
    <section class="rubric" style="margin-top: 2rem;">
      <h2>📝 Черновик поста</h2>
      <div class="card" style="margin-top: 1rem;">
        <div class="card-body">
          <pre style="color: rgba(255,255,255,.9); white-space: pre-wrap; word-break: break-word; font-size: 13px;">{post_text}</pre>
        </div>
      </div>{image_section}
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

    # Автопуш на GitHub Pages
    push_ok = _push_to_github(emit)

    result_text = f"📄 Отчёт создан: reports/{report_id}.html\nТрендов: {len(trends)}"
    if push_ok:
        result_text += "\n✅ Запушено на GitHub — сайт обновится через 1-2 мин"
    else:
        result_text += "\n⚠️ Не удалось запушить на GitHub (проверьте токен)"

    emit("result", "done", {"report": f"reports/{report_id}.html", "pushed": push_ok})
    return {
        "ok": True,
        "text": result_text,
        "data": {"report": f"reports/{report_id}.html", "pushed": push_ok},
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
    "report_build": adapter_report_build,
    "vk_post": adapter_vk_post,
    "deploy_site": lambda task, emit: {
        "ok": True,
        "text": "Используйте «Собрать отчёт» — он автоматически пушится на GitHub.",
        "data": {},
    },
}
