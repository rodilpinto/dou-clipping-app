"""
build_training_data.py — Build training data from DOU email history.

Parses historical DOU clipping emails, queries the INLABS API for the same
dates, and matches publications to produce labelled training data (selected
vs. rejected) for future ML-based filtering.

Modules consolidated here:
  - Email parsers (Tier 1 clean HTML, Tier 2 Word/Outlook HTML)
  - Date inference from filenames
  - URL/title normalization and matching
  - JSON output and reporting
  - CLI orchestration (argparse + main loop)
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import TypedDict

from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Ensure dou_clipping.py (same directory) is importable regardless of cwd
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_EMAILS_DIR = os.path.join(os.path.dirname(__file__), "..", "Ro-dou", "emails de saída")
DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "training")


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

class ArticleRecord(TypedDict):
    url: str | None
    title: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Month name mapping (Portuguese) for multi-date pattern
MONTH_NAMES = {
    "janeiro": "01",
    "fevereiro": "02",
    "marco": "03",
    "março": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}

# Regex patterns for DOU publication types typically found in Tier 2 emails
# when no in.gov.br links are present.
_TITLE_PATTERNS = re.compile(
    r"(?:^|\b)("
    r"PORTARIA\b[^\n]{0,120}"
    r"|RESOLU[CÇ][AÃ]O\b[^\n]{0,120}"
    r"|DECRETO\b[^\n]{0,120}"
    r"|LEI\s+N[^\n]{0,120}"
    r"|EDITAL\b[^\n]{0,120}"
    r"|AVISO\s+DE\s+LICITA[CÇ][AÃ]O[^\n]{0,120}"
    r"|EXTRATO\b[^\n]{0,120}"
    r"|PREG[AÃ]O\b[^\n]{0,120}"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

def detect_encoding(filepath: str | Path) -> str:
    """Detect the character encoding of an HTML file.

    Reads the first 2000 bytes and looks for a ``charset=`` declaration
    inside a ``<meta>`` tag.  Falls back to UTF-8, then windows-1252.
    """
    raw = Path(filepath).read_bytes()[:2000]
    # Look for charset in meta tag (handles both quoted and unquoted values)
    match = re.search(rb'charset=(["\']?)([a-zA-Z0-9_-]+)\1', raw, re.IGNORECASE)
    if match:
        return match.group(2).decode("ascii").lower()

    # Fallback: try decoding with utf-8 first
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "windows-1252"


# ---------------------------------------------------------------------------
# Tier detection
# ---------------------------------------------------------------------------

def detect_email_tier(filepath: str | Path) -> int:
    """Return 1 for clean HTML (our script) or 2 for Word/Outlook HTML.

    Raises ``ValueError`` if the file matches neither known format.
    """
    raw = Path(filepath).read_bytes()[:2000]
    header = raw.decode("ascii", errors="ignore").lower()

    if 'urn:schemas-microsoft-com:office:word' in header:
        return 2

    # Tier 1: clean HTML from our script — meta charset in the header
    if '<meta charset="utf-8">' in header:
        return 1

    raise ValueError(
        f"Cannot determine email tier for '{filepath}': "
        "file matches neither Tier 1 (clean HTML) nor Tier 2 (Word/Outlook)."
    )


# ---------------------------------------------------------------------------
# Tier 1 parser (clean HTML from our Ro-dou script)
# ---------------------------------------------------------------------------

def parse_email_clean(filepath: str | Path) -> list[ArticleRecord]:
    """Parse a Tier 1 (clean HTML) email and return article records.

    Each record contains the DOU article URL (in.gov.br) and its title
    extracted from the ``<b>`` tag inside the ``<a>`` element.
    """
    text = Path(filepath).read_text(encoding="utf-8")
    soup = BeautifulSoup(text, "html.parser")

    results: list[ArticleRecord] = []
    for anchor in soup.find_all("a", href=True):
        href: str = anchor["href"]
        if "in.gov.br" not in href:
            continue

        # Title lives inside a <b> tag; fall back to the link text itself
        bold = anchor.find("b")
        title = bold.get_text(strip=True) if bold else anchor.get_text(strip=True)
        if not title:
            continue

        results.append(ArticleRecord(url=href, title=title))

    return results


# ---------------------------------------------------------------------------
# Tier 2 parser (Word/Outlook HTML)
# ---------------------------------------------------------------------------

def parse_email_word(filepath: str | Path) -> list[ArticleRecord]:
    """Parse a Tier 2 (Word/Outlook) email and return article records.

    If in.gov.br links are present, extracts URL + title from each link.
    Otherwise, falls back to regex extraction of DOU publication-type titles.
    """
    encoding = detect_encoding(filepath)
    text = Path(filepath).read_text(encoding=encoding, errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    # --- Strategy A: extract from in.gov.br links ---
    results: list[ArticleRecord] = []
    seen_urls: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href: str = anchor["href"]
        if "in.gov.br" not in href:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)

        title = anchor.get_text(" ", strip=True)
        # Word HTML often splits titles across lines; normalize whitespace
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        results.append(ArticleRecord(url=href, title=title))

    if results:
        return results

    # --- Strategy B: regex fallback for text-only titles ---
    body = soup.find("body")
    visible_text = body.get_text("\n", strip=True) if body else soup.get_text("\n", strip=True)

    seen_titles: set[str] = set()
    for match in _TITLE_PATTERNS.finditer(visible_text):
        title = match.group(1).strip()
        title = re.sub(r"\s+", " ", title).strip()
        if title and title not in seen_titles:
            seen_titles.add(title)
            results.append(ArticleRecord(url=None, title=title))

    return results


# ---------------------------------------------------------------------------
# Date inference
# ---------------------------------------------------------------------------

def infer_date(filename: str) -> str:
    """Infer the publication date from a DOU email filename.

    Supports patterns:
      - DOU_DDMMYYYY / DOU DDMMYYYY  (8 digits)
      - DOU DDMMYY                    (6 digits)
      - DOU de D(D)MMYYYY             (7 or 8 digits after 'de ')
      - DOU de DD a DD de <month> de YYYY  (multi-date range)

    Returns:
        Date string in DD/MM/YYYY format.

    Raises:
        ValueError: If the filename cannot be parsed.
    """
    name = os.path.basename(filename)
    name = re.sub(r"\.htm[l]?$", "", name, flags=re.IGNORECASE)

    # Pattern 4: Multi-date range — "DOU de 18 a 20 de fevereiro de 2026"
    multi = re.match(
        r"DOU\s+de\s+(\d{1,2})\s+a\s+\d{1,2}\s+de\s+(\w+)\s+de\s+(\d{4})",
        name,
        re.IGNORECASE,
    )
    if multi:
        day = multi.group(1).zfill(2)
        month_name = multi.group(2).lower()
        year = multi.group(3)
        month = MONTH_NAMES.get(month_name)
        if month is None:
            raise ValueError(f"Unknown month name: {month_name}")
        return f"{day}/{month}/{year}"

    # Pattern 3: "DOU de <digits>" where digits encode D/DD + M/MM + YYYY
    de_match = re.match(r"DOU\s+de\s+(\d{6,8})$", name, re.IGNORECASE)
    if de_match:
        digits = de_match.group(1)
        year = digits[-4:]
        rest = digits[:-4]
        if len(rest) == 2:
            day = "0" + rest[0]
            month = "0" + rest[1]
        elif len(rest) == 3:
            day = rest[0:2]
            month = "0" + rest[2]
        elif len(rest) == 4:
            day = rest[0:2]
            month = rest[2:4]
        else:
            raise ValueError(f"Cannot parse date from filename: {filename}")
        return f"{day}/{month}/{year}"

    # Pattern 1 & 2: "DOU_DDMMYYYY", "DOU DDMMYYYY", "DOU DDMMYY"
    simple = re.match(r"DOU[_ ]+(\d{6,8})$", name, re.IGNORECASE)
    if simple:
        digits = simple.group(1)
        if len(digits) == 8:
            day = digits[0:2]
            month = digits[2:4]
            year = digits[4:8]
        elif len(digits) == 6:
            day = digits[0:2]
            month = digits[2:4]
            year = "20" + digits[4:6]
        else:
            raise ValueError(f"Cannot parse date from filename: {filename}")
        return f"{day}/{month}/{year}"

    raise ValueError(f"Cannot parse date from filename: {filename}")


# ---------------------------------------------------------------------------
# URL / title normalization
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Normalize a URL for comparison: lowercase, strip scheme and trailing slash."""
    result = url.strip().lower()
    result = re.sub(r"^https?://", "", result)
    result = result.rstrip("/")
    return result


