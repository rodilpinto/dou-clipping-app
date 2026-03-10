"""
Aplicação Streamlit para clipping do Diário Oficial da União (DOU).
Permite buscar publicações por data, selecionar resultados relevantes,
gerar relatório HTML e salvar histórico no GitHub.
"""

import base64
import json
import html as html_module
from datetime import date, datetime, timedelta

import requests
import streamlit as st
import streamlit.components.v1 as components

from dou_clipping import (
    SEARCH_TERMS,
    clean_html,
    fetch_boletim_items,
    generate_email_body,
    get_section_display,
    highlight_terms,
    highlight_all,
    extract_context_windows,
    search_all_terms,
)
from rules_engine import (
    get_search_terms,
    get_stems,
    get_stem_patterns,
    get_secao2_rules,
    get_display_config,
    get_terms_display,
    get_llm_config,
)

import time

APP_VERSION = "2.0"
APP_AUTHOR = "Rodrigo Pinto"

# Estimativa de tempo manual por termo de busca (em segundos):
# abrir pesquisa, digitar termo, configurar filtros, analisar resultados
_SECS_PER_TERM = 35
# Overhead fixo: agregar resultados + deduplicar + formatar relatorio
_SECS_OVERHEAD = 300  # 5 min


def _estimate_time_saved(num_terms: int, num_dates: int = 1) -> int:
    """Retorna estimativa de minutos economizados por busca automatizada."""
    total_secs = (num_terms * _SECS_PER_TERM + _SECS_OVERHEAD) * num_dates
    return round(total_secs / 60)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Clipping DOU - NUATI", layout="wide", page_icon="https://www2.camara.leg.br/favicon.ico")

