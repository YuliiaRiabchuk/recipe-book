"""Спільне для скриптів: шляхи, читання рецептів, константи схеми."""
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = ROOT / "recipes"
DATA_DIR = ROOT / "data"
SOURCES_DIR = ROOT / "sources"
SITE_FILE = ROOT / "site" / "index.html"

CATEGORIES = ["сніданки", "супи", "основні", "салати", "випічка", "десерти", "соуси", "заготовки", "напої", "складові"]
SOURCE_TYPES = ["book", "pdf", "video", "link", "telegram", "own"]
STATUSES = ["спробувати", "приготовано", "улюблене", "не-сподобалось"]
NUTRITION_STATUSES = ["повний", "частковий", "немає"]
UNITS = ["г", "кг", "мл", "л", "шт", "ч.л.", "ст.л.", "склянка", "зубчик", "пучок", "дрібка"]
NUTRIENT_KEYS = ["kcal", "protein", "fat", "carbs"]

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)


def utf8_stdout():
    # Windows-консоль за замовчуванням не UTF-8
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def split_frontmatter(text):
    """Повертає (сирий yaml, тіло) або None, якщо frontmatter немає."""
    m = FRONTMATTER_RE.match(text)
    return (m.group(1), m.group(2)) if m else None


def read_recipe(path):
    """Повертає (meta, body). Кидає ValueError з поясненням."""
    text = Path(path).read_text(encoding="utf-8")
    parts = split_frontmatter(text)
    if not parts:
        raise ValueError("немає YAML frontmatter між рядками '---'")
    try:
        meta = yaml.safe_load(parts[0])
    except yaml.YAMLError as e:
        raise ValueError(f"помилка YAML: {e}") from None
    if not isinstance(meta, dict):
        raise ValueError("frontmatter має бути словником полів")
    return meta, parts[1]


def recipe_files():
    return sorted(RECIPES_DIR.glob("*.md"))


def find_recipe(ref):
    """Шукає рецепт за id, назвою файлу або шляхом."""
    p = Path(ref)
    if p.exists():
        return p
    candidate = RECIPES_DIR / (ref if ref.endswith(".md") else ref + ".md")
    return candidate if candidate.exists() else None


def sections(body):
    """Розбиває markdown-тіло на {заголовок ## : текст}."""
    result, current, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current is not None:
                result[current] = "\n".join(buf).strip()
            current, buf = m.group(1), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        result[current] = "\n".join(buf).strip()
    return result


def parse_steps(text):
    steps, cur = [], None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            if cur is not None:
                steps.append(cur.strip())
            cur = m.group(1)
        elif cur is not None and line.strip():
            cur += " " + line.strip()
    if cur is not None:
        steps.append(cur.strip())
    return steps
