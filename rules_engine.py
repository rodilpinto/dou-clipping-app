# =============================================================================
# rules_engine.py — Central configuration loader for DOU Clipping NUATI
# =============================================================================
# Reads data/rules.yaml and exposes all configuration to the rest of the app.
# Caches parsed YAML with mtime tracking for automatic reload on file change.
# =============================================================================

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_cache: dict = {}
_yaml_mtime: float = 0.0

# Default path: data/rules.yaml relative to this module
_DEFAULT_YAML_PATH: Path = Path(__file__).parent / "data" / "rules.yaml"

# ---------------------------------------------------------------------------
# Fallback search terms (from dou_clipping.py — 44 terms)
# ---------------------------------------------------------------------------
_FALLBACK_SEARCH_TERMS: list[str] = [
    "Câmara dos Deputados",
    "Tecnologia da informação",
    "Tecnologia da Informação e Comunicação",
    "Soluções de TI",
    "Soluções de TIC",
    "Transformação digital",
    "Inovação tecnológica",
    "Computação em nuvem",
    "Auditoria de TI",
    "Auditoria de TIC",
    "Auditoria interna",
    "AudTI",
    "COSO",
    "COBIT",
    "Itil",
    "BPM",
    "Governança corporativa",
    "Governança de TI",
    "Governança de TIC",
    "Governança de aquisições",
    "Governança de contratações",
    "Governança digital",
    "Gestão de aquisições",
    "Gestão de contratações",
    "Gestão de contratos",
    "Fiscalização de contratos",
    "Fiscal de contrato",
    "Controle interno",
    "Controles internos",
    "Controladoria",
    "Indicadores",
    "Riscos",
    "Gestão de riscos",
    "Processos críticos",
    "Continuidade de negócios",
    "Segurança de informação",
    "Segurança da informação",
    "Cibersegurança",
    "Segurança cibernética",
    "Gestão de processos",
    "Melhoria de processos",
    "Dados abertos",
    "Dados em formatos abertos",
    "Proteção de dados",
    "LGPD",
    "Transparência da informação",
    "Lei de Acesso à Informação",
    "LAI",
    "Fábrica de Software",
    "Ponto de função",
    "Pontos de função",
    "Processo de software",
    "Hackers",
    "Hacktivismo",
    "Secretaria de Fiscalização de Tecnologia da Informação",
    "Sefti",
    "Inteligência artificial",
    "Ciência de dados",
    "Aprendizado de máquina",
    "Machine learning",
    "Compliance",
    "Conformidade",
]


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def load_rules(yaml_path: Optional[str] = None) -> dict:
    """Load and cache the YAML rules file.

    Uses module-level cache with mtime tracking so the file is re-read
    automatically whenever it changes on disk.

    Parameters
    ----------
    yaml_path : str or None
        Explicit path to the YAML file.  When *None*, defaults to
        ``data/rules.yaml`` relative to this module's directory.

    Returns
    -------
    dict
        Parsed YAML content, or a sensible defaults dict if the file is
        missing.
    """
    global _cache, _yaml_mtime

    path = Path(yaml_path) if yaml_path else _DEFAULT_YAML_PATH

    # Check mtime — reload only when file has changed
    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        # File does not exist — return defaults
        if not _cache:
            _cache = _build_fallback_rules()
        return _cache

    if _cache and current_mtime == _yaml_mtime:
        return _cache

    # (Re)load
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        if not _cache:
            _cache = _build_fallback_rules()
        return _cache

    _yaml_mtime = current_mtime
    _cache = data
    return _cache


def _build_fallback_rules() -> dict:
    """Return a minimal rules dict when the YAML file is unavailable."""
    return {
        "termos_busca": list(_FALLBACK_SEARCH_TERMS),
        "radicais": [],
        "secoes": {},
        "regras_positivas": [],
        "regras_negativas": [],
        "split_atos": {"habilitado": False, "padroes": []},
        "display": {},
        "llm": {},
    }


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------

def get_search_terms() -> list[str]:
    """Return the ``termos_busca`` list."""
    rules = load_rules()
    return list(rules.get("termos_busca", _FALLBACK_SEARCH_TERMS))


def get_stems() -> list[dict]:
    """Return the ``radicais`` list (each dict has ``radical`` and ``descricao``)."""
    rules = load_rules()
    return list(rules.get("radicais", []))


