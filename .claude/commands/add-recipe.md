---
description: Додати один рецепт з тексту, посилання або фото
argument-hint: <текст рецепта | URL | шлях до фото>
---

Додай рецепт із: $ARGUMENTS

Схема і правила в CLAUDE.md.

1. Визнач джерело:
   - URL відео (YouTube, Instagram, TikTok): `python scripts/video_transcript.py <URL>`, читай файл у `sources/transcripts/`; додай рядок у `sources/videos.md`. `source.type: video`.
   - інший URL: завантаж сторінку; додай рядок у `sources/links.md`. `source.type: link`.
   - фото або скріншот: прочитай зображення. Тип за змістом (book, якщо це сторінка книги), інакше `own`.
   - текст: `own`, якщо користувачка не назвала джерело.
   Якщо даних замало (немає інгредієнтів або кроків), спитай, а не вигадуй.
2. Перевір дублікати за назвою та основними інгредієнтами. Схожий є — зупинись, покажи його і запропонуй обʼєднати або зберегти як варіант.
3. Створи `recipes/<id>.md`: `status: спробувати`, `rating: null`, `added` сьогодні, КБЖВ `null`, `nutrition_status: немає`.
4. Нові інгредієнти: англійський запит у `data/search_hints.json`, потім `python scripts/nutrition.py <id>`.
5. `python scripts/build.py`.
6. Покажи: назву, id, кількість інгредієнтів, статус КБЖВ і що чекає підтвердження в `data/unmatched.md`.
7. Якщо джерело було посиланням, допиши рядок у `sources/processed.md`.
