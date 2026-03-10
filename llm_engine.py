"""
LLM Engine for DOU Clipping — NUATI

Handles LLM integration for two features:
1. Term enrichment — suggest new search terms based on current ones
2. Result filtering — classify search results by relevance

Provider: Gemini Flash 2.5 via google-genai SDK.
Future: Ollama for local models.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models for structured output
# ---------------------------------------------------------------------------

class TermSuggestion(BaseModel):
    """A single term suggestion from the LLM."""
    termo: str
    justificativa: str
    categoria: str


class TermSuggestions(BaseModel):
    """Wrapper for a list of term suggestions."""
    sugestoes: list[TermSuggestion]


class FilterResult(BaseModel):
    """Classification result for a single DOU item."""
    classificacao: str   # RELEVANTE | PARCIALMENTE_RELEVANTE | NAO_RELEVANTE
    justificativa: str
    confianca: float


# ---------------------------------------------------------------------------
# Helper — load guidelines
# ---------------------------------------------------------------------------

_GUIDELINES_PATH = Path(__file__).resolve().parent / "docs" / "LLM_GUIDELINES.md"


def load_guidelines() -> str:
    """Load the LLM_GUIDELINES.md content used as system context for filtering.

    Returns:
        The full text of LLM_GUIDELINES.md, or an empty string if the file
        cannot be read.
    """
    try:
        return _GUIDELINES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("LLM_GUIDELINES.md not found at %s", _GUIDELINES_PATH)
        return ""
    except OSError as exc:
        logger.warning("Failed to read LLM_GUIDELINES.md: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# LLMEngine
# ---------------------------------------------------------------------------

class LLMEngine:
    """LLM integration for DOU clipping — supports Gemini and future Ollama."""

    _MAX_RETRIES = 3
    _RATE_LIMIT_DELAY = 1.0  # seconds between filter_single calls

    def __init__(
        self,
        api_key: str,
        provider: str = "gemini",
        model: str = "gemini-2.5-flash",
    ) -> None:
        """Initialize with API key and provider config.

        Args:
            api_key: API key for the chosen provider.
            provider: ``"gemini"`` (default) or ``"ollama"`` (future).
            model: Model identifier (e.g. ``"gemini-2.5-flash"``).

        Raises:
            NotImplementedError: If *provider* is not ``"gemini"``.
        """
        self.provider = provider
        self.model = model

        if provider == "gemini":
            self.client = genai.Client(api_key=api_key)
        elif provider == "ollama":
            raise NotImplementedError(
                "Ollama provider is not yet implemented. "
                "Contributions welcome!"
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider!r}")

        logger.info(
            "LLMEngine initialized — provider=%s, model=%s",
            provider,
            model,
        )

    # ------------------------------------------------------------------
    # Term enrichment
    # ------------------------------------------------------------------

    def enrich_terms(
        self,
        current_terms: list[str],
        context: str = "",
    ) -> list[dict]:
        """Suggest new search terms based on current ones.

        The LLM is asked to propose 10-20 new terms relevant to *auditoria
        de TI e governança no setor público brasileiro*, avoiding terms that
        are already in *current_terms*.

        Args:
            current_terms: Current list of search terms.
            context: Optional additional context (e.g.
                ``"auditoria de TI no setor público"``).

        Returns:
            A list of dicts, each with keys ``termo``, ``justificativa``,
            and ``categoria``.  Returns an empty list on unrecoverable error.
        """
        terms_block = "\n".join(f"- {t}" for t in current_terms)
        context_line = context or (
            "auditoria de TI e governança no setor público brasileiro"
        )

        prompt = (
            "Você é um especialista em auditoria governamental e tecnologia "
            "da informação no setor público brasileiro.\n\n"
            f"Contexto temático: {context_line}\n\n"
            "Abaixo estão os termos de busca já utilizados para monitorar o "
            "Diário Oficial da União (DOU):\n\n"
            f"{terms_block}\n\n"
            "Sugira entre 10 e 20 NOVOS termos de busca que:\n"
            "1. Sejam relevantes para auditoria de TI, governança, controle "
            "interno e segurança da informação no setor público.\n"
            "2. NÃO repitam nenhum termo já listado acima.\n"
            "3. Incluam siglas, nomes de normas, frameworks ou conceitos que "
            "possam aparecer em publicações oficiais.\n\n"
            "Para cada termo, forneça:\n"
            "- termo: o termo de busca exato\n"
            "- justificativa: por que este termo é relevante (1 frase)\n"
            "- categoria: uma das seguintes — Normativos, Tecnologia, "
            "Auditoria, Governança, Segurança, Dados, Gestão, Outro\n\n"
            "Responda SOMENTE com o JSON solicitado."
        )

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TermSuggestions,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        response_text = self._call_with_retry(prompt, config)
        if response_text is None:
            return []

        try:
            parsed = TermSuggestions.model_validate_json(response_text)
            return [s.model_dump() for s in parsed.sugestoes]
        except Exception as exc:
            logger.warning(
                "Failed to parse enrich_terms response: %s", exc,
            )
            return []

    # ------------------------------------------------------------------
    # Result filtering (batch)
    # ------------------------------------------------------------------

    def filter_results(
        self,
        items: list[dict],
        guidelines: str,
    ) -> list[dict]:
        """Classify each result by relevance using the LLM.

        Iterates over *items*, calling :meth:`filter_single` for each one
        with a short delay to respect rate limits.

        Args:
            items: List of DOU result dicts.  Each is expected to have keys
                such as ``title``, ``hierarchy``, ``abstract`` or
                ``full_text``, ``found_by``, and ``section``.
            guidelines: The content of ``LLM_GUIDELINES.md``.

        Returns:
            A list of dicts, one per item, each containing ``index``,
            ``classificacao``, ``justificativa``, and ``confianca``.
        """
        results: list[dict] = []

        for idx, item in enumerate(items):
            try:
                classification = self.filter_single(item, guidelines)
                classification["index"] = idx
                results.append(classification)
            except Exception as exc:
                logger.warning(
                    "filter_results — item %d failed (%s). "
                    "Defaulting to RELEVANTE (safety principle).",
                    idx,
                    exc,
                )
                results.append({
                    "index": idx,
                    "classificacao": "RELEVANTE",
                    "justificativa": (
                        "Erro na classificação automática — mantido como "
                        "relevante por segurança."
                    ),
                    "confianca": 0.0,
                })

            # Rate-limit delay between calls (skip after last item)
            if idx < len(items) - 1:
                time.sleep(self._RATE_LIMIT_DELAY)

        return results

    # ------------------------------------------------------------------
    # Result filtering (single item)
    # ------------------------------------------------------------------

    def filter_single(self, item: dict, guidelines: str) -> dict:
        """Classify a single DOU result item by relevance.

        Args:
            item: A dict with keys like ``title``, ``hierarchy``,
                ``abstract``/``full_text``, ``found_by``, ``section``.
            guidelines: The LLM_GUIDELINES.md content.

        Returns:
            A dict with ``classificacao``, ``justificativa``, and
            ``confianca``.  On unrecoverable error, returns a safe default
            (``RELEVANTE``).
        """
        title = item.get("title", "Sem título")
        hierarchy = item.get("hierarchy", "Não informado")
        section = item.get("section", "Não informada")
        found_by = item.get("found_by", "Não informado")

        # Prefer abstract; fall back to full_text (truncated)
        body = item.get("abstract") or item.get("full_text") or ""
        if len(body) > 2000:
            body = body[:2000] + " [...]"

        prompt = (
            f"{guidelines}\n\n"
            "---\n\n"
            "Analise a publicação abaixo e classifique sua relevância "
            "conforme as diretrizes acima.\n\n"
            f"**Título:** {title}\n"
            f"**Órgão/Hierarquia:** {hierarchy}\n"
            f"**Seção do DOU:** {section}\n"
            f"**Termo que encontrou:** {found_by}\n"
            f"**Conteúdo:**\n{body}\n\n"
            "Responda SOMENTE com o JSON de classificação."
        )

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FilterResult,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        response_text = self._call_with_retry(prompt, config)

        if response_text is None:
            logger.warning(
                "filter_single — no response for '%s'. "
                "Defaulting to RELEVANTE.",
                title,
            )
            return {
                "classificacao": "RELEVANTE",
                "justificativa": (
                    "Sem resposta do LLM — mantido como relevante "
                    "por segurança."
                ),
                "confianca": 0.0,
            }

        try:
            parsed = FilterResult.model_validate_json(response_text)
            return parsed.model_dump()
        except Exception as exc:
            logger.warning(
                "filter_single — failed to parse response for '%s': %s. "
                "Defaulting to RELEVANTE.",
                title,
                exc,
            )
            return {
                "classificacao": "RELEVANTE",
                "justificativa": (
                    "Erro ao interpretar resposta do LLM — mantido como "
                    "relevante por segurança."
                ),
                "confianca": 0.0,
            }

    # ------------------------------------------------------------------
    # Internal: API call with exponential-backoff retry
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        prompt: str,
        config: types.GenerateContentConfig,
        max_retries: Optional[int] = None,
    ) -> Optional[str]:
        """Call the LLM API with retry on rate-limit errors.

        Args:
            prompt: The prompt text to send.
            config: Generation config (JSON schema, thinking, etc.).
            max_retries: Override for the maximum number of attempts.

        Returns:
            The response text on success, or ``None`` if all attempts fail.
        """
        retries = max_retries or self._MAX_RETRIES

        for attempt in range(1, retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                return response.text

            except Exception as exc:
                exc_type = type(exc).__name__

                # Detect rate-limit / resource-exhausted errors by class name
                # or message so we don't need to import provider-specific
                # exception classes.
                is_rate_limit = (
                    "ResourceExhausted" in exc_type
                    or "429" in str(exc)
                    or "rate" in str(exc).lower()
                )

                if is_rate_limit and attempt < retries:
                    wait = 2 ** attempt  # 2s, 4s, 8s …
                    logger.warning(
                        "Rate limit hit (attempt %d/%d). "
                        "Retrying in %ds…",
                        attempt,
                        retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                if is_rate_limit:
                    logger.error(
                        "Rate limit hit — all %d attempts exhausted.",
                        retries,
                    )
                else:
                    logger.error(
                        "LLM API error (attempt %d/%d): [%s] %s",
                        attempt,
                        retries,
                        exc_type,
                        exc,
                    )
                return None

        return None  # pragma: no cover — unreachable but satisfies type checker