def get_stem_patterns() -> list[re.Pattern]:
    r"""Return compiled regex patterns for each stem.

    Pattern per stem: ``\b{radical}\w*`` — case-insensitive, Unicode.
    """
    stems = get_stems()
    patterns: list[re.Pattern] = []
    for entry in stems:
        radical = entry.get("radical", "")
        if radical:
            patterns.append(
                re.compile(rf"\b{re.escape(radical)}\w*", re.IGNORECASE | re.UNICODE)
            )
    return patterns


def get_section_config(section: str) -> dict:
    """Return config for a section key (e.g. ``secao_1``, ``boletim_administrativo``).

    Returns an empty dict if the section does not exist.
    """
    rules = load_rules()
    secoes = rules.get("secoes", {})
    return dict(secoes.get(section, {}))


def get_secao2_rules() -> list[dict]:
    """Return appointment rules for Secao 2 with pre-compiled ``padrao_fc`` regex."""
    config = get_section_config("secao_2")
    raw_rules = config.get("regras", [])
    compiled: list[dict] = []
    for rule in raw_rules:
        entry = dict(rule)
        filtro = entry.get("filtro", {})
        padrao_fc = filtro.get("padrao_fc")
        if padrao_fc and isinstance(padrao_fc, str):
            filtro = dict(filtro)
            filtro["padrao_fc_compiled"] = re.compile(
                padrao_fc, re.IGNORECASE | re.UNICODE
            )
            entry["filtro"] = filtro
        compiled.append(entry)
    return compiled


def get_positive_rules() -> list[dict]:
    """Return positive rules (``regras_positivas``)."""
    rules = load_rules()
    return list(rules.get("regras_positivas", []))


def get_negative_rules() -> list[dict]:
    """Return negative rules (``regras_negativas``)."""
    rules = load_rules()
    return list(rules.get("regras_negativas", []))


def get_split_patterns() -> list[dict]:
    """Return split patterns with pre-compiled ``regex_separador`` and ``titulo_regex``."""
    rules = load_rules()
    split_cfg = rules.get("split_atos", {})
    raw_patterns = split_cfg.get("padroes", [])
    compiled: list[dict] = []
    for pat in raw_patterns:
        entry = dict(pat)
        sep = entry.get("regex_separador")
        if sep and isinstance(sep, str):
            entry["regex_separador_compiled"] = re.compile(
                sep, re.IGNORECASE | re.UNICODE
            )
        titulo = entry.get("titulo_regex")
        if titulo and isinstance(titulo, str):
            entry["titulo_regex_compiled"] = re.compile(
                titulo, re.IGNORECASE | re.UNICODE
            )
        compiled.append(entry)
    return compiled


def get_display_config() -> dict:
    """Return the ``display`` config dict."""
    rules = load_rules()
    return dict(rules.get("display", {}))


def get_llm_config() -> dict:
    """Return the ``llm`` config dict."""
    rules = load_rules()
    return dict(rules.get("llm", {}))


def get_terms_display() -> str:
    """Return a formatted string of all terms for the report footer.

    Format: one line per exact term, then a section ``Radicais:`` with each
    stem and its description.
    """
    terms = get_search_terms()
    stems = get_stems()

    lines: list[str] = []
    for term in terms:
        lines.append(term)

    if stems:
        lines.append("")
        lines.append("Radicais:")
        for entry in stems:
            radical = entry.get("radical", "")
            descricao = entry.get("descricao", "")
            if radical:
                lines.append(f"  {radical} — {descricao}")

    return "\n".join(lines)


def get_all_match_patterns(terms: Optional[list[str]] = None) -> list[re.Pattern]:
    r"""Return compiled patterns for both exact terms and stems.

    Exact terms use ``re.escape`` so special characters are matched literally.
    Stems use ``\b{radical}\w*``.  All patterns are case-insensitive with
    Unicode support.

    Parameters
    ----------
    terms : list[str] or None
        Override list of exact terms.  When *None*, uses ``get_search_terms()``.
    """
    if terms is None:
        terms = get_search_terms()

    patterns: list[re.Pattern] = []

    # Exact term patterns
    for term in terms:
        patterns.append(
            re.compile(re.escape(term), re.IGNORECASE | re.UNICODE)
        )

    # Stem patterns
    for entry in get_stems():
        radical = entry.get("radical", "")
        if radical:
            patterns.append(
                re.compile(rf"\b{re.escape(radical)}\w*", re.IGNORECASE | re.UNICODE)
            )

    return patterns
