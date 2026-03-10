"""
Script para busca e clipping do DOU (Diário Oficial da União).
Gera corpo de email HTML pronto para copiar/colar no Outlook.
"""

import html as _html
import json
import logging
import time
import re
import io
from copy import deepcopy
from datetime import datetime
from random import random
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
import pdfplumber

from rules_engine import (
    get_search_terms,
    get_stems,
    get_stem_patterns,
    get_section_config,
    get_secao2_rules,
    get_positive_rules,
    get_negative_rules,
    get_split_patterns,
    get_display_config,
    get_terms_display,
    get_all_match_patterns,
)

# API URLs
IN_WEB_BASE_URL = "https://www.in.gov.br/web/dou/-/"
IN_API_BASE_URL = "https://www.in.gov.br/consulta/-/buscar/dou"
BOLETIM_BASE_URL = "https://www.camara.leg.br/boletimadm/{year}/Ba{date}.pdf"

# Mapa de seções da API para display
SECTION_DISPLAY = {
    "do1": "1", "do2": "2", "do3": "3",
    "do1e": "1 - Extra", "do2e": "2 - Extra", "do3e": "3 - Extra",
    "do1_extra_a": "1 - Extra A", "do1_extra_b": "1 - Extra B",
    "do2_extra_a": "2 - Extra A", "do3_extra_a": "3 - Extra A",
}

# Termos de busca — carregados de rules.yaml via rules_engine
SEARCH_TERMS = get_search_terms()

# Lista legível das palavras-chave para o rodapé
SEARCH_TERMS_DISPLAY = get_terms_display()


# ---------------------------------------------------------------------------
# Utility: stem matching
# ---------------------------------------------------------------------------

def match_stems(text: str, stem_entries: list[dict], stem_patterns: list[re.Pattern]) -> set[str]:
    """Return set of matched stem labels found in *text*."""
    matched = set()
    for entry, pattern in zip(stem_entries, stem_patterns):
        if pattern.search(text):
            radical = entry.get("radical", "")
            matched.add(f"{radical}* (radical)")
    return matched


# ---------------------------------------------------------------------------
# Utility: highlight (new — supports stems)
# ---------------------------------------------------------------------------

def highlight_all(text: str, exact_terms: list[str], stem_patterns: list[re.Pattern] = None) -> str:
    """Highlight all exact-term and stem matches by merging overlapping spans."""
    HIGHLIGHT_OPEN = '<span style="background-color:#FFFF00">'
    HIGHLIGHT_CLOSE = '</span>'
    spans = []
    for term in exact_terms:
        pat = re.compile(re.escape(term), re.IGNORECASE)
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
    if stem_patterns:
        for pat in stem_patterns:
            for m in pat.finditer(text):
                spans.append((m.start(), m.end()))
    if not spans:
        return text
    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        text = text[:start] + HIGHLIGHT_OPEN + text[start:end] + HIGHLIGHT_CLOSE + text[end:]
    return text


# ---------------------------------------------------------------------------
# Utility: context windows
# ---------------------------------------------------------------------------