# ---------------------------------------------------------------------------
# CSS customizado — identidade visual da Câmara dos Deputados
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Header: verde claro com faixa dourada */
    header[data-testid="stHeader"] {
        background: linear-gradient(to bottom, #4a8c4a 0%, #4a8c4a 92%, #c8a415 92%, #c8a415 100%) !important;
    }

    /* Sidebar: verde claro, texto escuro legível */
    section[data-testid="stSidebar"] {
        background-color: #e8f0e8 !important;
        border-right: 3px solid #c8a415 !important;
    }

    /* Botão primário: verde médio */
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="stBaseButton-primary"] {
        background-color: #4CAF50 !important;
        border-color: #4CAF50 !important;
        color: white !important;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover {
        background-color: #43A047 !important;
        border-color: #43A047 !important;
    }

    /* Botões secundários */
    .stButton > button:not([kind="primary"]):not([data-testid="stBaseButton-primary"]) {
        border-color: #4CAF50 !important;
        color: #2e7d32 !important;
    }

    /* Links verdes */
    a { color: #2e7d32 !important; }
    a:hover { color: #1b5e20 !important; }

    /* Expanders: borda dourada sutil */
    details[data-testid="stExpander"] {
        border-color: #c8a41566 !important;
    }

    /* Divisores: tom dourado */
    .stDivider { border-color: #c8a41544 !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
if "results" not in st.session_state:
    st.session_state["results"] = []
if "email_html" not in st.session_state:
    st.session_state["email_html"] = ""
if "search_done" not in st.session_state:
    st.session_state["search_done"] = False
if "search_terms" not in st.session_state:
    st.session_state["search_terms"] = None  # Will be loaded in sidebar
if "total_searches" not in st.session_state:
    st.session_state["total_searches"] = 0
if "total_minutes_saved" not in st.session_state:
    st.session_state["total_minutes_saved"] = 0
if "llm_classifications" not in st.session_state:
    st.session_state["llm_classifications"] = []
if "llm_filtered" not in st.session_state:
    st.session_state["llm_filtered"] = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_all():
    """Callback: marca todos os checkboxes."""
    for i in range(len(st.session_state["results"])):
        st.session_state[f"sel_{i}"] = True


def _deselect_all():
    """Callback: desmarca todos os checkboxes."""
    for i in range(len(st.session_state["results"])):
        st.session_state[f"sel_{i}"] = False


def _init_checkboxes():
    """Inicializa checkboxes como True para resultados recém-carregados."""
    for i in range(len(st.session_state["results"])):
        if f"sel_{i}" not in st.session_state:
            st.session_state[f"sel_{i}"] = True


def _load_terms_from_github() -> list | None:
    """Carrega termos de busca do GitHub (data/search_terms.json). Retorna None se não encontrar."""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
    except (KeyError, Exception):
        return None

    url = f"https://api.github.com/repos/{repo}/contents/data/search_terms.json"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            content_b64 = resp.json().get("content", "")
            raw = base64.b64decode(content_b64).decode("utf-8")
            terms = json.loads(raw)
            if isinstance(terms, list) and terms:
                return terms
        return None
    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError):
        return None


def _save_terms_to_github(terms: list):
    """Salva termos de busca no GitHub como data/search_terms.json."""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
    except (KeyError, Exception):
        st.error("Secrets GITHUB_TOKEN e/ou GITHUB_REPO não configurados.")
        return

    path = "data/search_terms.json"
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Obter SHA do arquivo existente (necessário para update)
    sha = None
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            sha = resp.json().get("sha")
    except requests.exceptions.RequestException:
        pass

    content_b64 = base64.b64encode(
        json.dumps(terms, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")

    body = {
        "message": "Atualizar termos de busca",
        "content": content_b64,
    }
    if sha:
        body["sha"] = sha

    try:
        resp = requests.put(url, headers=headers, json=body, timeout=30)
        if resp.status_code in (200, 201):
            st.success("Termos salvos no GitHub com sucesso!")
        else:
            st.error(f"Erro ao salvar termos ({resp.status_code}): {resp.text[:300]}")
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com GitHub: {e}")


def _save_to_github(selected_items: list, rejected_items: list, date_display: str):
    """Salva seleção e rejeições como JSON no GitHub via API REST."""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
    except KeyError:
        st.error("Secrets GITHUB_TOKEN e/ou GITHUB_REPO não configurados.")
        return

    now = datetime.now()
    filename = f"selection_{date_display.replace('/', '')}_{now.strftime('%H%M%S')}.json"
    path = f"data/selections/{filename}"

    payload_data = {
        "date": date_display,
        "saved_at": now.isoformat(),
        "selected": selected_items,
        "rejected": rejected_items,
    }
    content_b64 = base64.b64encode(
        json.dumps(payload_data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")

    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    body = {
        "message": f"Clipping {date_display} - seleção salva",
        "content": content_b64,
    }

    try:
        resp = requests.put(url, headers=headers, json=body, timeout=30)
        if resp.status_code in (200, 201):
            st.success(f"Seleção salva no GitHub: {path}")
        else:
            st.error(f"Erro ao salvar no GitHub ({resp.status_code}): {resp.text[:300]}")
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com GitHub: {e}")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        '<h2 style="color:#2e7d32;margin-bottom:0;">Clipping DOU</h2>'
        '<p style="color:#8a7a2a;font-size:14px;margin-top:0;">NUATI · Câmara dos Deputados</p>',
        unsafe_allow_html=True,
    )

    st.subheader("Período de busca")
    col_ini, col_fim = st.columns(2)
    with col_ini:
        data_inicial = st.date_input(
            "Data inicial",
            value=date.today(),
            max_value=date.today(),
            format="DD/MM/YYYY",
        )
    with col_fim:
        data_final = st.date_input(
            "Data final",
            value=date.today(),
            max_value=date.today(),
            format="DD/MM/YYYY",
        )

    _datas_invalidas = data_inicial > data_final
    _intervalo_excedido = (data_final - data_inicial).days > 30

    if _datas_invalidas:
        st.warning("Data inicial deve ser anterior ou igual à data final.")
    elif _intervalo_excedido:
        st.warning("Intervalo máximo de 30 dias.")

    buscar = st.button(
        "Buscar",
        type="primary",
        use_container_width=True,
        disabled=(_datas_invalidas or _intervalo_excedido),
    )

    st.divider()

    # Inicializar termos: GitHub -> padrão
    if st.session_state["search_terms"] is None:
        github_terms = _load_terms_from_github()
        st.session_state["search_terms"] = github_terms if github_terms else list(SEARCH_TERMS)

    with st.expander("Termos de busca"):
        current_terms = st.session_state["search_terms"]
        st.caption(f"{len(current_terms)} termos configurados")

        terms_text = st.text_area(
            "Editar termos (um por linha)",
            value="\n".join(current_terms),
            height=300,
            key="terms_text_area",
        )

        col_apply, col_restore = st.columns(2)
        with col_apply:
            if st.button("Aplicar", use_container_width=True):
                new_terms = [t.strip() for t in terms_text.strip().split("\n") if t.strip()]
                st.session_state["search_terms"] = new_terms
                st.success(f"{len(new_terms)} termos aplicados.")
                st.rerun()
        with col_restore:
            if st.button("Restaurar padrão", use_container_width=True):
                st.session_state["search_terms"] = list(SEARCH_TERMS)
                st.success("Termos restaurados.")
                st.rerun()

        if st.button("Salvar termos no GitHub", use_container_width=True):
            parsed = [t.strip() for t in terms_text.strip().split("\n") if t.strip()]
            st.session_state["search_terms"] = parsed
            with st.spinner("Salvando no GitHub..."):
                _save_terms_to_github(parsed)

        st.divider()
        if st.button("Sugerir novos termos com IA", use_container_width=True):
            try:
                api_key = st.secrets.get("GEMINI_API_KEY", "")
                if not api_key:
                    st.error("GEMINI_API_KEY não configurada nos Secrets.")
                else:
                    from llm_engine import LLMEngine

                    llm_cfg = get_llm_config()
                    engine = LLMEngine(
                        api_key=api_key,
                        provider=llm_cfg.get("provider", "gemini"),
                        model=llm_cfg.get("modelo", "gemini-2.5-flash"),
                    )
                    with st.spinner("Consultando IA..."):
                        suggestions = engine.enrich_terms(st.session_state["search_terms"])
                    if suggestions:
                        st.success(f"{len(suggestions)} sugestões recebidas!")
                        for s in suggestions:
                            col_add, col_text = st.columns([0.15, 0.85])
                            with col_add:
                                add_it = st.checkbox("", key=f"add_term_{s['termo']}", value=False)
                            with col_text:
                                st.markdown(
                                    f"**{s['termo']}** ({s['categoria']})<br>"
                                    f"<small>{s['justificativa']}</small>",
                                    unsafe_allow_html=True,
                                )
                            if add_it and s["termo"] not in st.session_state["search_terms"]:
                                st.session_state["search_terms"].append(s["termo"])
                    else:
                        st.warning("Nenhuma sugestão retornada.")
            except Exception as e:
                st.error(f"Erro: {e}")

# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------
if buscar and data_inicial <= data_final:
    # Limpar estado anterior
    st.session_state["results"] = []
    st.session_state["email_html"] = ""
    st.session_state["search_done"] = False
    # Limpar checkboxes antigos
    keys_to_remove = [k for k in st.session_state if k.startswith("sel_")]
    for k in keys_to_remove:
        del st.session_state[k]

    # Gerar lista de datas
    delta = (data_final - data_inicial).days
    dates = [data_inicial + timedelta(days=d) for d in range(delta + 1)]

    all_items = []

    with st.status(f"Buscando publicações para {len(dates)} data(s)...", expanded=True) as status:
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        try:
            for date_idx, dt in enumerate(dates):
                date_obj = datetime(dt.year, dt.month, dt.day)
                date_str = date_obj.strftime("%d-%m-%Y")
                date_display = date_obj.strftime("%d/%m/%Y")

                status_text.write(f"**DOU {date_display}** - Iniciando busca...")

                # Callback de progresso para search_all_terms
                def make_progress_cb(d_idx, total_dates, d_display):
                    def progress_cb(current, total, message):
                        # Progresso global: combina progresso da data atual com índice da data
                        date_fraction = d_idx / total_dates
                        step_fraction = (current / total) / total_dates if total > 0 else 0
                        overall = date_fraction + step_fraction
                        progress_bar.progress(min(overall, 0.99))
                        status_text.write(f"**DOU {d_display}** - {message}")
                    return progress_cb

                cb = make_progress_cb(date_idx, len(dates), date_display)

                # Busca DOU
                secao2_rules = get_secao2_rules()
                items = search_all_terms(
                    st.session_state["search_terms"], date_str,
                    progress_callback=cb,
                    secao2_rules=secao2_rules if secao2_rules else None,
                )
                all_items.extend(items)

                # Busca Boletim Administrativo
                status_text.write(f"**BA {date_display}** - Buscando Boletim Administrativo...")
                stem_entries = get_stems()
                stem_patterns_list = get_stem_patterns()
                ba_items = fetch_boletim_items(
                    date_obj,
                    terms=st.session_state["search_terms"],
                    stem_entries=stem_entries,
                    stem_patterns=stem_patterns_list,
                )
                all_items.extend(ba_items)
        except Exception as e:
            st.error(f"Erro durante a busca: {e}")
            st.stop()

        progress_bar.progress(1.0)
        status_text.write(f"Busca concluída! **{len(all_items)}** publicação(ões) encontrada(s).")
        status.update(label=f"Busca concluída - {len(all_items)} publicações", state="complete")

    # Ordenar por data
    all_items.sort(key=lambda x: x.get("date", ""))

    st.session_state["results"] = all_items
    st.session_state["search_done"] = True
    _init_checkboxes()

    # Contabilizar tempo economizado
    num_terms = len(st.session_state["search_terms"] or [])
    num_dates = len(dates)
    minutes_saved = _estimate_time_saved(num_terms, num_dates)
    st.session_state["total_searches"] += 1
    st.session_state["total_minutes_saved"] += minutes_saved

# ---------------------------------------------------------------------------
# Lista de resultados
# ---------------------------------------------------------------------------
results = st.session_state["results"]

if st.session_state["search_done"] and results:
    # --- Cabeçalho com contagem + estatísticas por palavra-chave ---
    col_header, col_stats = st.columns([3, 1])
    with col_header:
        st.header(f"{len(results)} publicação(ões) encontrada(s)")
    with col_stats:
        st.write("")  # espaçamento vertical
        _show_stats = st.toggle("Estatísticas por termo", value=False)

    if _show_stats:
        # Contar publicações por palavra-chave (found_by)
        term_counts: dict[str, int] = {}
        for item in results:
            found_by = item.get("found_by", "N/A")
            # found_by pode ter múltiplos termos separados por ", "
            for term in found_by.split(", "):
                term = term.strip()
                if term:
                    term_counts[term] = term_counts.get(term, 0) + 1
        # Ordenar por contagem decrescente
        sorted_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)
        with st.container(border=True):
            for term, count in sorted_terms:
                st.markdown(f"- **{term}**: {count} publicação(ões)")

    # Botões de seleção em massa
    col_sel, col_desel, _ = st.columns([1, 1, 4])
    with col_sel:
        st.button("Selecionar todos", on_click=_select_all, use_container_width=True)
    with col_desel:
        st.button("Desmarcar todos", on_click=_deselect_all, use_container_width=True)

    # Renderizar cada publicação
    for i, item in enumerate(results):
        col_check, col_content = st.columns([0.05, 0.95])

        with col_check:
            st.checkbox(
                label="sel",
                key=f"sel_{i}",
                label_visibility="collapsed",
            )

        with col_content:
            # --- Resumo visível SEM precisar expandir ---
            found_by = item.get("found_by", "N/A")

            # Ementa: para atos normativos (Seção 1 com full_text), extrair
            # tudo antes de "RESOLVE", "Art.", "DECRETA", etc.
            # Para Seção 3 e outros, usar abstract da API.
            full_text = item.get("full_text")
            ementa_raw = ""
            if full_text:
                # Encontrar onde começa o dispositivo (parte normativa)
                import re as _re
                corte = _re.search(
                    r'\n\s*(RESOLVE|DETERMINA|DECRETA|ACORDAM|Art\.\s*1|CONSIDERANDO)',
                    full_text,
                    _re.IGNORECASE,
                )
                if corte:
                    ementa_raw = full_text[:corte.start()].strip()
                else:
                    # Sem padrão de corte: pegar primeiras linhas
                    linhas = full_text.split("\n")
                    ementa_raw = "\n".join(linhas[:3]).strip()
                # Limitar tamanho
                if len(ementa_raw) > 350:
                    ementa_raw = ementa_raw[:350].rsplit(" ", 1)[0] + "..."
            if not ementa_raw:
                abstract_raw = clean_html(item.get("abstract", "")).strip()
                ementa_raw = abstract_raw[:250]
                if len(ementa_raw) >= 250:
                    ementa_raw = ementa_raw.rsplit(" ", 1)[0] + "..."

            # Órgão e seção em linha compacta
            orgao = item.get("hierarchy", "")
            if item["section"] == "BA":
                secao_info = "Boletim Administrativo"
            else:
                secao_info = f"Seção {get_section_display(item['section'])}"

            st.markdown(
                f"**{item['title']}**\n\n"
                f"<small style='color:#666'>"
                f"<b>Termo:</b> {html_module.escape(found_by)} · "
                f"<b>Órgão:</b> {html_module.escape(orgao)} · "
                f"{html_module.escape(secao_info)} · "
                f"{html_module.escape(item.get('date', ''))}"
                f"</small>\n\n"
                f"<span style='color:#444'>{html_module.escape(ementa_raw)}</span>",
                unsafe_allow_html=True,
            )

            # --- Detalhes completos no expander ---
            with st.expander("Ver detalhes completos", expanded=False):
                # Metadados
                if item["section"] == "BA":
                    st.markdown(f"**Data:** {item['date']} | **Boletim Administrativo da Câmara dos Deputados**")
                else:
                    section_display = get_section_display(item["section"])
                    page_str = f" | **Página:** {item['page']}" if item.get('page') else ""
                    st.markdown(f"**Data:** {item['date']} | **Edição:** {item['edition']} | **Seção:** {section_display}{page_str}")

                st.markdown(f"**Órgão:** {item['hierarchy']}")
                st.markdown(f"**Link:** [{item['href']}]({item['href']})")
                st.markdown(f"**Encontrado por:** `{found_by}`")

                # Texto com highlight — use context windows
                display_cfg = get_display_config()
                toggle_max = display_cfg.get("toggle_max_chars", 2000)
                ctx_before = display_cfg.get("contexto_chars_antes", 300)
                ctx_after = display_cfg.get("contexto_chars_depois", 300)

                if full_text:
                    windowed = extract_context_windows(
                        full_text,
                        st.session_state["search_terms"],
                        stem_patterns=get_stem_patterns(),
                        chars_before=ctx_before,
                        chars_after=ctx_after,
                        max_total=toggle_max,
                    )
                    text_html = html_module.escape(windowed)
                    text_html = text_html.replace("\n", "<br>")
                    text_html = highlight_all(text_html, st.session_state["search_terms"], get_stem_patterns())
                else:
                    text_html = highlight_all(
                        html_module.escape(clean_html(item.get("abstract", ""))),
                        st.session_state["search_terms"],
                        get_stem_patterns(),
                    )

                # Style [...] markers
                text_html = text_html.replace("[...]", '<span style="color:#999;font-style:italic">[...]</span>')

                # Wrapper com estilo para o conteúdo HTML
                styled_html = f"""
                <div style="font-family: Arial, sans-serif; font-size: 14px;
                            line-height: 1.6; padding: 10px; max-height: 400px;
                            overflow-y: auto; background: #fafafa; border-radius: 4px;">
                    {text_html}
                </div>
                """
                components.html(styled_html, height=300, scrolling=True)

        st.divider()

    # -------------------------------------------------------------------
    # LLM Filtering (Etapa 2 — optional)
    # -------------------------------------------------------------------
    st.divider()
    col_llm, col_llm_info = st.columns([1, 3])
    with col_llm:
        filtrar_llm = st.button("Filtrar com IA", use_container_width=True)
    with col_llm_info:
        st.caption(
            "Usa Gemini Flash 2.5 para classificar a relevância de cada resultado. "
            "Itens filtrados ficam disponíveis para conferência."
        )

    if filtrar_llm:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY", "")
            if not api_key:
                st.error("GEMINI_API_KEY não configurada nos Secrets.")
            else:
                from llm_engine import LLMEngine, load_guidelines

                llm_cfg = get_llm_config()
                engine = LLMEngine(
                    api_key=api_key,
                    provider=llm_cfg.get("provider", "gemini"),
                    model=llm_cfg.get("modelo", "gemini-2.5-flash"),
                )
                guidelines = load_guidelines()

                with st.status("Filtrando com IA...", expanded=True) as llm_status:
                    progress_text = st.empty()
                    classifications = []
                    for idx, item in enumerate(results):
                        progress_text.write(
                            f"Analisando {idx+1}/{len(results)}: {item['title'][:50]}..."
                        )
                        cls = engine.filter_single(item, guidelines)
                        cls["index"] = idx
                        classifications.append(cls)
                        if idx < len(results) - 1:
                            time.sleep(1)

                    # Apply: uncheck NAO_RELEVANTE
                    for cls in classifications:
                        if cls["classificacao"] == "NAO_RELEVANTE":
                            st.session_state[f"sel_{cls['index']}"] = False

                    st.session_state["llm_classifications"] = classifications
                    st.session_state["llm_filtered"] = True

                    n_relevant = sum(1 for c in classifications if c["classificacao"] == "RELEVANTE")
                    n_partial = sum(1 for c in classifications if c["classificacao"] == "PARCIALMENTE_RELEVANTE")
                    n_irrelevant = sum(1 for c in classifications if c["classificacao"] == "NAO_RELEVANTE")

                    llm_status.update(
                        label=f"Filtragem concluída — {n_relevant} relevantes, {n_partial} parciais, {n_irrelevant} filtrados",
                        state="complete",
                    )
                st.rerun()
        except Exception as e:
            st.error(f"Erro na filtragem por LLM: {e}")

    # Show filtered items (if LLM filtering was done)
    if st.session_state.get("llm_filtered"):
        classifications = st.session_state.get("llm_classifications", [])
        filtered_items = [
            (cls, results[cls["index"]])
            for cls in classifications
            if cls["classificacao"] == "NAO_RELEVANTE" and cls["index"] < len(results)
        ]
        if filtered_items:
            with st.expander(f"Filtrados pelo LLM ({len(filtered_items)} itens)", expanded=False):
                for cls, fitem in filtered_items:
                    st.markdown(
                        f"**{fitem['title']}**\n\n"
                        f"<small style='color:#666'>"
                        f"Justificativa: {html_module.escape(cls['justificativa'])} "
                        f"(confiança: {cls['confianca']:.0%})"
                        f"</small>",
                        unsafe_allow_html=True,
                    )
                    idx = cls["index"]
                    if st.checkbox(f"Re-incluir: {fitem['title'][:40]}...", key=f"reinclude_{idx}", value=False):
                        st.session_state[f"sel_{idx}"] = True
                    st.divider()

    # -------------------------------------------------------------------
    # Geração do email
    # -------------------------------------------------------------------
    st.divider()
    st.subheader("Gerar relatório")

    col_gerar, col_salvar = st.columns([1, 1])

    with col_gerar:
        if st.button("Gerar Relatório", type="primary", use_container_width=True):
            selected_items = [
                item for i, item in enumerate(results)
                if st.session_state.get(f"sel_{i}", False)
            ]

            if not selected_items:
                st.warning("Nenhuma publicação selecionada.")
            else:
                # Montar date_display a partir dos itens
                item_dates = sorted(set(item.get("date", "") for item in selected_items))
                if len(item_dates) == 1:
                    date_display = item_dates[0]
                else:
                    date_display = f"{item_dates[0]} a {item_dates[-1]}"

                email_html = generate_email_body(
                    selected_items,
                    date_display,
                    search_terms=st.session_state["search_terms"],
                    terms_display="\n".join(st.session_state["search_terms"]),
                    stem_patterns=get_stem_patterns(),
                )
                st.session_state["email_html"] = email_html
                st.success(f"Relatório gerado com {len(selected_items)} publicação(ões).")

    with col_salvar:
        if st.button("Salvar seleção no GitHub", use_container_width=True):
            selected = [
                item for i, item in enumerate(results)
                if st.session_state.get(f"sel_{i}", False)
            ]
            rejected = [
                item for i, item in enumerate(results)
                if not st.session_state.get(f"sel_{i}", False)
            ]
            item_dates = sorted(set(item.get("date", "") for item in results))
            date_display = item_dates[0] if len(item_dates) == 1 else f"{item_dates[0]} a {item_dates[-1]}"
            with st.spinner("Salvando no GitHub..."):
                _save_to_github(selected, rejected, date_display)

    # -------------------------------------------------------------------
    # Preview e download do email
    # -------------------------------------------------------------------
    email_html = st.session_state.get("email_html", "")
    if email_html:
        st.divider()

        # Botões de ação
        col_download, col_copy, _ = st.columns([1, 1, 2])

        with col_download:
            # Construir nome do arquivo
            item_dates = sorted(set(item.get("date", "").replace("/", "") for item in results if item.get("date")))
            if len(item_dates) == 1:
                file_suffix = item_dates[0]
            elif item_dates:
                file_suffix = f"{item_dates[0]}_{item_dates[-1]}"
            else:
                file_suffix = date.today().strftime("%d%m%Y")

            st.download_button(
                label="Baixar .htm",
                data=email_html.encode("utf-8"),
                file_name=f"DOU_{file_suffix}.htm",
                mime="text/html",
                use_container_width=True,
            )

        with col_copy:
            # Botão de copiar HTML rico via JavaScript dentro do iframe
            # O clique do usuário no botão DENTRO do iframe fornece o "user gesture"
            # necessário para a Clipboard API funcionar
            import json as _json
            html_json = _json.dumps(email_html)
            js_code = f"""
            <html><body style="margin:0;padding:0;font-family:Arial,sans-serif;">
            <button id="copyBtn" onclick="doCopy()" style="
                width:100%;padding:10px 16px;font-size:14px;font-weight:bold;
                background:#4CAF50;color:white;border:none;border-radius:6px;
                cursor:pointer;">
                Copiar HTML para a area de transferencia
            </button>
            <div id="toast" style="display:none;width:100%;text-align:center;padding:6px 0;
                font-size:12px;border-radius:4px;margin-top:4px;font-weight:bold;"></div>
            <script>
            var rawHtml = {html_json};

            function showToast(msg, ok) {{
                var t = document.getElementById('toast');
                t.textContent = msg;
                t.style.display = 'block';
                t.style.background = ok ? '#28a745' : '#dc3545';
                t.style.color = 'white';
                var btn = document.getElementById('copyBtn');
                btn.textContent = ok ? 'Copiado!' : 'Erro';
                btn.style.background = ok ? '#28a745' : '#dc3545';
            }}

            function doCopy() {{
                // Tentar ClipboardItem (melhor: copia como HTML rico)
                if (typeof ClipboardItem !== 'undefined') {{
                    var blob = new Blob([rawHtml], {{type: 'text/html'}});
                    navigator.clipboard.write([new ClipboardItem({{'text/html': blob}})])
                        .then(function() {{ showToast('HTML copiado! Cole no Outlook com Ctrl+V.', true); }})
                        .catch(function() {{ fallbackCopy(); }});
                }} else {{
                    fallbackCopy();
                }}
            }}

            function fallbackCopy() {{
                // Fallback: execCommand com contentEditable
                var div = document.createElement('div');
                div.contentEditable = true;
                div.innerHTML = rawHtml;
                div.style.position = 'fixed';
                div.style.left = '-9999px';
                document.body.appendChild(div);
                var range = document.createRange();
                range.selectNodeContents(div);
                var sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                var ok = document.execCommand('copy');
                sel.removeAllRanges();
                document.body.removeChild(div);
                if (ok) {{
                    showToast('HTML copiado! Cole no Outlook com Ctrl+V.', true);
                }} else {{
                    showToast('Nao foi possivel copiar. Use Baixar .htm.', false);
                }}
            }}
            </script>
            </body></html>
            """
            components.html(js_code, height=70)

        # Preview
        with st.expander("Preview do email", expanded=False):
            components.html(email_html, height=600, scrolling=True)

elif st.session_state["search_done"] and not results:
    st.info("Nenhuma publicação encontrada para o período selecionado.")

elif not st.session_state["search_done"]:
    st.markdown(
        '<div style="text-align:center;padding:60px 20px;">'
        '<h1 style="color:#2e7d32;">Clipping do Diário Oficial da União</h1>'
        '<p style="color:#666;font-size:18px;">Núcleo de Auditoria de TI · Câmara dos Deputados</p>'
        '<hr style="border:2px solid #c8a415;width:100px;margin:20px auto;">'
        '<p style="color:#888;">Selecione o período na barra lateral e clique em <b>Buscar</b>.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Rodape
# ---------------------------------------------------------------------------
_num_terms = len(st.session_state.get("search_terms") or SEARCH_TERMS)
_minutes_per_search = _estimate_time_saved(_num_terms)

# Texto de economia acumulada na sessao
_total_searches = st.session_state.get("total_searches", 0)
_total_saved = st.session_state.get("total_minutes_saved", 0)

if _total_saved >= 60:
    _saved_display = f"{_total_saved // 60}h{_total_saved % 60:02d}min"
else:
    _saved_display = f"{_total_saved} min"

if _total_searches > 0:
    _economy_line = (
        f"Tempo economizado nesta sessao: <b>{_saved_display}</b> "
        f"({_total_searches} busca(s) · ~{_minutes_per_search} min cada)"
    )
else:
    _economy_line = (
        f"Cada busca automatiza ~<b>{_minutes_per_search} min</b> de trabalho manual "
        f"({_num_terms} termos pesquisados automaticamente)"
    )

st.markdown(
    f"""
    <hr style="border:1px solid #c8a41544;margin-top:40px;">
    <div style="text-align:center;padding:12px 0 20px 0;color:#888;font-size:13px;">
        <p style="margin:2px 0;">{_economy_line}</p>
        <p style="margin:2px 0;">Feito por <b>{APP_AUTHOR}</b> · Versao {APP_VERSION}</p>
    </div>
    """,
    unsafe_allow_html=True,
)
