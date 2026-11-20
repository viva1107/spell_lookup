#!/usr/bin/env python3
import os
import sys
import asyncio
import re
import html
import json
import requests
import urllib.parse
import time
from datetime import datetime

# ↳ bump this when you cut a new release
__version__ = "1.5.1"
# ↳ raw URLs for version check and script update
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/Tyrallis/SpellLookup/main/VERSION.txt"
RAW_SCRIPT_URL     = "https://raw.githubusercontent.com/Tyrallis/SpellLookup/main/spell_lookup.py"

# The build string to use specifically for SpellChainEffect lookups
CHAIN_EFFECT_BUILD = "10.2.7.54717"

try:
    import aiohttp
except ImportError:
    print("Error: aiohttp module not found. Please install with `pip install aiohttp requests aiohttp`.", file=sys.stderr)
    sys.exit(1)

# ANSI true-color helper
def rgb(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"

# Basic ANSI
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"

# Class colors
CLASS_COLORS = {
    "Death Knight": rgb(196,  30,  58),
    "Demon Hunter": rgb(163,  48, 201),
    "Druid":        rgb(255, 124,  10),
    "Evoker":       rgb( 51, 147, 127),
    "Hunter":       rgb(170, 211, 114),
    "Mage":         rgb( 63, 199, 235),
    "Monk":         rgb(  0, 255, 152),
    "Paladin":      rgb(244, 140, 186),
    "Priest":       rgb(255, 255, 255),
    "Rogue":        rgb(255, 244, 104),
    "Shaman":       rgb(  0, 112, 221),
    "Warlock":      rgb(135, 136, 238),
    "Warrior":      rgb(198, 155, 109),
}

# Wowhead class ID → class name
CLASS_ID_MAP = {
    "1":"Warrior","2":"Paladin","3":"Hunter","4":"Rogue","5":"Priest",
    "6":"Death Knight","7":"Shaman","8":"Mage","9":"Warlock","10":"Monk",
    "11":"Druid","12":"Demon Hunter","13":"Evoker",
}

# Browser-like headers so Wowhead/wago.tools don't block us with 403
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DB2_BASE     = "https://wago.tools/db2"
FILES_BASE   = "https://wago.tools/files"
SEM          = None  # will be set per-search
TOTAL_STAGES = 7     # 0..6 for model, 7 for chain textures

# Shared state for multiple‐bar rendering
multi_labels = []         # list of spell_name per index
multi_progress = []       # list of current stage (0..7) per index
multi_done_event = None   # asyncio.Event to signal completion
BAR_WIDTH = 30

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    clear_screen()
    width = 60
    border = CYAN + "+" + "-"*(width-2) + "+" + RESET

    # line 1: byline + version
    content = f"Made by QQ:646638084 (v{__version__})"
    line1 = CYAN + "|" + RESET + content.center(width-2) + CYAN + "|" + RESET

    # line 2: timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line2 = CYAN + "|" + RESET + timestamp.center(width-2) + CYAN + "|" + RESET

    # line 3: update notice
    try:
        resp = requests.get(REMOTE_VERSION_URL, timeout=1)
        resp.raise_for_status()
        latest = resp.text.strip()
        upd = ""  # auto-update disabled in this fixed build
    except Exception:
        upd = ""
    line3 = CYAN + "|" + RESET + upd.center(width-2) + CYAN + "|" + RESET

    print(border)
    print(line1)
    print(line2)
    print(line3)
    print(border)
    print()

def prompt_update():
    """
    Auto-update DISABLED in this fixed build:
    upstream v1.5 exe was built from unpublished source; allowing the
    auto-updater to overwrite this file would restore the 403 bug.
    """
    return
    try:
        resp = requests.get(REMOTE_VERSION_URL, timeout=2)
        resp.raise_for_status()
        latest = resp.text.strip()
    except Exception:
        return

    if latest == __version__:
        return

    print(f"{RED}Update available!{RESET} You have {__version__}, latest is {latest}.")
    choice = input("Download and install now? [Y/n] ").strip().lower()
    if choice in ("", "y", "yes"):
        try:
            r2 = requests.get(RAW_SCRIPT_URL, timeout=5)
            r2.raise_for_status()
        except Exception as e:
            print(f"{RED}Failed to download update:{RESET} {e}")
            return

        script_path = os.path.realpath(__file__)
        try:
            with open(script_path, "wb") as f:
                f.write(r2.content)
        except Exception as e:
            print(f"{RED}Error writing update to disk:{RESET} {e}")
            return

        print(f"{GREEN}Updated to {latest}! Please re-run the script.{RESET}")
        sys.exit(0)
    else:
        print("Continuing with current version...\n")

def print_progress(stage: int, label: str):
    """
    Single‐bar smooth animation (used only for single‐ID calls).
    """
    bar_width = BAR_WIDTH
    target_pct = stage / TOTAL_STAGES
    current_pct = getattr(print_progress, "_current_pct", 0.0)

    steps = 20  # Number of frames for smooth animation
    for i in range(steps + 1):
        pct = current_pct + (target_pct - current_pct) * (i / steps)
        filled = int(bar_width * pct)
        empty = bar_width - filled
        bar = GREEN + "█" * filled + RESET + "░" * empty
        sys.stdout.write(f"\r{CYAN}{label.ljust(20)}{RESET} {bar} {pct*100:5.1f}%\033[K")
        sys.stdout.flush()
        time.sleep(0.01)

    # Save the latest value so the next animation starts from here
    print_progress._current_pct = target_pct

    if stage == TOTAL_STAGES:
        sys.stdout.write("\n")
        print_progress._current_pct = 0.0  # Reset for next lookup

def render_multi_bars():
    """
    Render all progress bars for spells in multi_labels/multi_progress.
    """
    lines = []
    for idx, label in enumerate(multi_labels):
        stage = multi_progress[idx]
        pct = stage / TOTAL_STAGES
        filled = int(BAR_WIDTH * pct)
        empty = BAR_WIDTH - filled
        bar = GREEN + "█" * filled + RESET + "░" * empty
        lines.append(f"{CYAN}{label.ljust(20)}{RESET} {bar} {pct*100:5.1f}%")
    return "\n".join(lines)

async def multi_bar_renderer():
    """
    Continuously update the multiple progress bars on screen until done.
    """
    while not multi_done_event.is_set():
        # Move cursor up by number of bars
        sys.stdout.write(f"\033[{len(multi_labels)}A")
        sys.stdout.write(render_multi_bars() + "\n")
        sys.stdout.flush()
        await asyncio.sleep(0.05)

    # Final update to 100%
    sys.stdout.write(f"\033[{len(multi_labels)}A")
    sys.stdout.write(render_multi_bars() + "\n")
    sys.stdout.flush()

async def _get_text(session: aiohttp.ClientSession, url: str, attempts: int=3) -> str:
    """
    GET with retries + backoff (wago.tools occasionally rate-limits).
    """
    last_exc = None
    for i in range(attempts):
        try:
            async with SEM:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    return await resp.text()
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                await asyncio.sleep(1.0 * (i + 1))
    raise last_exc

local_tables_used = set()

def _table_csv_path(table: str) -> str:
    new_path = os.path.join(DATA_DIR, f"{table}.csv")
    legacy = os.path.join(LISTFILE_DIR, f"{table}.csv")
    if not os.path.exists(new_path) and os.path.exists(legacy):
        try:
            os.replace(legacy, new_path)   # 自动迁移旧位置的文件
        except Exception:
            pass
    return new_path

def _download_table_csv(table: str) -> str:
    """One-time full-CSV download of a DB2 table from wago.tools."""
    path = _table_csv_path(table)
    if os.path.exists(path):
        return path
    url = f"{DB2_BASE}/{table}/csv"
    print(f"{CYAN}首次使用：下载数据表 {table}.csv（仅需一次）...{RESET}")
    try:
        with requests.get(url, stream=True, timeout=180,
                          headers=BROWSER_HEADERS) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0) or 0)
            got = 0
            with open(path + ".part", "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        print(f"\r{CYAN}{table} 下载中 {got * 100 // total}%{RESET}",
                              end="", flush=True)
        os.replace(path + ".part", path)
        with open(path, "rb") as chk:
            head = chk.read(4096)
        if head.lstrip().startswith(b"<"):
            os.remove(path)
            raise RuntimeError("下载内容是网页而非CSV（被反爬拦截）")
        print(f"\n{GREEN}{table}.csv 下载完成。{RESET}")
    except Exception as e:
        if os.path.exists(path + ".part"):
            os.remove(path + ".part")
        print(f"\n{RED}{table}.csv 下载失败：{e}{RESET}")
        raise
    return path

_local_result_cache = {}

def _local_db2_query(table: str, filters: dict):
    """
    Deterministic local query over the cached full-table CSV.
    Supports filter[Col]=exact:a,b,c (OR) — same style as the remote API.
    """
    import csv
    key = (table, tuple(sorted((k, str(v)) for k, v in filters.items())))
    if key in _local_result_cache:
        return _local_result_cache[key]
    path = _download_table_csv(table)
    conds = []
    for k, v in filters.items():
        m = re.match(r"filter\[(.+?)\]$", str(k))
        if not m:
            continue
        raw = str(v)
        if raw.startswith("exact:"):
            raw = raw[len("exact:"):]
        conds.append((m.group(1), set(raw.split(","))))
    out = []
    with open(path, "rb") as chk:
        if chk.read(64).lstrip().startswith(b"<"):
            print(f"{RED}[诊断] {table}.csv 实际是网页内容（下载被拦截）。"
                  f"请删除该 csv 后重试，或手动下载真 CSV 替换。{RESET}")
            return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        sample = f.read(8192)
        f.seek(0)
        delim = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            delim = dialect.delimiter
        except Exception:
            if sample.count(";") > sample.count(","):
                delim = ";"
        reader = csv.reader(f, delimiter=delim)
        header = next(reader, None)
        if not header:
            print(f"{RED}[诊断] {table}.csv 为空或没有表头。{RESET}")
            return []
        missing_cols = [c for c, _ in conds if c not in header]
        if missing_cols:
            first_line = sample.splitlines()[0][:300] if sample.splitlines() else "(空文件)"
            print(f"{RED}[诊断] {table}.csv 中找不到列 {missing_cols}{RESET}")
            print(f"{RED}[诊断] 分隔符={delim!r} 列数={len(header)} 文件首行: {first_line}{RESET}")
            return []
        idx = {c: header.index(c) for c, _ in conds}
        _rowcount = 0
        for row in reader:
            _rowcount += 1
            ok = True
            for c, vals in conds:
                i = idx[c]
                if i < 0 or i >= len(row) or row[i] not in vals:
                    ok = False
                    break
            if ok:
                out.append(dict(zip(header, row)))
    if table not in local_tables_used:
        local_tables_used.add(table)
        print(f"{CYAN}[本地表] {table} -> 匹配 {len(out)} 行 / 全表 {_rowcount} 行{RESET}")
    _local_result_cache[key] = out
    return out

async def fetch_db2(session: aiohttp.ClientSession, table: str, filters: dict, use_chain_build: bool=False):
    """
    Dual-path DB2 query:
      1) remote wago.tools page (fast when it works)
      2) local full-table CSV fallback (deterministic; auto-downloaded once)
    """
    # 1) remote
    try:
        rows = await _fetch_db2_remote(session, table, filters, use_chain_build)
        if rows:
            # 校验：新站可能忽略 filter 直接返回第一页，必须逐行核实匹配
            for k, v in filters.items():
                m = re.match(r"filter\[(.+?)\]$", str(k))
                if not m or not str(v).startswith("exact:"):
                    continue
                col = m.group(1)
                vals = set(str(x) for x in str(v)[len("exact:"):].split(","))
                rows = [r for r in rows if str(r.get(col, "")) in vals]
            if rows:
                return rows
    except Exception:
        pass
    # 2) local CSV
    try:
        return await asyncio.to_thread(_local_db2_query, table, filters)
    except Exception as e:
        print(f"{RED}本地表 {table} 查询失败：{e}{RESET}")
        return []

async def _fetch_db2_remote(session: aiohttp.ClientSession, table: str, filters: dict, use_chain_build: bool=False):
    """
    Fetch data from wago.tools/db2 for the given table and filters.
    If use_chain_build=True, always include build=CHAIN_EFFECT_BUILD in the query string.
    """
    if use_chain_build:
        filters["build"] = CHAIN_EFFECT_BUILD

    qs = urllib.parse.urlencode(filters)
    url = f"{DB2_BASE}/{table}?{qs}"
    text = await _get_text(session, url)

    m = re.search(r'<div[^>]+data-page=(?:["\'])(.*?)(?:["\'])', text, re.DOTALL)
    if not m:
        return []
    blob = html.unescape(m.group(1))
    page = json.loads(blob)
    return page.get("props", {}).get("data", {}).get("data", []) or []

async def fetch_spell_ids_by_name(session: aiohttp.ClientSession, name: str):
    rows = await fetch_db2(session, "SpellName", {
        "filter[Name_lang]": f"exact:{name}",
        "page": "1"
    })
    return [r["ID"] for r in rows if "ID" in r]

LISTFILE_URL = "https://github.com/wowdev/wow-listfile/releases/latest/download/community-listfile.csv"
# PyInstaller onefile: __file__ 指向临时 _MEI 目录（退出即删），
# 必须用 sys.executable 所在目录，数据文件才能持久保存并找到用户的 listfile.csv
if getattr(sys, "frozen", False):
    LISTFILE_DIR = os.path.dirname(sys.executable)
else:
    LISTFILE_DIR = os.path.dirname(os.path.abspath(__file__))

# 所有自动下载的数据统一放 data 子目录，方便整体清理
DATA_DIR = os.path.join(LISTFILE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
LISTFILE_CSV = os.path.join(LISTFILE_DIR, "community-listfile.csv")
LISTFILE_IDX = os.path.join(DATA_DIR, "community-listfile.idx")

def _listfile_csv_path() -> str:
    """Accept both 'community-listfile.csv' and legacy 'listfile.csv'."""
    legacy = os.path.join(LISTFILE_DIR, "listfile.csv")
    if os.path.exists(LISTFILE_CSV):
        return LISTFILE_CSV
    if os.path.exists(legacy):
        return legacy
    return LISTFILE_CSV

def _download_listfile() -> None:
    """One-time download of the community listfile (fdid -> path)."""
    if os.path.exists(_listfile_csv_path()):
        return
    print(f"{CYAN}首次使用：下载文件名数据库（约150MB，仅一次）...{RESET}")
    try:
        with requests.get(LISTFILE_URL, stream=True, timeout=60,
                          headers=BROWSER_HEADERS) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0) or 0)
            got = 0
            with open(_listfile_csv_path() + ".part", "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        print(f"\r{CYAN}下载中 {got * 100 // total}%{RESET}",
                              end="", flush=True)
        os.replace(_listfile_csv_path() + ".part", _listfile_csv_path())
        print(f"\n{GREEN}文件名数据库下载完成。{RESET}")
    except Exception as e:
        if os.path.exists(_listfile_csv_path() + ".part"):
            os.remove(_listfile_csv_path() + ".part")
        print(f"\n{RED}文件名数据库下载失败：{e}{RESET}")
        print(f"{YELLOW}可手动下载后放到程序目录：{LISTFILE_URL}{RESET}")
        raise

def _load_listfile_pairs():
    """fdid -> file-offset pairs, built once, cached as .idx."""
    import struct
    _idx_legacy = os.path.join(LISTFILE_DIR, "community-listfile.idx")
    if not os.path.exists(LISTFILE_IDX) and os.path.exists(_idx_legacy):
        try:
            os.replace(_idx_legacy, LISTFILE_IDX)
        except Exception:
            pass
    if not os.path.exists(LISTFILE_IDX):
        _download_listfile()
        print(f"{CYAN}建立文件名索引（约10秒，仅一次）...{RESET}")
        pairs = []
        with open(_listfile_csv_path(), "rb") as f:
            offset = 0
            for line in f:
                semi = line.find(b";")
                if semi > 0:
                    try:
                        pairs.append((int(line[:semi]), offset))
                    except ValueError:
                        pass  # header line
                offset += len(line)
        pairs.sort()
        with open(LISTFILE_IDX, "wb") as f:
            for fdid, off in pairs:
                f.write(struct.pack("<IQ", fdid, off))
    else:
        data = open(LISTFILE_IDX, "rb").read()
        pairs = [struct.unpack_from("<IQ", data, i)
                 for i in range(0, len(data), 12)]
    return pairs

def _listfile_lookup(fdids):
    """Local fdid -> [path] lookup against the community listfile."""
    import bisect
    fdids = {int(x) for x in fdids if x}
    if not fdids:
        return {}
    try:
        pairs = _load_listfile_pairs()
    except Exception:
        return {}
    keys = [p[0] for p in pairs]
    out = {}
    with open(_listfile_csv_path(), "rb") as f:
        for fdid in fdids:
            i = bisect.bisect_left(keys, fdid)
            if i < len(pairs) and pairs[i][0] == fdid:
                f.seek(pairs[i][1])
                line = f.readline().decode("utf-8", errors="replace")
                parts = line.split(";")
                if len(parts) >= 2 and parts[0].strip().lstrip("-").isdigit():
                    out[fdid] = [parts[1].strip()]
    return out

def print_wowhead_link(spell_id: int, spell_name: str):
    url = f"https://www.wowhead.com/spell={spell_id}"
    link = f"\033]8;;{url}\033\\{spell_name}\033]8;;\033\\"
    print(f"\n{YELLOW}Wowhead:{RESET} {link}\n")

def fetch_spell_class_wowhead(spell_id: int) -> str:
    """
    Best-effort spell-class lookup from the Wowhead page.
    Wowhead may 403/Cloudflare-block us; class is cosmetic, so on
    any failure degrade to 'Unknown' instead of crashing.
    """
    url = f"https://www.wowhead.com/spell={spell_id}"
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        resp.raise_for_status()
        text = resp.text
    except requests.RequestException:
        return "Unknown"
    m = re.search(r"\[class=(\d+)\]", text)
    return CLASS_ID_MAP.get(m.group(1), "Unknown") if m else "Unknown"

async def fetch_files(session: aiohttp.ClientSession, search_id: int):
    """
    Resolve an ID to filename(s). Tries several strategies:
      1) classic Inertia data-page JSON on the wago files page
      2) loose regex over raw HTML (structure drift)
      3) local community listfile (fdid -> path), auto-downloaded once
      4) ModelFileDataID -> FileDataID mapping, then listfile again
    """
    try:
        search_id = int(search_id)
    except (TypeError, ValueError):
        return []
    url = f"{FILES_BASE}?search={search_id}"
    try:
        text = await _get_text(session, url)
    except Exception:
        text = ""

    # Strategy 1: classic Inertia data-page JSON
    m = re.search(r'<div[^>]+data-page=(?:["\'])(.*?)(?:["\'])', text, re.DOTALL)
    if m:
        try:
            page = json.loads(html.unescape(m.group(1)))
        except Exception:
            page = None
        if page:
            files = page.get("props", {}).get("files", {})
            if isinstance(files, dict):
                data = files.get("data", []) or []
            elif isinstance(files, list):
                data = files
            else:
                data = []
            out = [e.get("filename") for e in data
                   if str(e.get("fdid")) == str(search_id) and e.get("filename")]
            if out:
                return sorted(set(out))

    # Strategy 2: loose regex over raw HTML
    for pat in (
        r'"fdid"\s*:\s*%d\s*,\s*"filename"\s*:\s*"([^"]+)"' % search_id,
        r'"filename"\s*:\s*"([^"]+)"\s*,\s*"fdid"\s*:\s*%d\b' % search_id,
    ):
        found = re.findall(pat, text)
        if found:
            return sorted(set(found))

    # Strategy 3: local community listfile (id treated as FileDataID)
    hits = await asyncio.to_thread(_listfile_lookup, {search_id})
    if hits.get(search_id):
        return hits[search_id]

    # Strategy 4: id may be a ModelFileDataID -> map to FileDataID -> listfile
    try:
        rows = await fetch_db2(session, "ModelFileData",
                               {"filter[ID]": f"exact:{search_id}", "page": "1"})
    except Exception:
        rows = []
    fdids = [r.get("FileDataID") for r in rows if r.get("FileDataID")]
    if fdids:
        hits = await asyncio.to_thread(_listfile_lookup, set(fdids))
        out = []
        for fd in fdids:
            out.extend(hits.get(fd, []))
        if out:
            return sorted(set(out))
    return []

async def lookup_chain_effect_textures(session: aiohttp.ClientSession, visual_ids: set):
    chain_texture_files = []

    # 1) SpellVisualEvent → find entries with TargetType == 4, collect their SpellVisualKitID
    kit_ids = set()
    for vid in visual_ids:
        sv_events = await fetch_db2(
            session,
            "SpellVisualEvent",
            {"filter[SpellVisualID]": f"exact:{vid}", "page": "1"},
            use_chain_build=True
        )
        for ev in sv_events:
            if ev.get("TargetType") == 4:
                kit_ids.add(ev.get("SpellVisualKitID", 0))

    # 2) SpellVisualKitEffect → filter by EffectType == 1 (SpellProceduralEffectID), collect "Effect" (proc IDs)
    proc_ids = set()
    for kid in kit_ids:
        sv_ke = await fetch_db2(
            session,
            "SpellVisualKitEffect",
            {
                "filter[ParentSpellVisualKitID]": f"exact:{kid}",
                "filter[EffectType]": "exact:1",
                "page": "1"
            },
            use_chain_build=True
        )
        for row in sv_ke:
            pid = row.get("Effect")
            if pid:
                proc_ids.add(pid)

    # 3) SpellProceduralEffect → for each proc ID, get Value_0 (chain effect ID)
    chain_ids = set()
    for pid in proc_ids:
        proc_rows = await fetch_db2(
            session,
            "SpellProceduralEffect",
            {"filter[ID]": f"exact:{pid}", "page": "1"},
            use_chain_build=True
        )
        for prow in proc_rows:
            v0 = prow.get("Value_0")
            if v0:
                chain_ids.add(v0)

    # 4) SpellChainEffects → collect TextureFileDataID_0/1/2
    texture_ids = set()
    for cid in chain_ids:
        chains = await fetch_db2(
            session,
            "SpellChainEffects",
            {"filter[ID]": f"exact:{cid}", "page": "1"},
            use_chain_build=True
        )
        for crow in chains:
            for key in ("TextureFileDataID_0", "TextureFileDataID_1", "TextureFileDataID_2"):
                tid = crow.get(key)
                if tid:
                    texture_ids.add(tid)

    # 5) fetch_files for each texture FileDataID
    for tid in texture_ids:
        files = await fetch_files(session, tid)
        if files:
            chain_texture_files.extend(files)

    return sorted(set(chain_texture_files))

# ──────────────────────────────────────────────────────────────────────────────

async def process_spell_single(session: aiohttp.ClientSession, spell_id: int):
    """
    Original single-ID pipeline ( prints progress via print_progress, then outputs results).
    """
    # SpellName lookup
    spell_rows = await fetch_db2(
        session,
        "SpellName",
        {"filter[ID]": f"exact:{spell_id}", "page": "1"}
    )
    spell_name = str(spell_id)
    if spell_rows:
        for k, v in spell_rows[0].items():
            if "name" in k.lower():
                spell_name = v
                break

    spell_class   = fetch_spell_class_wowhead(spell_id)
    color         = CLASS_COLORS.get(spell_class, "")
    colored_class = f"{color}{spell_class}{RESET}"

    # Stage 0: initial progress
    print_progress(0, spell_name)

    # Stage 1: SpellXSpellVisual → SpellVisualID(s)
    visuals = await fetch_db2(
        session,
        "SpellXSpellVisual",
        {"filter[SpellID]": f"exact:{spell_id}", "page": "1"}
    )
    visual_ids = {r.get("SpellVisualID") for r in visuals}
    print_progress(1, "SpellVisualIDs")

    # Stage 2: SpellVisualEvent → collect SpellVisualKitIDs
    rows2 = await asyncio.gather(*[
        fetch_db2(session, "SpellVisualEvent", {"filter[SpellVisualID]": f"exact:{vid}", "page": "1"})
        for vid in visual_ids
    ])
    kit_ids = {r.get("SpellVisualKitID") for sub in rows2 for r in sub}
    print_progress(2, "SpellVisualKitIDs")

    # Stage 3: SpellVisualKitEffect (Type=2) → collect ModelAttachIDs
    rows3 = await asyncio.gather(*[
        fetch_db2(
            session,
            "SpellVisualKitEffect",
            {
                "filter[ParentSpellVisualKitID]": f"exact:{kid}",
                "filter[EffectType]": "exact:2",
                "page": "1"
            }
        )
        for kid in kit_ids
    ])
    attach_ids = {r.get("Effect") for sub in rows3 for r in sub}
    print_progress(3, "ModelAttachIDs")

    # Stage 4: SpellVisualKitModelAttach → SpellVisualEffectNameID(s)
    rows4 = await asyncio.gather(*[
        fetch_db2(session, "spellvisualkitmodelattach", {"filter[ID]": f"exact:{aid}", "page": "1"})
        for aid in attach_ids
    ])
    name_ids = {r.get("SpellVisualEffectNameID") for sub in rows4 for r in sub}
    print_progress(4, "EffectNameIDs")

    # Stage 5: SpellVisualEffectName → ModelFileDataID(s)
    rows5 = await asyncio.gather(*[
        fetch_db2(session, "SpellVisualEffectName", {"filter[ID]": f"exact:{nid}", "page": "1"})
        for nid in name_ids
    ])
    data_ids = {r.get("ModelFileDataID") for sub in rows5 for r in sub}
    print_progress(5, "ModelFileDataIDs")

    # Stage 6: ModelFileData → .m2 filenames
    if data_ids:
        resolved_lists = await asyncio.gather(
            *[fetch_files(session, did) for did in data_ids])
        resolved_map = dict(zip(data_ids, resolved_lists))
    else:
        resolved_map = {}
    filenames = sorted({f for fs in resolved_map.values() for f in fs})
    print_progress(6, "Filenames")
    if not visual_ids:
        print(f"{YELLOW}[提示] 该法术在 SpellXSpellVisual 中没有记录——{RESET}")
        print(f"{YELLOW}[提示] 通常是纯光环/服务器端法术，没有独立模型文件。{RESET}")
        print(f"{YELLOW}[提示] 输入 133（火球术）可验证工具本身是否正常。{RESET}")
    print(f"{CYAN}[trace] {spell_name} ({spell_id}): visuals={len(visual_ids)} "
          f"kits={len(kit_ids)} kitModels={len(attach_ids)} "
          f"effectNames={len(name_ids)} modelIDs={len(data_ids)} "
          f"files={len(filenames)}{RESET}")

    if filenames:
        print(f"\n{YELLOW}Found files for {spell_name} [{colored_class}]{RESET}")
        for f in filenames:
            print(f"{GREEN}- {f}{RESET}")
    else:
        print(f"\n{RED}No model (.m2) files found for {spell_name} [{colored_class}]{RESET}")

    # Stage 7: SpellChainEffect textures
    print_progress(7, "ChainTextures")
    chain_files = await lookup_chain_effect_textures(session, visual_ids)
    if chain_files:
        print(f"\n{YELLOW}Found ChainEffect textures for {spell_name} [{colored_class}]{RESET}")
        for cf in chain_files:
            print(f"{GREEN}- {cf}{RESET}")
    else:
        print(f"\n{YELLOW}No ChainEffect textures found for {spell_name} [{colored_class}]{RESET}")

    print_wowhead_link(spell_id, spell_name)
    print()

async def process_spell_indexed(session: aiohttp.ClientSession, spell_id: int, idx: int, result_m2: set, result_chain: set):
    """
    Exactly the same pipeline as before, but updates multi_progress[idx]
    and fills result_m2/result_chain sets instead of printing immediately.
    """
    # SpellName lookup
    spell_rows = await fetch_db2(
        session,
        "SpellName",
        {"filter[ID]": f"exact:{spell_id}", "page": "1"}
    )
    spell_name = str(spell_id)
    if spell_rows:
        for k, v in spell_rows[0].items():
            if "name" in k.lower():
                spell_name = v
                break

    # Stage 0
    multi_progress[idx] = 0

    # Stage 1: SpellXSpellVisual → SpellVisualID(s)
    visuals = await fetch_db2(
        session,
        "SpellXSpellVisual",
        {"filter[SpellID]": f"exact:{spell_id}", "page": "1"}
    )
    visual_ids = {r.get("SpellVisualID") for r in visuals}
    multi_progress[idx] = 1

    # Stage 2: SpellVisualEvent → collect SpellVisualKitIDs
    rows2 = await asyncio.gather(*[
        fetch_db2(session, "SpellVisualEvent", {"filter[SpellVisualID]": f"exact:{vid}", "page": "1"})
        for vid in visual_ids
    ])
    kit_ids = {r.get("SpellVisualKitID") for sub in rows2 for r in sub}
    multi_progress[idx] = 2

    # Stage 3: SpellVisualKitEffect (Type=2) → collect ModelAttachIDs
    rows3 = await asyncio.gather(*[
        fetch_db2(
            session,
            "SpellVisualKitEffect",
            {
                "filter[ParentSpellVisualKitID]": f"exact:{kid}",
                "filter[EffectType]": "exact:2",
                "page": "1"
            }
        )
        for kid in kit_ids
    ])
    attach_ids = {r.get("Effect") for sub in rows3 for r in sub}
    multi_progress[idx] = 3

    # Stage 4: SpellVisualKitModelAttach → SpellVisualEffectNameID(s)
    rows4 = await asyncio.gather(*[
        fetch_db2(session, "spellvisualkitmodelattach", {"filter[ID]": f"exact:{aid}", "page": "1"})
        for aid in attach_ids
    ])
    name_ids = {r.get("SpellVisualEffectNameID") for sub in rows4 for r in sub}
    multi_progress[idx] = 4

    # Stage 5: SpellVisualEffectName → ModelFileDataID(s)
    rows5 = await asyncio.gather(*[
        fetch_db2(session, "SpellVisualEffectName", {"filter[ID]": f"exact:{nid}", "page": "1"})
        for nid in name_ids
    ])
    data_ids = {r.get("ModelFileDataID") for sub in rows5 for r in sub}
    multi_progress[idx] = 5

    # Stage 6: ModelFileData → .m2 filenames
    for did in data_ids:
        m2s = await fetch_files(session, did)
        for m2 in m2s:
            result_m2.add(m2)
    multi_progress[idx] = 6

    # Stage 7: SpellChainEffect textures
    chain_files = await lookup_chain_effect_textures(session, visual_ids)
    for cf in chain_files:
        result_chain.add(cf)
    multi_progress[idx] = 7


# ──────────────────────────────────────────────────────────────────────────────
# ADDITION: NPC model lookup ('npc <DisplayID>' / 'npcid <NPCID>')
# ──────────────────────────────────────────────────────────────────────────────

async def process_npc_display(session: aiohttp.ClientSession, display_id: int, creature_name: str=""):
    """
    Given a CreatureDisplayInfo ID, find its model (.m2) and skin textures.
    """
    rows = await fetch_db2(
        session,
        "CreatureDisplayInfo",
        {"filter[ID]": f"exact:{display_id}", "page": "1"}
    )
    if not rows:
        print(f"{YELLOW}No CreatureDisplayInfo found for DisplayID {display_id}.{RESET}")
        return
    row = rows[0]

    label = f"{creature_name} " if creature_name else ""
    print(f"{CYAN}DisplayID {display_id}{RESET}  ({label}CreatureDisplayInfo)".rstrip())

    # 1) ModelID → CreatureModelData → FileDataID → .m2 filename
    model_id = row.get("ModelID") or row.get("CreatureModelDataID")
    m2_files = []
    if model_id:
        mrows = await fetch_db2(
            session,
            "CreatureModelData",
            {"filter[ID]": f"exact:{model_id}", "page": "1"}
        )
        for mr in mrows:
            fdid = mr.get("FileDataID")
            if fdid:
                m2_files.extend(await fetch_files(session, fdid))
    m2_files = sorted(set(m2_files))
    print(f"{CYAN}[trace] npc display={display_id} modelID={model_id} "
          f"m2={len(m2_files)}{RESET}")
    if m2_files:
        print(f"{YELLOW}Model files for DisplayID {display_id}:{RESET}")
        for f in m2_files:
            print(f"{GREEN}- {f}{RESET}")
    else:
        print(f"{RED}No model (.m2) files found for DisplayID {display_id}{RESET}")

    # 2) TextureVariationFileDataID_0/1/2 + PortraitTextureFileDataID → .blp
    tex_fdids = set()
    for k, v in row.items():
        if k.lower().startswith("texturevariationfiledataid") and v:
            tex_fdids.add(v)
        elif k == "PortraitTextureFileDataID" and v:
            tex_fdids.add(v)
    tex_files = []
    for tid in sorted(tex_fdids):
        tex_files.extend(await fetch_files(session, tid))
    tex_files = sorted(set(tex_files))
    print(f"{CYAN}[trace] npc display={display_id} texFDIDs={len(tex_fdids)} "
          f"tex={len(tex_files)}{RESET}")
    if tex_files:
        print(f"{YELLOW}Textures for DisplayID {display_id}:{RESET}")
        for f in tex_files:
            print(f"{GREEN}- {f}{RESET}")
    else:
        print(f"{YELLOW}No textures found for DisplayID {display_id}{RESET}")

async def process_npc_by_creature(session: aiohttp.ClientSession, creature_id: int):
    """
    Given a Creature (NPC) ID, resolve its name and up to 4 display IDs,
    then run the display pipeline for each.
    """
    rows = await fetch_db2(
        session,
        "Creature",
        {"filter[ID]": f"exact:{creature_id}", "page": "1"}
    )
    if not rows:
        print(f"{YELLOW}No creature found with NPCID {creature_id}.{RESET}")
        return
    row = rows[0]
    name = row.get("Name_lang") or str(creature_id)

    display_ids = []
    for k in sorted(row.keys()):
        if k.lower().startswith("displayid"):
            try:
                v = int(row.get(k))
            except (TypeError, ValueError):
                continue
            if v > 0 and v not in display_ids:
                display_ids.append(v)

    if not display_ids:
        print(f"{YELLOW}Creature \"{name}\" ({creature_id}) has no display IDs.{RESET}")
        return

    print(f"{CYAN}NPC {name} ({creature_id}){RESET} -> DisplayIDs: {', '.join(map(str, display_ids))}")
    for did in display_ids:
        print()
        await process_npc_display(session, did, name)

    url = f"https://www.wowhead.com/npc={creature_id}"
    link = f"\033]8;;{url}\033\\{name}\033]8;;\033\\"
    print(f"\n{YELLOW}Wowhead:{RESET} {link}")
    print()

async def search_and_process(name_or_id: str):
    global SEM

    # Create a new semaphore for this run, bound to the current event loop
    SEM = asyncio.Semaphore(16)

    async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as session:
        # NPC modes: 'npc <DisplayID>' or 'npcid <NPCID>'
        low = name_or_id.lower()
        if low.startswith("npc ") and name_or_id[4:].strip().isdigit():
            await process_npc_display(session, int(name_or_id[4:].strip()))
            return
        if low.startswith("npcid ") and name_or_id[6:].strip().isdigit():
            await process_npc_by_creature(session, int(name_or_id[6:].strip()))
            return

        # If user typed digits, treat as a single SpellID:
        if name_or_id.isdigit():
            await process_spell_single(session, int(name_or_id))
            return

        # Otherwise, look up all SpellIDs matching that exact name:
        ids = await fetch_spell_ids_by_name(session, name_or_id)
        if not ids:
            print(f"{YELLOW}No spells found matching \"{name_or_id}\".{RESET}")
            return

        # Fetch spell names for each ID, to label bars:
        names = []
        for sid in ids:
            rows = await fetch_db2(session, "SpellName", {"filter[ID]": f"exact:{sid}", "page": "1"})
            if rows:
                for k, v in rows[0].items():
                    if "name" in k.lower():
                        names.append(v)
                        break
                else:
                    names.append(str(sid))
            else:
                names.append(str(sid))

        # Prepare shared state
        global multi_labels, multi_progress, multi_done_event
        multi_labels = names.copy()
        multi_progress = [0] * len(ids)
        multi_done_event = asyncio.Event()

        # Print placeholders for each bar (one per ID)
        for label in multi_labels:
            bar = " " * BAR_WIDTH
            print(f"{CYAN}{label.ljust(20)}{RESET} [{bar}]   0.0%")

        # Start the multi‐bar renderer
        renderer_task = asyncio.create_task(multi_bar_renderer())

        # Prepare aggregate result sets
        aggregate_m2 = set()
        aggregate_chain = set()

        # Launch one task per ID
        tasks = []
        for idx, sid in enumerate(ids):
            tasks.append(
                asyncio.create_task(
                    process_spell_indexed(session, sid, idx, aggregate_m2, aggregate_chain)
                )
            )

        # Wait until all ID‐tasks finish
        await asyncio.gather(*tasks)

        # Signal renderer to do a final update, then exit
        multi_done_event.set()
        await renderer_task

        # After that, print de‐duplicated results:
        if aggregate_m2:
            print(f"\n{YELLOW}Found files for \"{name_or_id}\" (all IDs combined):{RESET}")
            for f in sorted(aggregate_m2):
                print(f"{GREEN}- {f}{RESET}")
        else:
            print(f"\n{RED}No model (.m2) files found for \"{name_or_id}\"{RESET}")

        if aggregate_chain:
            print(f"\n{YELLOW}Found ChainEffect textures for \"{name_or_id}\" (all IDs combined):{RESET}")
            for cf in sorted(aggregate_chain):
                print(f"{GREEN}- {cf}{RESET}")
        else:
            print(f"\n{YELLOW}No ChainEffect textures found for \"{name_or_id}\"{RESET}")

        # Finally, print a Wowhead link using the first ID:
        first_id = ids[0]
        print_wowhead_link(first_id, name_or_id)
        print()

def interactive_loop():
    while True:
        print_banner()
        prompt_update()
        inp = input("Enter a SpellID or exact spell name: ").strip()
        if not inp:
            continue
        try:
            asyncio.run(search_and_process(inp))
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Cancelled.{RESET}")
        except Exception as e:
            print(f"{RED}Lookup failed:{RESET} {type(e).__name__}: {e}")
            print(f"{YELLOW}(网络请求被目标网站拒绝或超时，可稍后重试){RESET}")
        input("Press Enter for new search")

if __name__ == "__main__":
    try:
        interactive_loop()
    except KeyboardInterrupt:
        pass
    finally:
        input("\nPress Enter to exit...")