def extract_context_windows(
    text: str,
    terms: list[str],
    stem_patterns: list[re.Pattern] = None,
    chars_before: int = 300,
    chars_after: int = 300,
    max_total: int = 2000,
    merge_gap: int = 50,
) -> str:
    """Extract context windows around matches, merge overlapping ones, snap to word boundaries."""
    # Collect all match spans
    spans = []
    for term in terms:
        pat = re.compile(re.escape(term), re.IGNORECASE)
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
    if stem_patterns:
        for pat in stem_patterns:
            for m in pat.finditer(text):
                spans.append((m.start(), m.end()))

    # No matches — return first max_total chars at word boundary
    if not spans:
        if len(text) <= max_total:
            return text
        cut = text[:max_total]
        sp = cut.rfind(' ')
        if sp > max_total - 80:
            cut = cut[:sp]
        return cut + "\n[...]"

    spans.sort()

    # Build windows around each span
    windows = []
    for start, end in spans:
        w_start = max(0, start - chars_before)
        w_end = min(len(text), end + chars_after)
        windows.append((w_start, w_end))

    # Merge overlapping / close windows
    merged = [windows[0]]
    for w_start, w_end in windows[1:]:
        prev_start, prev_end = merged[-1]
        if w_start <= prev_end + merge_gap:
            merged[-1] = (prev_start, max(prev_end, w_end))
        else:
            merged.append((w_start, w_end))

    # Snap to word boundaries (find nearest space within 80 chars)
    def snap_left(pos: int) -> int:
        if pos == 0:
            return 0
        search_start = max(0, pos - 80)
        idx = text.rfind(' ', search_start, pos)
        if idx != -1:
            return idx + 1
        return pos

    def snap_right(pos: int) -> int:
        if pos >= len(text):
            return len(text)
        idx = text.find(' ', pos, min(pos + 80, len(text)))
        if idx != -1:
            return idx
        return pos

    snapped = [(snap_left(s), snap_right(e)) for s, e in merged]

    # Assemble with separator, respecting max_total
    parts = []
    total_chars = 0
    for s, e in snapped:
        fragment = text[s:e]
        if total_chars + len(fragment) > max_total and parts:
            break
        parts.append((s, e, fragment))
        total_chars += len(fragment)

    result_parts = []
    first_start = parts[0][0] if parts else 0
    if first_start > 10:
        result_parts.append("[...]")

    for i, (s, e, fragment) in enumerate(parts):
        if i > 0:
            result_parts.append("\n[...]\n")
        result_parts.append(fragment)

    last_end = parts[-1][1] if parts else 0
    if last_end < len(text):
        result_parts.append("\n[...]")

    return "".join(result_parts)


# ---------------------------------------------------------------------------
# Utility: split compound acts
# ---------------------------------------------------------------------------

def split_compound_acts(item: dict, patterns: list[dict]) -> list[dict]:
    """Split a compound act into sub-acts using split patterns from rules_engine."""
    full_text = item.get("full_text")
    if not full_text:
        return [item]

    for pat in patterns:
        sep_re = pat.get("regex_separador_compiled")
        if not sep_re:
            continue
        if not sep_re.search(full_text):
            continue

        # Split using the separator pattern
        fragments = sep_re.split(full_text)
        # Filter fragments < 50 chars
        fragments = [f for f in fragments if len(f.strip()) >= 50]

        if len(fragments) <= 1:
            continue

        # Build sub-acts
        sub_acts = []
        titulo_re = pat.get("titulo_regex_compiled")
        original_title = item.get("title", "")
        split_tipo = pat.get("tipo", "")

        for idx, fragment in enumerate(fragments):
            sub = deepcopy(item)
            sub["full_text"] = fragment.strip()

            # Try to extract title from fragment
            if titulo_re:
                m = titulo_re.search(fragment)
                if m:
                    sub["title"] = m.group(0).strip()
                else:
                    sub["title"] = f"{original_title} — Ato {idx + 1}"
            else:
                sub["title"] = f"{original_title} — Ato {idx + 1}"

            # Tags
            sub["split_from"] = original_title
            sub["split_tipo"] = split_tipo
            sub["split_index"] = idx
            sub_acts.append(sub)

        return sub_acts

    return [item]


# ---------------------------------------------------------------------------
# Seção 2: rule matching and search
# ---------------------------------------------------------------------------

def matches_secao2_rule(text: str, rule: dict) -> bool:
    """Check whether *text* matches a Seção 2 appointment rule."""
    filtro = rule.get("filtro", {})

    # texto_contem_qualquer — at least one term must match
    contem = filtro.get("texto_contem_qualquer", [])
    if contem:
        found_any = False
        for term in contem:
            if re.search(re.escape(term), text, re.IGNORECASE):
                found_any = True
                break
        if not found_any:
            return False

    # texto_nao_contem — none of these should match
    nao_contem = filtro.get("texto_nao_contem", [])
    for term in nao_contem:
        if re.search(re.escape(term), text, re.IGNORECASE):
            return False

    # padrao_fc — regex pattern with expanded FC handling
    padrao_fc = filtro.get("padrao_fc")
    padrao_fc_compiled = filtro.get("padrao_fc_compiled")
    if padrao_fc and not padrao_fc_compiled:
        # Expand FC[- ]? to handle zero-padded FC-03 etc.
        expanded = padrao_fc.replace("FC[- ]?", "FC[- ]*0*")
        padrao_fc_compiled = re.compile(expanded, re.IGNORECASE | re.UNICODE)
    if padrao_fc_compiled:
        if not padrao_fc_compiled.search(text):
            return False

    return True


