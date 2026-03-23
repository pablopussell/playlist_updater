import requests
import re

PLAYLIST_A = "https://ipfs.io/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/data/listas/lista_iptv.m3u"
PLAYLIST_B = "https://github.com/tutw/platinsport-m3u-updater/raw/refs/heads/main/lista.m3u"

OUTPUT_FILE = "output/updated_playlist.m3u"

GB = ["GB"]

def fetch(url):
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.text.splitlines()
    except Exception as e:
        print(f"Error fetching {url} : {e}")
        return []

def is_gb(line):
    line = line.upper()
    return any(k in line for k in GB)

def parse_m3u(lines):
    entries = []
    for i in range(len(lines)):
        if lines[i].startswith("#EXT"):
            if i + 1 < len(lines):
                entries.append((lines[i], lines[i+1]))
    return entries

def replace_group_title(line):
    # If group-title="AGENDA PLATINSPORT" exists, replace it with group-title="ENGLISH CHANNELS"
    if 'group-title=' in line:
        return re.sub(r'group-title="[^"]*"', f'group-title="{"ENGLISH CHANNELS"}"', line)

def main():
    output = []
    seen_urls = set()

    # --- Playlist A (keep all) ---
    lines_a = fetch(PLAYLIST_A)
    entries_a = parse_m3u(lines_a)

    for meta, url in entries_a:
        if url not in seen_urls:
            output.append(meta)
            output.append(url)
            seen_urls.add(url)

    # --- Playlist B (filter GB only) ---
    lines_b = fetch(PLAYLIST_B)
    entries_b = parse_m3u(lines_b)

    for meta, url in entries_b:
        if is_gb(meta):
            updated_meta = replace_group_title(meta)
            output.append(updated_meta)
            output.append(url)
            seen_urls.add(url)

    # Write file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

if __name__ == "__main__":
    main()