def normalize_title(title: str) -> str:
    """Normalize a title for comparison: lowercase, strip accents, collapse spaces."""
    result = title.strip().lower()
    nfd = unicodedata.normalize("NFD", result)
    result = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    result = re.sub(r"\s+", " ", result)
    return result


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match_results(
    email_pubs: list[dict],
    search_results: list[dict],
) -> dict:
    """Match search results against email publications by URL or title.

    Args:
        email_pubs: List of {"url": str|None, "title": str} from email parser.
        search_results: List of dicts from search_all_terms(), each with keys
            like "href", "title", "section", "abstract", etc.

    Returns:
        {
            "selected": [search_result + {"match_type": "url"|"title"}, ...],
            "rejected": [search_result + {"match_type": None}, ...],
            "unmatched_email": [email_pub, ...],
        }
    """
    email_urls: dict[str, int] = {}
    email_titles: dict[str, int] = {}
    matched_email_indices: set[int] = set()

    for i, pub in enumerate(email_pubs):
        if pub.get("url"):
            email_urls[normalize_url(pub["url"])] = i
        email_titles[normalize_title(pub["title"])] = i

    selected: list[dict] = []
    rejected: list[dict] = []

    for result in search_results:
        norm_href = normalize_url(result.get("href", ""))
        norm_title = normalize_title(result.get("title", ""))

        if norm_href in email_urls:
            matched_email_indices.add(email_urls[norm_href])
            selected.append({**result, "match_type": "url"})
        elif norm_title in email_titles:
            matched_email_indices.add(email_titles[norm_title])
            selected.append({**result, "match_type": "title"})
        else:
            rejected.append({**result, "match_type": None})

    unmatched_email = [
        pub for i, pub in enumerate(email_pubs) if i not in matched_email_indices
    ]

    return {
        "selected": selected,
        "rejected": rejected,
        "unmatched_email": unmatched_email,
    }