def search_secao2(
    date_str: str,
    rules: list[dict],
    seen_titles: set,
    progress_callback=None,
) -> list[dict]:
    """Search Seção 2 for appointment acts matching configured rules."""
    results = search_dou("Câmara dos Deputados", date_str, sections=["do2", "do2e"])
    found_items = []

    for item in results:
        title = item["title"]
        if title in seen_titles:
            continue

        # Fetch full text
        full_text = fetch_full_text(item["href"])
        if full_text:
            item["full_text"] = full_text

        text_to_check = full_text or item.get("abstract", "")
        if not text_to_check:
            continue

        # Test each rule
        for rule in rules:
            if matches_secao2_rule(text_to_check, rule):
                seen_titles.add(title)
                item["found_by"] = rule.get("descricao", "Seção 2")
                found_items.append(item)
                break

        time.sleep(0.5 + random() * 1.0)

    return found_items


# ---------------------------------------------------------------------------
# Existing functions (preserved)
# ---------------------------------------------------------------------------

def clean_html(text: str) -> str:
    """Remove tags HTML."""
    return re.sub(r'<.*?>', '', text)


def fetch_boletim_items(
    date: datetime,
    terms: list = None,
    stem_entries: list[dict] = None,
    stem_patterns: list[re.Pattern] = None,
) -> list:
    """
    Baixa o Boletim Administrativo da Câmara, extrai o texto completo,
    busca os termos fornecidos (ou SEARCH_TERMS padrão) e retorna publicações
    relevantes no mesmo formato dos itens do DOU.
    """
    url = BOLETIM_BASE_URL.format(year=date.year, date=date.strftime("%Y%m%d"))
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            logging.info(f"Boletim Administrativo não disponível para {date.strftime('%d/%m/%Y')}")
            return []
    except:
        return []

    try:
        r = requests.get(url, headers=headers, timeout=30)
        pdf = pdfplumber.open(io.BytesIO(r.content))
    except Exception as e:
        logging.error(f"Erro ao baixar/abrir Boletim: {e}")
        return []

    # Extrair texto completo
    full_text = ""
    for page in pdf.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"
    pdf.close()

    # Dividir em blocos usando cabeçalhos de seção como separadores
    # Padrões que indicam início de um novo ato/seção no BA
    block_markers = re.compile(
        r'^(ATOS? D[OA] |DA |DO |PORTARIA|ATO DA MESA|RESOLUÇÃO|INSTRUÇÃO|DECISÃO)',
        re.MULTILINE
    )

    lines = full_text.split('\n')

    # Limpar linhas de cabeçalho/rodapé repetidas do PDF
    clean_lines = []
    for line in lines:
        line_lower = line.lower().strip()
        if any(skip in line_lower for skip in [
            'documento assinado por', 'selo digital de segurança',
            'ano xlix', 'b. adm.', 'ddooccuummeennttoo',
            'sseelloo ddiiggiittaall',
        ]):
            continue
        if line.strip().startswith('Câmara dos Deputados') and len(line.strip()) < 30:
            continue
        clean_lines.append(line)

    full_clean = '\n'.join(clean_lines)

    # Buscar termos no texto do BA (usa exatamente os termos configurados)
    ba_terms = list(terms) if terms else SEARCH_TERMS.copy()

    # Verificar se há termos relevantes no BA
    found_terms = set()
    for term in ba_terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        if pattern.search(full_clean):
            found_terms.add(term)

    # Also check stems
    stem_labels = set()
    if stem_entries and stem_patterns:
        stem_labels = match_stems(full_clean, stem_entries, stem_patterns)

    if not found_terms and not stem_labels:
        logging.info(f"  BA {date.strftime('%d/%m/%Y')}: nenhum termo relevante encontrado")
        return []

    # Retornar UMA entrada consolidada com o texto completo do BA
    # O highlight será aplicado depois pelo generate_email_body
    # Limitar o texto a algo razoável
    if len(full_clean) > 5000:
        full_clean = full_clean[:5000] + "\n[...]"

    # Combine exact terms and stem labels in found_by
    combined_labels = sorted(found_terms) + sorted(stem_labels)

    found_items = [{
        "section": "BA",
        "title": f"Boletim Administrativo — {date.strftime('%d/%m/%Y')}",
        "href": url,
        "abstract": "",
        "full_text": full_clean,
        "date": date.strftime("%d/%m/%Y"),
        "edition": f"BA nº {date.strftime('%j').lstrip('0')}",
        "page": "",
        "hierarchy": "Câmara dos Deputados",
        "arttype": "Boletim Administrativo",
        "found_by": ", ".join(combined_labels),
    }]

    logging.info(f"  BA {date.strftime('%d/%m/%Y')}: {len(found_terms)} termos + {len(stem_labels)} radicais encontrados — entrada única consolidada")
    return found_items


