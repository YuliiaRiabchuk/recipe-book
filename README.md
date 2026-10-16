# Книга рецептів

Особисті рецепти з книг, PDF, відео, сайтів і Telegram-каналів в одній базі. Перегляд: відкрити `site/index.html` у браузері (на телефоні теж, файл самодостатній).

## Встановлення

```bash
python -m pip install -r requirements.txt
cp .env.example .env   # вписати FDC_API_KEY з https://api.data.gov/signup
```

## Як додавати джерела

| Що | Куди |
|---|---|
| Книга, PDF | `sources/books/`, `sources/pdf/` |
| Експорт Telegram Desktop | `sources/telegram/<канал>/result.json` |
| Відео YouTube / Instagram | рядок у `sources/videos.md` |
| Сайт | рядок у `sources/links.md` |

Сирі джерела в git не потрапляють.

## Команди Claude Code

| Команда | Що робить |
|---|---|
| `/process-sources` | обробляє все нове в `sources/`, рахує КБЖВ, перезбирає сторінку |
| `/add-recipe <текст, посилання або фото>` | додає один рецепт |
| `/nutrition [id]` | перераховує КБЖВ, показує інгредієнти на підтвердження |
| `/cooked <id> <оцінка> <нотатка>` | відмічає рецепт приготованим |
| `/build` | перезбирає дані й сторінку, комітить і пушить |

## Скрипти

```bash
python scripts/build.py                          # валідація + data/recipes.json + site/index.html
python scripts/nutrition.py --all                # КБЖВ для всіх рецептів
python scripts/nutrition.py borshch-zelenyi      # для одного
python scripts/nutrition.py confirm "щавель" 168465
python scripts/nutrition.py ignore "вода"
python scripts/telegram_extract.py               # кандидати з sources/telegram/*/result.json
python scripts/video_transcript.py <URL>         # субтитри без завантаження відео
python scripts/pdf_extract.py text <pdf> <out>   # текст PDF по сторінках (також: images, sheet, cover)
```

Схема рецепта і правила: [CLAUDE.md](CLAUDE.md).
