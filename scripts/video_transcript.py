"""Тягне субтитри відео через yt-dlp без завантаження самого відео.

  python scripts/video_transcript.py <URL> [<URL> ...]
  python scripts/video_transcript.py --from-file sources/videos.md

Мови за пріоритетом: uk, ru, en; ручні субтитри важливіші за автоматичні.
Опис відео теж зберігається: у ньому часто є список інгредієнтів.
Результат: sources/transcripts/<сайт>-<id>.md
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

from recipe_lib import SOURCES_DIR, utf8_stdout

try:
    import yt_dlp
except ImportError:
    print("yt-dlp не встановлено: python -m pip install yt-dlp")
    sys.exit(2)

OUT_DIR = SOURCES_DIR / "transcripts"
LANGS = ["uk", "ru", "en"]
URL_RE = re.compile(r"https?://\S+")


def pick_language(info):
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for lang in LANGS:
        for pool, kind in ((manual, "ручні"), (auto, "автоматичні")):
            for code in (lang, f"{lang}-orig"):
                if code in pool:
                    return code, kind, pool is auto
    return None, None, None


def vtt_to_text(vtt):
    lines, prev = [], None
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or re.match(r"^(Kind|Language|NOTE)\b", line) or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line != prev:  # автосубтитри дублюють рядки
            lines.append(line)
            prev = line
    return "\n".join(lines)


def process(url):
    base_opts = {"quiet": True, "no_warnings": True, "noprogress": True, "skip_download": True}
    with yt_dlp.YoutubeDL(base_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    site = (info.get("extractor_key") or "video").lower()
    vid = re.sub(r"[^A-Za-z0-9_-]", "_", str(info.get("id")))
    out = OUT_DIR / f"{site}-{vid}.md"

    code, kind, is_auto = pick_language(info)
    transcript = ""
    if code:
        with tempfile.TemporaryDirectory() as tmp:
            opts = dict(base_opts, writesubtitles=not is_auto, writeautomaticsub=is_auto,
                        subtitleslangs=[code], subtitlesformat="vtt",
                        outtmpl=str(Path(tmp) / "sub"))
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            files = list(Path(tmp).glob("*.vtt"))
            if files:
                transcript = vtt_to_text(files[0].read_text(encoding="utf-8", errors="replace"))

    header = [
        f"# {info.get('title', '')}",
        "",
        f"- URL: {info.get('webpage_url') or url}",
        f"- Автор: {info.get('uploader') or info.get('channel') or ''}",
        f"- Дата: {info.get('upload_date') or ''}",
        f"- Субтитри: {f'{code}, {kind}' if transcript else 'немає'}",
        "",
        "## Опис",
        "",
        (info.get("description") or "").strip() or "(порожньо)",
        "",
        "## Транскрипт",
        "",
        transcript or "(субтитрів немає)",
        "",
    ]
    out.write_text("\n".join(header), encoding="utf-8")
    status = f"субтитри {code} ({kind})" if transcript else "без субтитрів, збережено опис"
    print(f"{url} → {out.relative_to(SOURCES_DIR.parent).as_posix()}: {status}")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--from-file")
    args = ap.parse_args()
    urls = list(args.urls)
    if args.from_file:
        text = re.sub(r"<!--.*?-->", "", Path(args.from_file).read_text(encoding="utf-8"), flags=re.S)
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            m = URL_RE.search(line)
            if m:
                urls.append(m.group(0))
    if not urls:
        print("Немає посилань. Передай URL або --from-file sources/videos.md")
        sys.exit(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed = 0
    for url in urls:
        try:
            process(url)
        except yt_dlp.utils.DownloadError as e:
            failed += 1
            print(f"{url}: не вдалося ({str(e).splitlines()[0]})")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
