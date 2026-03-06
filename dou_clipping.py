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
from datetime import datetime
from random import random
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
import pdfplumber

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

# Termos de busca
SEARCH_TERMS = [
    "Câmara dos Deputados",
    "Tecnologia da informação",
    "Auditoria de TI",
    "Auditoria de TIC",
    "Auditoria interna",
    "COSO",
    "Controle interno",
    "Controles internos",
    "COBIT",
    "Indicadores",
    "Itil",
    "BPM",
    "Governança corporativa",
    "Governança de TI",
    "Governança de aquisições",
    "Governança de contratações",
    "Gestão de aquisições",
    "Gestão de contratações",
    "Gestão de contratos",
    "Fiscalização de contratos",
    "Riscos",
    "Segurança de informação",
    "Segurança da informação",
    "Gestão de processos",
    "Melhoria de processos",
    "Dados abertos",
    "Dados em formatos abertos",
    "Fábrica de Software",
    "Ponto de função",
    "Pontos de função",
    "Processo de software",
    "Soluções de TI",
    "Hackers",
    "Hacktivismo",
    "Processos críticos",
    "Continuidade de negócios",
    "Secretaria de Fiscalização de Tecnologia da Informação",
    "Sefti",
    "AudTI",
    "Transparência da informação",
    "Lei de Acesso à Informação",
    "LAI",
    "Inteligência artificial",
    "Ciência de dados",
]

# Lista legível das palavras-chave para o rodapé
SEARCH_TERMS_DISPLAY = """Tecnologia da informação
Auditoria de TI
Auditoria de TIC
Auditoria interna
COSO
Controle(s) interno(s)
COBIT
Indicadores
Itil
BPM
Governança corporativa
Governança de TI
Governança de aquisições
Governança de contratações
Gestão de aquisições
Gestão de contratações
Gestão de contratos
Fiscalização de contratos
Riscos
Segurança de informação
Segurança da informação
Gestão de processos
Melhoria de processos
Dados abertos
Dados em formatos abertos
Fábrica de Software
Ponto(s) de função
Processo de software
Soluções de TI
Hackers
Hacktivismo
Processos críticos
Continuidade de negócios
Secretaria de Fiscalização de Tecnologia da Informação
Sefti/TCU
AudTI
Transparência da informação
Lei de Acesso à Informação
LAI
Inteligência artificial
Ciência de dados"""

def clean_html(text: str) -> str:
    """Remove tags HTML."""
    return re.sub(r'<.*?>', '', text)


def fetch_boletim_items(date: datetime, terms: list = None) -> list:
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

    if not found_terms:
        logging.info(f"  BA {date.strftime('%d/%m/%Y')}: nenhum termo relevante encontrado")
        return []

    # Retornar UMA entrada consolidada com o texto completo do BA
    # O highlight será aplicado depois pelo generate_email_body
    # Limitar o texto a algo razoável
    if len(full_clean) > 5000:
        full_clean = full_clean[:5000] + "\n[...]"

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
        "found_by": ", ".join(sorted(found_terms)),
    }]

    logging.info(f"  BA {date.strftime('%d/%m/%Y')}: {len(found_terms)} termos encontrados — entrada única consolidada")
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

    # Limitar a ~3000 chars para não explodir o email
    if len(full) > 3000:
        full = full[:3000] + "\n[...]"

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


def search_all_terms(terms: list, date_str: str, progress_callback=None) -> list:
    """
    Busca todos os termos com lógica de seções:
    - Seção 1: todos os termos (com busca de ementa para atos normativos)
    - Seção 2: ignorada (atos de nomeação)
    - Seção 3: apenas "Câmara dos Deputados"

    progress_callback(current, total, message): chamado a cada passo para reportar progresso.
    """
    seen_titles = set()
    all_items = []

    # === SEÇÃO 3: apenas "Câmara dos Deputados" (só se estiver nos termos) ===
    buscar_secao3 = any(t.lower() == "câmara dos deputados" for t in terms)
    total_steps = (1 if buscar_secao3 else 0) + len(terms)
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

    # Ordenar por data de publicação
    all_items.sort(key=lambda x: x.get("date", ""))

    logging.info(f"Total: {len(all_items)} publicações únicas após deduplicação e filtro")
    return all_items


def highlight_terms(text: str, terms: list) -> str:
    """Aplica realce amarelo nos termos de busca encontrados no texto."""
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
) -> str:
    """
    Gera corpo de email HTML no formato do Rodrigo:
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
            meta = f'Publicado em: {e_date} | Edição: {e_edition} | Seção: {e_section} | Página: {e_page}'
        lines.append(f'<p style="{F}">{meta}</p>')

        # Órgão
        lines.append(f'<p style="{F}">Órgão: {e_hierarchy}</p>')

        # Título com link
        lines.append(f'<p style="{F}"><a href="{e_href}"><b>{e_title}</b></a></p>')

        # Texto da publicação
        full_text = item.get("full_text")
        if full_text:
            # Seção 1: mostrar texto com parágrafos consolidados e highlight
            for paragraph in full_text.split("\n"):
                paragraph = paragraph.strip()
                if paragraph:
                    # Escapar entidades HTML antes de aplicar highlight
                    paragraph = _html.escape(paragraph)
                    paragraph = highlight_terms(paragraph, highlight_list)
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
            abstract = highlight_terms(abstract, highlight_list)
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

    for date in dates:
        date_str = date.strftime("%d-%m-%Y")
        date_display = date.strftime("%d/%m/%Y")

        # DOU
        logging.info(f"=== Buscando DOU para {date_display} ===")
        items = search_all_terms(SEARCH_TERMS, date_str)
        all_items.extend(items)

        # Boletim Administrativo
        logging.info(f"=== Buscando Boletim Administrativo para {date_display} ===")
        ba_items = fetch_boletim_items(date)
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

    html = generate_email_body(all_items, title_display)

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
