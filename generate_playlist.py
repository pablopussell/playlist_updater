import os
import re
import sys
import time
import json

import requests

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
JSON_SOURCE = "https://elcano-hashes.icastresana.workers.dev/"
PLAYLIST_B  = "https://github.com/tutw/platinsport-m3u-updater/raw/refs/heads/main/lista.m3u"

OUTPUT_FILE = "output/updated_playlist.m3u"
CACHE_DIR   = "cache"

# ---------------------------------------------------------------------------
# Fetch settings
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
REQUEST_TIMEOUT = 20
MAX_RETRY_AFTER = 20

# ---------------------------------------------------------------------------
# Filtering (kept from the original script)
# ---------------------------------------------------------------------------
EXCLUDED_LANGS = {"FR", "PT", "BE", "NL", "DE", "TR", "RU", "PL"}

LANG_PATTERN = re.compile(
    r'[\(\[\{](FR|PT|BE|NL|DE|TR|RU|PL)[\)\]\}]',
    re.IGNORECASE
)

GROUP_TITLE_PATTERN = re.compile(r'group-title="([^"]*)"', re.IGNORECASE)
COUNTRY_PATTERN     = re.compile(r'tvg-country="([^"]*)"', re.IGNORECASE)

# ---------------------------------------------------------------------------
# M3U template (header + group logos) — used for the JSON source
# ---------------------------------------------------------------------------
M3U_HEADER = (
    '#EXTM3U url-tvg="'
    'https://raw.githubusercontent.com/davidmuma/EPG_dobleM/refs/heads/master/guiatv.xml,'
    'https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz,'
    'https://raw.githubusercontent.com/davidmuma/EPG_dobleM/master/guiatv.xml'
    '" refresh="3600"'
)

GROUP_LOGOS = {
    "BALONCESTO":         "https://www.soyvisual.org/sites/default/files/styles/twitter_card/public/images/photos/dep_0002.jpg",
    "DAZN":               "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d6/Dazn-logo.png/601px-Dazn-logo.png",
    "EUROSPORT":          "https://logos-world.net/wp-content/uploads/2022/05/Eurosport-Logo.png",
    "FORMULA 1":          "https://i.ibb.co/2Ndmtbp/f1.png",
    "HYPERMOTION":        "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d9/LaLiga_Hypermotion_2023_Vertical_Logo.svg/2335px-LaLiga_Hypermotion_2023_Vertical_Logo.svg.png",
    "LA LIGA":            "https://i.ibb.co/sp6dD8h2/laliga-logo.png",
    "LIGA DE CAMPEONES":  "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Liga_de_Campeones_por_Movistar_Plus%2B_2023_Logo.svg/2560px-Liga_de_Campeones_por_Movistar_Plus%2B_2023_Logo.svg.png",
    "MOVISTAR":           "https://upload.wikimedia.org/wikipedia/commons/d/d9/Movistar%2B_Logo.png",
    "MOVISTAR DEPORTES":  "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Deportes_por_Movistar_Plus%2B_2022_logo.svg/2560px-Deportes_por_Movistar_Plus%2B_2022_logo.svg.png",
    "OTROS":              "https://i.ibb.co/zVNFsy0F/logo-otros.png",
    "RFEF TV":            "https://rfef.es/themes/custom/rfef/img/rfef-share.png",
    "TDT":                "https://i.ibb.co/j9xn42jB/logo-tdt.png",
}

STREAM_URL_TEMPLATE = "http://127.0.0.1:6878/ace/getstream?id={hash}"

# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------
def get_country(meta):
    m = COUNTRY_PATTERN.search(meta)
    return m.group(1).upper() if m else None


def is_allowed_country(meta):
    country = get_country(meta)
    if country is None:
        return False
    return country not in EXCLUDED_LANGS and country == "GB"


def extract_group_title(line):
    m = GROUP_TITLE_PATTERN.search(line)
    return m.group(1).upper() if m else None


def is_excluded(meta, check_country=False):
    # Check 1: tvg-country attribute (Playlist B only)
    if check_country:
        country = get_country(meta)
        if country and country in EXCLUDED_LANGS:
            return True

    # Check 2: language tag in channel name e.g. (PL), [DE], {FR}
    if LANG_PATTERN.search(meta):
        return True

    return False


def replace_group_title(line):
    if 'group-title=' in line:
        return re.sub(r'group-title="[^"]*"', 'group-title="ENGLISH CHANNELS"', line)
    return line


# ---------------------------------------------------------------------------
# Fetching: retries, cache
# ---------------------------------------------------------------------------
def looks_like_m3u(text):
    return "#EXTM3U" in text[:2000] or "#EXTINF" in text


