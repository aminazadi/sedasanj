#!/usr/bin/env python3

import html
import re
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

PAGE_URL = "https://hamcall.ir/%D9%86%D9%85%D9%88%D9%86%D9%87-%D9%85%DA%A9%D8%A7%D9%84%D9%85%D8%A7%D8%AA-%DA%A9%D8%A7%D8%B1%D8%B4%D9%86%D8%A7%D8%B3%D8%A7%D9%86-%D9%87%D9%85%DA%A9%D8%A7%D9%84/"
OUTPUT_DIR = Path.home() / "Downloads" / "hamcall_audios"
AUDIO_PATTERN = re.compile(
    r'''(?:src|href|data-mediafile)\s*=\s*["']([^"']+\.(?:mp3|wav|ogg|m4a|aac)(?:\?[^"']*)?)["']''',
    re.IGNORECASE,
)


def fetch(url):
    request = Request(quote(url, safe=":/?&=%"), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request) as response:
        return response.read()


def filename_from_url(url, index):
    name = Path(unquote(urlparse(url).path)).name
    return name or f"audio_{index:02d}.mp3"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page = fetch(PAGE_URL).decode("utf-8", errors="ignore")
    urls = []

    for match in AUDIO_PATTERN.findall(html.unescape(page)):
        url = urljoin(PAGE_URL, match)
        if url not in urls:
            urls.append(url)

    if not urls:
        raise SystemExit("No audio files found.")

    for index, url in enumerate(urls, start=1):
        filename = OUTPUT_DIR / filename_from_url(url, index)
        print(f"Downloading: {filename.name}")
        filename.write_bytes(fetch(url))

    print(f"Downloaded {len(urls)} files to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
