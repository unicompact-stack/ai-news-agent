# CLAUDE.md — AI Office

## Описание проекта
AI Office — 3D-офис с 3 AI-агентами для автоматизации контента. Сбор трендов из рус. RSS, генерация постов для ВК, публикация отчётов.

## Стек технологий
- **Python 3** — бэкенд (bridge/server.py)
- **React 19** — фронтенд (3d-office/)
- **Three.js** — 3D-сцена офиса
- **Vite** — сборка фронтенда
- **VK API** — публикация постов (опционально)

## Структура папок
- `bridge/` — бэкенд
  - `server.py` — Python-сервер (порт 8788)
  - `agents.json` — конфиг 3 агентов
  - `bridge_adapters.py` — 5 адаптеров скиллов
  - `data/` — данные (тренды, черновики, история)
- `3d-office/` — React-фронтенд
  - `src/` — исходники
  - `dist/` — собранный бандл
- `site/reports/` — HTML-отчёты

## Агенты
| ID | Имя | Скиллы | Что делает |
|----|-----|--------|-----------|
| trend-scout | ТРЕНДЫ | trend_scan | Парсит рус. RSS |
| content-maker | КОНТЕНТ | content_generate, image_prompt | Генерирует посты |
| publisher | ИЗДАТЕЛЬ | report_build, vk_post | HTML-отчёты + ВК |

## Роутинг
- Вопрос про «агентов / скиллы» → `bridge/agents.json`
- Вопрос про «бэкенд / API» → `bridge/server.py`
- Вопрос про «фронтенд / UI» → `3d-office/src/`
- Вопрос про «данные / тренды» → `bridge/data/`
- Вопрос про «отчёты» → `site/reports/`

## Ключевые ограничения
1. **Сервер только на Windows** — WSL падает, запускать через `start_office.bat`
2. **Порт 8788** — не 8787!
3. **Дедупликация** — через `bridge/data/seen_articles.json` (до 1000 хэшей)
4. **VK_TOKEN** — нужен для публикации в ВК (хранить в .env)

## Важно для новой сессии

### Где что лежит
| Что | Где |
|-----|-----|
| Сервер | `bridge/server.py` (порт 8788) |
| Конфиг агентов | `bridge/agents.json` |
| Адаптеры | `bridge/bridge_adapters.py` |
| Фронтенд | `3d-office/src/` |
| Собранный бандл | `3d-office/dist/` |
| Тренды | `bridge/data/latest_trends.json` |
| Черновик поста | `bridge/data/latest_draft.json` |
| История задач | `bridge/data/tasks.json` |
| Сайт (отчёты) | `site/` → GitHub Pages |

### Текущие проблемы
1. **image_prompt** — заглушка, промт генерируется вместе с постом
2. **VK публикация** — нужен VK_TOKEN и VK_GROUP_ID в .env

### Как запускать
```cmd
cd C:\Users\Пользователь\Videos\VS_code1\Faunder\ai-cofounder
start_office.bat
```
Открыть: `http://127.0.0.1:8788/3d-office/`

### Как пересобрать фронтенд
```cmd
cd 3d-office
npm run build
```

### Как обновить сайт на GitHub Pages
1. Сгенерировать отчёт через Издателя
2. Скопировать `site/` в репозиторий `ai-news-agent`
3. Запушить:
```cmd
cd path/to/ai-news-agent
git add site/
git commit -m "update reports"
git push
```
Сайт: `https://unicompact-stack.github.io/ai-news-agent/site/`

### Команды агентов
1. ТРЕНДЫ: `собери тренды`
2. КОНТЕНТ: `сделай пост из 1` или `тема: маркетинг в Telegram`
3. ИЗДАТЕЛЬ: `опубликуй отчёт`

### RSS-источники (работают)
| Источник | Статус |
|----------|--------|
| Хабр | ✅ |
| vc.ru | ✅ |
| Коммерсантъ | ✅ |
| Газета: Бизнес | ✅ |
| ТАСС | ✅ |