def get_section_display(section_code: str) -> str:
    """Converte código de seção para display legível."""
    return SECTION_DISPLAY.get(section_code.lower(), section_code)


def fetch_full_text(url: str) -> Optional[str]:
    """
    Busca a página completa de uma publicação do DOU e extrai o texto
    substancial: ementa + dispositivo (resolve/acordam/recomendações).
    Junta linhas curtas consecutivas para evitar fragmentação.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.warning(f"Erro ao buscar texto de {url}: {e}")
        return None

    soup = BeautifulSoup(response.content, "html.parser")

    # O texto da publicação fica dentro de um container Liferay
    content_div = (
        soup.find("div", class_="texto-dou")
        or soup.find("div", class_="portlet-content")
        or soup.find("div", class_="journal-content-article")
    )
    if not content_div:
        return None

    # Extrair todos os parágrafos
    paragraphs = content_div.find_all("p")
    if not paragraphs:
        return None

    # Extrair texto e juntar linhas curtas consecutivas
    raw_lines = []
    for p in paragraphs:
        text = p.get_text(strip=True)
        if text:
            raw_lines.append(text)

    # Consolidar: juntar linhas curtas (<80 chars) com a próxima,
    # exceto se parecem ser itens de lista (começam com algarismo romano,
    # número+ponto, letra+ponto, ou travessão)
    consolidated = []
    buffer = ""
    item_pattern = re.compile(
        r'^(I{1,3}V?|VI{0,3}|IX|X{0,3}I{0,3}V?|'  # romanos
        r'\d+[\.\)°º]|'                              # 1. 2) 3°
        r'[a-z][\.\)]|'                               # a. b)
        r'§|Art\.|Parágrafo|CAPÍTULO|SEÇÃO|TÍTULO|'
        r'[-–—•])'                                     # travessão/bullet
    )
    for line in raw_lines:
        is_item = bool(item_pattern.match(line))
        is_short = len(line) < 80

        if is_item or not is_short:
            # Flush buffer
            if buffer:
                consolidated.append(buffer)
                buffer = ""
            consolidated.append(line)
        else:
            # Linha curta, acumular
            if buffer:
                buffer += " " + line
            else:
                buffer = line
    if buffer:
        consolidated.append(buffer)

    full = "\n".join(consolidated)

    # Limitar usando display config (default 5000)
    display_cfg = get_display_config()
    max_chars = display_cfg.get("relatorio_max_chars", 5000)
    if len(full) > max_chars:
        # Cut at word boundary
        cut = full[:max_chars]
        sp = cut.rfind(' ')
        if sp > max_chars - 80:
            cut = cut[:sp]
        full = cut + "\n[...]"

    return full if full else None


def search_dou(search_term: str, date_str: str, sections: list = None) -> list:
    """Busca um termo na API do DOU para uma data específica."""
    if sections is None:
        sections = ["do1", "do2", "do3", "doe"]

    payload = {
        "q": f'"{search_term}"',
        "exactDate": "personalizado",
        "publishFrom": date_str,
        "publishTo": date_str,
        "sortType": "0",
        "s": sections,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }

    try:
        response = requests.get(IN_API_BASE_URL, params=payload, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao buscar '{search_term}': {e}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    script_tag = soup.find(
        "script", id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"
    )
    if script_tag is None:
        return []

    try:
        json_data = json.loads(script_tag.contents[0])
        search_results = json_data.get("jsonArray", [])
    except (json.JSONDecodeError, IndexError):
        return []

    all_results = []
    for content in search_results:
        all_results.append(_parse_content(content))

    # Paginação
    pagination_tag = soup.find('button', id='lastPage')
    if pagination_tag:
        number_pages = int(pagination_tag.text.strip())
        last_item = search_results[-1] if search_results else None
        for page_num in range(1, number_pages):
            if not last_item:
                break
            payload.update({
                "id": last_item["classPK"],
                "displayDate": last_item["displayDateSortable"],
                "newPage": page_num + 1,
                "currentPage": page_num,
            })
            try:
                response = requests.get(IN_API_BASE_URL, params=payload, headers=headers, timeout=15)
                soup = BeautifulSoup(response.content, "html.parser")
                script_tag = soup.find(
                    "script", id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"
                )
                if script_tag:
                    page_results = json.loads(script_tag.contents[0]).get("jsonArray", [])
                    for content in page_results:
                        all_results.append(_parse_content(content))
                    last_item = page_results[-1] if page_results else None
            except Exception as e:
                logging.error(f"Erro na página {page_num + 1}: {e}")
                break
            time.sleep(0.5)

    return all_results


def _parse_content(content: dict) -> dict:
    """Extrai campos de um resultado da API do DOU."""
    return {
        "section": content.get("pubName", ""),
        "title": content.get("title", ""),
        "href": IN_WEB_BASE_URL + content.get("urlTitle", ""),
        "abstract": content.get("content", ""),
        "date": content.get("pubDate", ""),
        "edition": content.get("editionNumber", ""),
        "page": content.get("pageNumber", ""),
        "hierarchy": content.get("hierarchyStr", ""),
        "arttype": content.get("artType", ""),
    }


def search_all_terms(
    terms: list,
    date_str: str,
    progress_callback=None,
    secao2_rules: list[dict] = None,
) -> list:
    """
    Busca todos os termos com lógica de seções:
    - Seção 1: todos os termos (com busca de ementa para atos normativos)
    - Seção 2: regras de nomeação configuradas (se secao2_rules fornecido)
    - Seção 3: apenas "Câmara dos Deputados"

    progress_callback(current, total, message): chamado a cada passo para reportar progresso.
    """
    seen_titles = set()
    all_items = []

    # === SEÇÃO 3: apenas "Câmara dos Deputados" (só se estiver nos termos) ===
    buscar_secao3 = any(t.lower() == "câmara dos deputados" for t in terms)
    buscar_secao2 = bool(secao2_rules)
    total_steps = (1 if buscar_secao3 else 0) + (1 if buscar_secao2 else 0) + len(terms)
    current_step = 0

    if buscar_secao3:
        logging.info("=== Seção 3: Buscando 'Câmara dos Deputados' ===")
        if progress_callback:
            progress_callback(current_step, total_steps, "Seção 3: Câmara dos Deputados")
        results = search_dou("Câmara dos Deputados", date_str, sections=["do3"])
        for item in results:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                item["found_by"] = "Câmara dos Deputados"
                all_items.append(item)
        logging.info(f"  -> {len(results)} resultado(s), {len(all_items)} novo(s)")
        current_step += 1
        time.sleep(1.0 + random() * 1.5)

    # === SEÇÃO 2: regras de nomeação ===
    if buscar_secao2:
        logging.info("=== Seção 2: Buscando atos de nomeação (regras configuradas) ===")
        if progress_callback:
            progress_callback(current_step, total_steps, "Seção 2: atos de nomeação")
        secao2_items = search_secao2(date_str, secao2_rules, seen_titles, progress_callback)
        all_items.extend(secao2_items)
        logging.info(f"  Seção 2: {len(secao2_items)} publicação(ões) encontrada(s)")
        current_step += 1
        time.sleep(1.0 + random() * 1.5)

    # === SEÇÃO 1: todos os termos ===
    total = len(terms)
    secao1_count = 0
    for i, term in enumerate(terms):
        logging.info(f"[{i+1}/{total}] Seção 1 - Buscando: '{term}'")
        if progress_callback:
            progress_callback(current_step, total_steps, f"Seção 1: {term}")
        results = search_dou(term, date_str, sections=["do1", "do1e"])

        added = 0
        for item in results:
            title = item["title"]
            if title not in seen_titles:
                seen_titles.add(title)
                item["found_by"] = term
                all_items.append(item)
                added += 1
                secao1_count += 1

        if results:
            logging.info(f"  -> {len(results)} resultado(s), {added} novo(s)")
        else:
            logging.info(f"  -> Nenhum resultado")

        current_step += 1
        delay = 1.0 + random() * 1.5
        time.sleep(delay)

    logging.info(f"Seção 1: {secao1_count} publicações encontradas")

    # === Buscar texto completo para publicações da seção 1 ===
    secao1_items = [item for item in all_items if item.get("section", "").startswith("DO1")]
    if secao1_items:
        logging.info(f"=== Buscando texto completo para {len(secao1_items)} publicações da seção 1 ===")
        for i, item in enumerate(secao1_items):
            logging.info(f"  [{i+1}/{len(secao1_items)}] {item['title'][:60]}...")
            if progress_callback:
                progress_callback(
                    total_steps - 1, total_steps,
                    f"Texto completo: {item['title'][:50]}..."
                )
            full_text = fetch_full_text(item["href"])
            if full_text:
                item["full_text"] = full_text
            time.sleep(0.5 + random() * 1.0)

    # === Split compound acts ===
    split_pats = get_split_patterns()
    if split_pats:
        expanded = []
        for item in all_items:
            expanded.extend(split_compound_acts(item, split_pats))
        all_items = expanded

    # Ordenar por data de publicação
    all_items.sort(key=lambda x: x.get("date", ""))

    logging.info(f"Total: {len(all_items)} publicações únicas após deduplicação e filtro")
    return all_items


def highlight_terms(text: str, terms: list) -> str:
    """Aplica realce amarelo nos termos de busca encontrados no texto.

    Kept for backward compatibility (app.py may still use it).
    """
    for term in terms:
        pattern = re.compile(f'({re.escape(term)})', re.IGNORECASE)
        text = pattern.sub(
            r'<span style="background-color:#FFFF00">\1</span>',
            text,
        )
    return text


def generate_email_body(
    items: list,
    date_display: str,
    search_terms: list | None = None,
    terms_display: str | None = None,
    stem_patterns: list[re.Pattern] = None,
) -> str:
    """
    Gera corpo de email HTML formatado:
    - Lista corrida ordenada por data
    - Metadados: Publicado em | Edição | Seção | Página
    - Órgão
    - Título (link)
    - Texto com termos destacados em amarelo
    - <hr> entre publicações
    - Rodapé com palavras-chave
    """
    F = 'font-size:12.0pt;font-family:Arial,sans-serif'

    _terms = search_terms if search_terms is not None else SEARCH_TERMS
    _terms_display = terms_display if terms_display is not None else SEARCH_TERMS_DISPLAY

    # Display config
    display_cfg = get_display_config()
    relatorio_max_chars = display_cfg.get("relatorio_max_chars", 5000)

    # Termos para highlight (usa exatamente os termos configurados)
    highlight_list = list(_terms)

    lines = []
    lines.append(f'<html><head><meta charset="UTF-8"></head>')
    lines.append(f'<body style="font-family:Arial,sans-serif;font-size:12pt">')

    for item in items:
        # Escapar todos os campos de origem externa antes de inserir no HTML
        e_date      = _html.escape(str(item.get("date", "")))
        e_edition   = _html.escape(str(item.get("edition", "")))
        e_page      = _html.escape(str(item.get("page", "")))
        e_hierarchy = _html.escape(str(item.get("hierarchy", "")))
        e_title     = _html.escape(str(item.get("title", "")))
        e_href      = _html.escape(str(item.get("href", "")))
        e_section   = get_section_display(item.get("section", ""))
        e_section   = _html.escape(e_section)

        # Metadados
        if item["section"] == "BA":
            meta = f'Publicado em: {e_date} | Boletim Administrativo da Câmara dos Deputados'
        else:
            meta = f'Publicado em: {e_date} | Edição: {e_edition} | Seção: {e_section}'
            if e_page:
                meta += f' | Página: {e_page}'
        lines.append(f'<p style="{F}">{meta}</p>')

        # Órgão
        lines.append(f'<p style="{F}">Órgão: {e_hierarchy}</p>')

        # Título com link
        lines.append(f'<p style="{F}"><a href="{e_href}"><b>{e_title}</b></a></p>')

        # Texto da publicação
        full_text = item.get("full_text")
        if full_text:
            # Truncate using display config limit
            if len(full_text) > relatorio_max_chars:
                cut = full_text[:relatorio_max_chars]
                sp = cut.rfind(' ')
                if sp > relatorio_max_chars - 80:
                    cut = cut[:sp]
                full_text = cut + "\n[...]"

            # Seção 1: mostrar texto com parágrafos consolidados e highlight
            for paragraph in full_text.split("\n"):
                paragraph = paragraph.strip()
                if paragraph:
                    # Escapar entidades HTML antes de aplicar highlight
                    paragraph = _html.escape(paragraph)
                    paragraph = highlight_all(paragraph, highlight_list, stem_patterns)
                    lines.append(f'<p style="{F}">{paragraph}</p>')
        else:
            # Seção 3 / fallback: usar abstract da API com highlight
            abstract = clean_html(item.get("abstract", ""))
            if len(abstract) > 500:
                cut = abstract[:500]
                last_dot = cut.rfind('.')
                if last_dot > 100:
                    abstract = cut[:last_dot + 1]
                else:
                    abstract = cut + "..."
            # Escapar entidades HTML antes de aplicar highlight (que injeta tags <span>)
            abstract = _html.escape(abstract)
            abstract = highlight_all(abstract, highlight_list, stem_patterns)
            lines.append(f'<p style="{F}">{abstract}</p>')

        # Separador
        lines.append('<hr>')
        lines.append('')

    # Rodapé com palavras-chave
    lines.append(f'<p style="{F}">&nbsp;</p>')
    lines.append(f'<p style="{F}">Buscas feitas para boas práticas, normativos e acórdãos sobre os seguintes temas:</p>')
    lines.append(f'<p style="{F}">&nbsp;</p>')

    for term_line in _terms_display.strip().split('\n'):
        lines.append(f'<p style="{F}">{_html.escape(term_line)}</p>')

    lines.append('</body></html>')

    return "\n".join(lines)


def run_clipping(dates: list, output_dir: str = "."):
    """Executa o clipping para uma ou mais datas e salva um único HTML."""
    all_items = []

    # Load stem data from rules_engine
    stem_entries = get_stems()
    stem_patterns = get_stem_patterns()

    # Load secao2 rules from rules_engine
    secao2_rules = get_secao2_rules()

    for date in dates:
        date_str = date.strftime("%d-%m-%Y")
        date_display = date.strftime("%d/%m/%Y")

        # DOU
        logging.info(f"=== Buscando DOU para {date_display} ===")
        items = search_all_terms(
            SEARCH_TERMS, date_str,
            secao2_rules=secao2_rules if secao2_rules else None,
        )
        all_items.extend(items)

        # Boletim Administrativo
        logging.info(f"=== Buscando Boletim Administrativo para {date_display} ===")
        ba_items = fetch_boletim_items(
            date,
            stem_entries=stem_entries,
            stem_patterns=stem_patterns,
        )
        all_items.extend(ba_items)

    # Ordenar tudo por data
    all_items.sort(key=lambda x: x.get("date", ""))

    # Gerar display do período
    if len(dates) == 1:
        title_display = dates[0].strftime("%d/%m/%Y")
        file_suffix = dates[0].strftime("%d%m%Y")
    else:
        d0 = dates[0].day
        d1 = dates[-1]
        title_display = f"{d0} a {d1.day}/{d1.month}/{d1.year}"
        file_suffix = f"{dates[0].strftime('%d%m%Y')}_{dates[-1].strftime('%d%m%Y')}"

    html = generate_email_body(
        all_items, title_display,
        stem_patterns=stem_patterns,
    )

    output_path = f"{output_dir}/DOU_{file_suffix}.htm"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logging.info(f"=== Clipping salvo em: {output_path} ({len(all_items)} publicações) ===")
    return output_path


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    dates = [
        datetime(2026, 3, 2),
        datetime(2026, 3, 3),
        datetime(2026, 3, 4),
    ]

    output_dir = "emails de saída"

    if len(sys.argv) > 1:
        try:
            parsed_dates = []
            for arg in sys.argv[1:]:
                parsed_dates.append(datetime.strptime(arg, "%d-%m-%Y"))
            dates = parsed_dates
        except ValueError:
            print(f"Formato de data inválido. Use DD-MM-YYYY")
            sys.exit(1)

    run_clipping(dates, output_dir)
