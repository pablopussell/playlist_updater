import os
import re
import sys
import time
 
import requests
 
# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
IPNS_KEY = "k51qzi5uqu5di462t7j4vu4akwfhvtjhy88qbupktvoacqfqe9uforjvhyi4wr"
PATH_HASHES = "hashes.m3u"
 
# Gateways are tried in order; the one that last worked is moved to the front.
GATEWAY_TEMPLATES = [
    "https://dweb.link/ipns/{key}/{path}",
    "https://ipfs.io/ipns/{key}/{path}",
    "https://{key}.ipns.dweb.link/{path}",
    "https://gateway.pinata.cloud/ipns/{key}/{path}",
    "https://{key}.ipns.inbrowser.link/{path}",
]
 
PLAYLIST_B = "https://github.com/tutw/platinsport-m3u-updater/raw/refs/heads/main/lista.m3u"
 
OUTPUT_FILE = "output/updated_playlist.m3u"
CACHE_DIR = "cache"
 
# ---------------------------------------------------------------------------
# Fetch settings
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
REQUEST_TIMEOUT = 20
MAX_ROUNDS = 2            # full passes over all gateways (fallback only)
ROUND_BACKOFF = 10        # seconds, multiplied by round number
MAX_RETRY_AFTER = 20      # cap on Retry-After sleeps
DEADLINE_SECONDS = 120    # max time spent on gateways per playlist
 
# Files downloaded by the workflow through the local Kubo node (preferred source)
LOCAL_DIR = "downloads"
 
# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
EXCLUDED_LANGS = {"FR", "PT", "BE", "NL", "DE", "TR", "RU", "PL"}
 
LANG_PATTERN = re.compile(
    r'[\(\[\{](FR|PT|BE|NL|DE|TR|RU|PL)[\)\]\}]',
    re.IGNORECASE
)
 
GROUP_TITLE_PATTERN = re.compile(r'group-title="([^"]*)"', re.IGNORECASE)
COUNTRY_PATTERN = re.compile(r'tvg-country="([^"]*)"', re.IGNORECASE)
 
 
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
 
 
# ---------------------------------------------------------------------------
# Fetching: retries, gateway fallback, cache
# ---------------------------------------------------------------------------
def looks_like_m3u(text):
    """Gateways sometimes return 200 with an HTML bootstrap page; reject those."""
    return "#EXTM3U" in text[:2000] or "#EXTINF" in text
 
 
def fetch_once(url):
    """Single request. Returns text, or None on any failure (logged)."""
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
 
 
def fetch_local(path):
    """Read a file the workflow already downloaded via the local Kubo node."""
    local_path = os.path.join(LOCAL_DIR, path)
    if not os.path.exists(local_path):
        return None
    with open(local_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if looks_like_m3u(text):
        print(f"Using local Kubo download for {path}")
        return text
    print(f"Local file {local_path} doesn't look like an M3U; ignoring it")
    return None
 
 
def fetch_ipns(path):
    """Try every gateway with backoff and an overall deadline. Returns text or None."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    for rnd in range(1, MAX_ROUNDS + 1):
        for template in list(GATEWAY_TEMPLATES):
            if time.monotonic() > deadline:
                print(f"Gateway deadline reached for {path}")
                return None
            url = template.format(key=IPNS_KEY, path=path)
            text = fetch_once(url)
            if text:
                # Remember the working gateway so the next file tries it first
                GATEWAY_TEMPLATES.remove(template)
                GATEWAY_TEMPLATES.insert(0, template)
                return text
        wait = ROUND_BACKOFF * rnd
        if rnd < MAX_ROUNDS and time.monotonic() + wait < deadline:
            print(f"All gateways failed (round {rnd}/{MAX_ROUNDS}); retrying in {wait}s")
            time.sleep(wait)
    return None
 
 
def fetch_ipns_playlist(path):
    """Preferred: local Kubo download. Fallback: public gateways. Then the cache."""
    return fetch_local(path) or fetch_ipns(path)
 
 
def fetch_direct(url):
    """Direct URL (e.g. GitHub raw) with simple retries."""
    for attempt in range(1, 4):
        text = fetch_once(url)
        if text:
            return text
        if attempt < 3:
            time.sleep(5 * attempt)
    return None
 
 
def load_playlist(cache_name, fetch_fn):
    """Fetch fresh data and refresh the cache; fall back to the cache on failure."""
    cache_path = os.path.join(CACHE_DIR, cache_name)
    text = fetch_fn()
    if text:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text.splitlines()
    if os.path.exists(cache_path):
        print(f"Using cached copy for {cache_name}")
        with open(cache_path, encoding="utf-8") as f:
            return f.read().splitlines()
    print(f"No fresh or cached data available for {cache_name}")
    return []
 
 
# ---------------------------------------------------------------------------
# M3U parsing / transformation
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
 
 
def replace_group_title(line):
    # Replace any group-title (e.g. "AGENDA PLATINSPORT") with "ENGLISH CHANNELS"
    if 'group-title=' in line:
        return re.sub(r'group-title="[^"]*"', 'group-title="ENGLISH CHANNELS"', line)
    return line
 
 
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
 
 
# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    output = []
    seen_urls = set()
    seen_extgrp = set()
 
    lines_h = load_playlist(PATH_HASHES, lambda: fetch_ipns_playlist(PATH_HASHES))
 
    # Don't overwrite the output with an empty playlist if the main source is gone
    if not lines_h:
        print("hashes.m3u is unavailable (no cache either); aborting.")
        sys.exit(1)
 
    headers_h, extgrp_h, entries_h = parse_m3u(lines_h)
 
    # Write #EXTM3U and non-EXTGRP headers from hashes.m3u
    for h in headers_h:
        output.append(h)
 
    # Keep #EXTGRP lines, deduplicating by group-title value only
    for grp in extgrp_h:
        title = extract_group_title(grp)
        if title and title not in seen_extgrp:
            output.append(grp)
            seen_extgrp.add(title)
        elif not title:
            output.append(grp)  # no group-title found, keep it anyway
 
    for meta, url in entries_h:
        if is_excluded(meta):
            continue
        if url not in seen_urls:
            output.append(meta)
            output.append(url)
            seen_urls.add(url)
 
    lines_b = load_playlist("lista_b.m3u", lambda: fetch_direct(PLAYLIST_B))
    _, _, entries_b = parse_m3u(lines_b)
    for meta, url in entries_b:
        if is_allowed_country(meta) and not is_excluded(meta, check_country=True):
            updated_meta = replace_group_title(meta)
            output.append(updated_meta)
            output.append(url)
            seen_urls.add(url)
 
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print(f"Wrote {OUTPUT_FILE}")
 
 
if __name__ == "__main__":
    main()
 