def fetch_once_m3u(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 429:
            try:
                wait = int(r.headers.get("Retry-After", 5))
            except ValueError:
                wait = 5
            print(f"429 from {url}; waiting {min(wait, MAX_RETRY_AFTER)}s")
            time.sleep(min(wait, MAX_RETRY_AFTER))
            return None
        r.raise_for_status()
        if not looks_like_m3u(r.text):
            print(f"{url} returned content that doesn't look like an M3U")
            return None
        return r.text
    except Exception as e:
        print(f"Error fetching {url} : {e}")
        return None


def fetch_direct(url):
    for attempt in range(1, 4):
        text = fetch_once_m3u(url)
        if text:
            return text
        if attempt < 3:
            time.sleep(5 * attempt)
    return None


def fetch_json(url):
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                try:
                    wait = int(r.headers.get("Retry-After", 5))
                except ValueError:
                    wait = 5
                print(f"429 from {url}; waiting {min(wait, MAX_RETRY_AFTER)}s")
                time.sleep(min(wait, MAX_RETRY_AFTER))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"Error fetching JSON {url}: {e}")
            if attempt < 3:
                time.sleep(5 * attempt)
    return None


def load_cached_or_fetch(cache_name, fetch_fn):
    """Fetch fresh data and refresh cache; fall back to cache on failure."""
    cache_path = os.path.join(CACHE_DIR, cache_name)
    data = fetch_fn()
    if data:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            if cache_name.endswith(".json"):
                json.dump(data, f)
            else:
                f.write(data)
        return data
    if os.path.exists(cache_path):
        print(f"Using cached copy for {cache_name}")
        with open(cache_path, encoding="utf-8") as f:
            if cache_name.endswith(".json"):
                return json.load(f)
            return f.read()
    print(f"No fresh or cached data available for {cache_name}")
    return None


# ---------------------------------------------------------------------------
# M3U parsing (for Playlist B)
# ---------------------------------------------------------------------------
def parse_m3u(lines):
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
            j = i + 1
            while j < len(lines) and (lines[j].strip() == "" or lines[j].strip().startswith("#")):
                j += 1
            if j < len(lines):
                entries.append((line, lines[j].strip()))
            i = j + 1
        elif line.startswith("#EXTM3U"):
            header_lines.append(line)
            i += 1
        elif line.startswith("#EXTGRP"):
            extgrp_lines.append(line)
            i += 1
        elif line.startswith("#"):
            header_lines.append(line)
            i += 1
        else:
            i += 1
    return header_lines, extgrp_lines, entries


# ---------------------------------------------------------------------------
# JSON → M3U entry builder
# ---------------------------------------------------------------------------
def build_meta(entry):
    """Build the #EXTINF line for a single JSON entry."""
    title  = entry.get("title", "")
    group  = entry.get("group", "")
    tvg_id = entry.get("tvg_id", "")
    logo   = entry.get("logo", "")

    meta = "#EXTINF:-1"
    if tvg_id:
        meta += f' tvg-id="{tvg_id}"'
    if logo:
        meta += f' tvg-logo="{logo}"'
    meta += f' group-title="{group}",{title}'
    return meta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    output = []
    seen_urls = set()

    # --- 1. Fetch JSON source ---
    data = load_cached_or_fetch(
        "hashes.json",
        lambda: fetch_json(JSON_SOURCE)
    )
    if not data:
        print("JSON source is unavailable (no cache either); aborting.")
        sys.exit(1)

    entries_json = data.get("hashes", [])

    # --- 2. Header ---
    output.append(M3U_HEADER)
    output.append("#EXTVLCOPT:network-caching=1000")
    output.append("")

    # --- 3. EXTGRP block ---
    for group, logo in GROUP_LOGOS.items():
        output.append(f'#EXTGRP: group-title="{group}" group-logo="{logo}"')
    output.append("")

    # --- 4. JSON entries with language-tag filtering ---
    for e in entries_json:
        hash_ = e.get("hash", "")
        if not hash_:
            continue

        meta = build_meta(e)
        if is_excluded(meta):
            continue

        url = STREAM_URL_TEMPLATE.format(hash=hash_)
        if url not in seen_urls:
            output.append(meta)
            output.append(url)
            seen_urls.add(url)

    # --- 5. Playlist B with country + language filtering ---
    text_b = load_cached_or_fetch(
        "lista_b.m3u",
        lambda: fetch_direct(PLAYLIST_B)
    )
    if text_b:
        _, _, entries_b = parse_m3u(text_b.splitlines())
        for meta, url in entries_b:
            if is_allowed_country(meta) and not is_excluded(meta, check_country=True):
                updated_meta = replace_group_title(meta)
                if url not in seen_urls:
                    output.append(updated_meta)
                    output.append(url)
                    seen_urls.add(url)

    # --- 6. Write output ---
    out_dir = os.path.dirname(OUTPUT_FILE)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output) + "\n")
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
