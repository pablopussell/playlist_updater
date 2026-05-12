import requests
import re

# "https://ipfs.io/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/data/listas/lista_iptv.m3u"
PLAYLIST_A = "https://k2k4r8lm8tkmuxbc8lkmq1in3v0oya1p6pe9o5bu0hu30br5ko08k2gb.ipns.dweb.link/data/listas/lista_iptv.m3u"
PLAYLIST_C = "https://k51qzi5uqu5di462t7j4vu4akwfhvtjhy88qbupktvoacqfqe9uforjvhyi4wr.ipns.dweb.link/hashes.m3u"
PLAYLIST_B = "https://github.com/tutw/platinsport-m3u-updater/raw/refs/heads/main/lista.m3u"

OUTPUT_FILE = "output/updated_playlist.m3u"

EXCLUDED_LANGS = {"FR", "PT", "BE", "NL", "DE", "TR", "RU", "PL"}

LANG_PATTERN = re.compile(
    r'[\(\[\{](FR|PT|BE|NL|DE|TR|RU|PL)[\)\]\}]',
    re.IGNORECASE
)

GROUP_TITLE_PATTERN = re.compile(r'group-title="([^"]*)"', re.IGNORECASE)

def extract_group_title(line):
    m = GROUP_TITLE_PATTERN.search(line)
    return m.group(1).upper() if m else None

def fetch(url):
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.text.splitlines()
    except Exception as e:
        print(f"Error fetching {url} : {e}")
        return []

def is_gb(line):
    line = line.upper()
    return any(k in line for k in ["GB"])

def parse_m3u(lines):
    """Returns (header_lines, extgrp_lines, entries)"""
    header_lines = []
    extgrp_lines = []
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("#EXTINF"):
            if i + 1 < len(lines):
                entries.append((line, lines[i + 1].strip()))
            i += 2
        elif line.startswith("#EXTM3U"):
            header_lines.append(line)
            i += 1
        elif line.startswith("#EXTGRP"):
            extgrp_lines.append(line)
            i += 1
        elif line.startswith("#"):
            header_lines.append(line)  # #EXTVLCOPT etc.
            i += 1
        else:
            i += 1
    return header_lines, extgrp_lines, entries

def replace_group_title(line):
    # If group-title="AGENDA PLATINSPORT" exists, replace it with group-title="ENGLISH CHANNELS"
    if 'group-title=' in line:
        return re.sub(r'group-title="[^"]*"', f'group-title="{"ENGLISH CHANNELS"}"', line)
    return line

def has_excluded_language(meta: str) -> bool:
    return LANG_PATTERN.search(meta) is not None

def main():
    output = []
    seen_urls = set()
    seen_extgrp = set()

    lines_a = fetch(PLAYLIST_A)
    lines_c = fetch(PLAYLIST_C)

    headers_a, extgrp_a, entries_a = parse_m3u(lines_a)
    _,         extgrp_c, entries_c = parse_m3u(lines_c)

    # Write #EXTM3U and non-EXTGRP headers from A
    for h in headers_a:
        output.append(h)

     # Merge #EXTGRP from A and C, deduplicating by group-title value only
    for grp in extgrp_a + extgrp_c:
        title = extract_group_title(grp)
        if title and title not in seen_extgrp:
            output.append(grp)
            seen_extgrp.add(title)
        elif not title:
            output.append(grp)  # no group-title found, keep it anyway

    for meta, url in entries_a:
        if has_excluded_language(meta):
            continue
        if url not in seen_urls:
            output.append(meta)
            output.append(url)
            seen_urls.add(url)

    for meta, url in entries_c:
        if has_excluded_language(meta):
            continue
        if url not in seen_urls:
            output.append(meta)
            output.append(url)
            seen_urls.add(url)

    lines_b = fetch(PLAYLIST_B)
    _, _, entries_b = parse_m3u(lines_b)
    for meta, url in entries_b:
        if is_gb(meta) and url not in seen_urls:
            updated_meta = replace_group_title(meta)
            output.append(updated_meta)
            output.append(url)
            seen_urls.add(url)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
        
if __name__ == "__main__":
    main()