# ---------------------------------------------------------------------------
# Output — JSON save and reporting
# ---------------------------------------------------------------------------

def save_training_json(data: dict, output_dir: str) -> str:
    """Salva dados de treinamento em arquivo JSON.

    Args:
        data: Dicionario com chaves "date" (DD/MM/YYYY), "source_file", "tier",
              "selected", "rejected", "unmatched_email", "stats".
        output_dir: Caminho do diretorio de saida.

    Returns:
        Caminho completo do arquivo JSON salvo.
    """
    date_str = data["date"].replace("/", "")
    filename = f"training_{date_str}.json"
    filepath = os.path.join(output_dir, filename)

    os.makedirs(output_dir, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))

    return filepath


def print_summary(result: dict) -> None:
    """Imprime resumo do processamento de um unico email."""
    print(f'=== {result["source_file"]} ({result["date"]}) ===')
    print(f'  Tier: {result["tier"]}')
    print(f'  Email: {result["email_count"]} publicações')
    print(f'  Busca: {result["search_count"]} resultados')
    print(f'  Selecionadas: {result["selected_count"]}')
    print(f'  Rejeitadas: {result["rejected_count"]}')
    print(f'  Sem match no email: {result["unmatched_count"]}')
    print(f'  JSON salvo: {result["json_path"]}')


def print_final_report(all_results: list) -> None:
    """Imprime relatorio consolidado de todos os emails processados."""
    total_selected = sum(r["selected_count"] for r in all_results)
    total_rejected = sum(r["rejected_count"] for r in all_results)
    total_unmatched = sum(r["unmatched_count"] for r in all_results)
    total = total_selected + total_rejected
    taxa = (total_selected / total * 100) if total > 0 else 0.0

    print("========================================")
    print("         RELATÓRIO FINAL")
    print("========================================")
    print(f"Emails processados: {len(all_results)}")
    print(f"Total selecionadas: {total_selected}")
    print(f"Total rejeitadas: {total_rejected}")
    print(f"Total sem match: {total_unmatched}")
    print(f"Taxa de seleção: {taxa:.1f}%")
    print("----------------------------------------")


# ---------------------------------------------------------------------------
# CLI orchestration
# ---------------------------------------------------------------------------

def process_one_email(filepath: str, terms: list, output_dir: str, dry_run: bool = False) -> dict | None:
    """Orchestrates: parse -> infer_date -> [search API] -> match -> save JSON -> print summary."""
    filename = os.path.basename(filepath)

    # 1. Detect tier and parse
    tier = detect_email_tier(filepath)
    if tier == 1:
        email_pubs = parse_email_clean(filepath)
    else:
        email_pubs = parse_email_word(filepath)

    # 2. Infer date
    date_str = infer_date(filename)

    # 3. If dry_run, just print stats and return
    if dry_run:
        print(f"[DRY-RUN] {filename} | Tier {tier} | Data: {date_str} | {len(email_pubs)} publicações")
        return None

    # 4. Search API — lazy import to avoid heavy dependencies during dry-run
    from dou_clipping import search_all_terms  # noqa: F811

    # Convert date from DD/MM/YYYY to DD-MM-YYYY for the API
    api_date = date_str.replace("/", "-")
    search_results = search_all_terms(terms, api_date)

    # 5. Match
    match_result = match_results(email_pubs, search_results)

    # 6. Build output data
    data = {
        "date": date_str,
        "source_file": filename,
        "tier": tier,
        "selected": match_result["selected"],
        "rejected": match_result["rejected"],
        "unmatched_email": match_result["unmatched_email"],
        "stats": {
            "email_count": len(email_pubs),
            "search_count": len(search_results),
            "selected_count": len(match_result["selected"]),
            "rejected_count": len(match_result["rejected"]),
            "unmatched_count": len(match_result["unmatched_email"]),
        },
    }

    # 7. Save JSON
    json_path = save_training_json(data, output_dir)

    # 8. Print summary
    result = {
        "source_file": filename,
        "date": date_str,
        "tier": tier,
        "email_count": len(email_pubs),
        "search_count": len(search_results),
        "selected_count": len(match_result["selected"]),
        "rejected_count": len(match_result["rejected"]),
        "unmatched_count": len(match_result["unmatched_email"]),
        "json_path": json_path,
    }
    print_summary(result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Build training data from DOU email history")
    parser.add_argument("--file", help="Process only this email file")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't call API")
    parser.add_argument("--tier", type=int, choices=[1, 2], help="Process only this tier")
    parser.add_argument("--emails-dir", default=DEFAULT_EMAILS_DIR, help="Path to email files")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Path to output JSON files")
    args = parser.parse_args()

    # List email files
    emails = sorted(glob.glob(os.path.join(args.emails_dir, "*.htm")))

    if args.file:
        emails = [e for e in emails if os.path.basename(e) == args.file]
        if not emails:
            print(f"Arquivo não encontrado: {args.file}")
            sys.exit(1)

    if args.tier:
        filtered = []
        for e in emails:
            try:
                if detect_email_tier(e) == args.tier:
                    filtered.append(e)
            except ValueError:
                logging.warning(f"Ignorando arquivo de tier desconhecido: {os.path.basename(e)}")
        emails = filtered

    # Sort by inferred date (convert DD/MM/YYYY to YYYYMMDD for correct chronological order)
    def _date_sort_key(email_path: str) -> str:
        d = infer_date(os.path.basename(email_path))  # DD/MM/YYYY
        parts = d.split("/")
        return f"{parts[2]}{parts[1]}{parts[0]}"  # YYYYMMDD

    emails.sort(key=_date_sort_key)

    if not emails:
        print("Nenhum email encontrado para processar.")
        sys.exit(0)

    # Import search terms (only if not dry-run, to avoid heavy deps)
    if not args.dry_run:
        from dou_clipping import SEARCH_TERMS
        terms = SEARCH_TERMS
    else:
        terms = []

    all_results = []
    for i, email_path in enumerate(emails):
        if i > 0 and not args.dry_run:
            print(f"\n--- Aguardando 10s antes do próximo email ---\n")
            time.sleep(10)

        try:
            result = process_one_email(email_path, terms, args.output_dir, args.dry_run)
            if result:
                all_results.append(result)
        except Exception as exc:
            logging.error(f"Erro ao processar {os.path.basename(email_path)}: {exc}")
            continue

    if all_results:
        print()
        print_final_report(all_results)


if __name__ == "__main__":
    main()
