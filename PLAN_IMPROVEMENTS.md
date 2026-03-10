# Plano de Melhorias — DOU Clipping App v2

## Arquitetura geral

```
┌─────────────────────────────────────────────────────────────────┐
│                        ETAPA 1 — DETERMINÍSTICA                │
│                                                                 │
│  rules.yaml ──► dou_clipping.py ──► Resultados brutos          │
│                                                                 │
│  - Busca por termos exatos (API DOU)                           │
│  - Busca por radicais (texto local: BA, texto completo)        │
│  - Regras por seção (S1: todos, S2: nomeações, S3: CD)        │
│  - Regras positivas (TCU acórdãos CD)                          │
│  - Regras negativas (excluir padrões)                          │
│  - Split de atos compostos (TCU lote, extratos, portarias)     │
│  - Texto completo com contexto                                  │
│                                                                 │
│  ► Usuário revisa, seleciona, gera relatório                   │
│  ► PODE PARAR AQUI se quiser                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ botão opcional
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ETAPA 2 — LLM (SEMÂNTICA)                    │
│                                                                 │
│  LLM_GUIDELINES.md ──► Gemini Flash 2.5 ──► Classificação     │
│                                                                 │
│  - Analisa cada resultado da Etapa 1                           │
│  - Classifica: RELEVANTE / PARCIAL / NÃO RELEVANTE            │
│  - Pré-seleciona checkboxes (relevantes = checked)             │
│  - Move filtrados para aba "Filtrados pelo LLM"                │
│  - Justificativa de 1 frase por item                           │
│                                                                 │
│  Módulo extra: Enriquecimento de termos                        │
│  - Botão "Sugerir novos termos" na sidebar                     │
│  - LLM analisa termos atuais + contexto NUATI                  │
│  - Sugere novos termos, usuário aprova/rejeita                 │
└─────────────────────────────────────────────────────────────────┘
```

## Fases de implementação

### FASE 1 — Fundação (rules.yaml + correções)

**Arquivos criados:**
- [x] `data/rules.yaml` — documento de referência central
- [x] `docs/LLM_GUIDELINES.md` — contexto para o LLM na Etapa 2

**Tarefas:**

1. **Criar `rules_engine.py`** — módulo que lê `rules.yaml` e expõe as regras
   - `load_rules()` → dict com todas as regras
   - `get_search_terms()` → lista de termos exatos
   - `get_stems()` → lista de radicais para regex
   - `get_section_config(section)` → config da seção
   - `get_positive_rules()` → regras positivas
   - `get_negative_rules()` → regras negativas
   - `get_split_patterns()` → padrões de split
   - `get_display_config()` → config de display

2. **Migrar `dou_clipping.py`** para usar `rules_engine.py`
   - Remover SEARCH_TERMS hardcoded
   - Carregar termos do YAML
   - Carregar config de seções do YAML

3. **Corrigir bug da página no relatório**
   - `generate_email_body()` já tem o campo `page` mas pode estar vazio
   - Verificar se `_parse_content()` extrai `pageNumber` corretamente
   - Garantir que aparece no HTML

4. **Atualizar rodapé do relatório**
   - Listar TODOS os termos usados (exatos + radicais com descrição)
   - Formato: termo exato + "(variações: ...)" para radicais

---

### FASE 2 — Busca aprimorada (regras determinísticas)

5. **Implementar busca na Seção 2** (nomeações)
   - Buscar "Câmara dos Deputados" na Seção 2
   - Para cada resultado, aplicar filtros do YAML:
     - `nomeacoes_ditec_fc3`: texto contém DITEC + FC 3+
     - `nomeacoes_cd_fc4`: texto contém CD + FC 4+ (exceto DITEC)
   - Buscar texto completo para verificar FC level
   - Marcar `found_by` com a regra que capturou

6. **Implementar regras positivas** (TCU acórdãos CD)
   - Ao buscar Seção 1, verificar se resultado é acórdão do TCU
   - Se menciona "Câmara dos Deputados" no texto → incluir sempre
   - Mesmo que o termo de busca original não tenha encontrado

7. **Implementar radicais**
   - Na busca do BA (PDF): usar regex `radical\w*` além dos termos exatos
   - No texto completo (após fetch): marcar matches de radicais
   - No highlight: destacar matches de radicais também
   - NÃO usar radicais na API do DOU (só aceita frase exata)

8. **Implementar split de atos compostos**
   - Após `fetch_full_text()`, detectar se contém múltiplos atos
   - Usar padrões do YAML (`regex_separador`)
   - Dividir texto em blocos
   - Criar um item de resultado para cada bloco
   - Preservar metadados do item original (seção, data, página, link)
   - Gerar título: usar `titulo_regex` ou "Ato N de M — Título original"

9. **Texto completo no toggle com contexto**
   - No expander "Ver detalhes", mostrar texto completo
   - Limitar a `toggle_max_chars` (YAML, default 2000)
   - Mostrar `contexto_chars_antes` + TERMO + `contexto_chars_depois`
   - Destacar todos os termos encontrados

10. **Texto completo no relatório**
    - `generate_email_body()`: usar `full_text` sempre que disponível
    - Limitar a `relatorio_max_chars` (YAML, default 5000)
    - Manter highlight de termos

---

### FASE 3 — Integração LLM

11. **Criar `llm_engine.py`** — módulo de integração com LLM
    - `GeminiClient` — wrapper para Gemini Flash 2.5 API
    - `enrich_terms(current_terms, context)` → lista de sugestões
    - `filter_results(items, guidelines)` → classificações
    - Suporte futuro: `OllamaClient` (mesma interface)

12. **Módulo de enriquecimento de termos** (sidebar)
    - Botão "Sugerir novos termos com IA"
    - Envia termos atuais + contexto NUATI ao LLM
    - LLM retorna sugestões com justificativa
    - Usuário vê sugestões em checkboxes, aprova/rejeita
    - Aprovados são adicionados à lista de termos

13. **Módulo de filtragem semântica** (Etapa 2)
    - Botão "Filtrar com IA" aparece APÓS busca da Etapa 1
    - Para cada resultado, envia ao LLM:
      - Título, ementa, órgão, seção, texto (truncado)
      - Contexto: LLM_GUIDELINES.md
    - LLM retorna classificação + justificativa + confiança
    - Resultados "NÃO RELEVANTE" → desmarca checkbox + move para aba
    - Resultados "PARCIALMENTE RELEVANTE" → mantém mas com badge

14. **Aba "Filtrados pelo LLM"**
    - Nova tab no Streamlit: "Resultados" | "Filtrados pelo LLM"
    - Mostra itens que o LLM classificou como não relevantes
    - Cada item mostra justificativa do LLM
    - Usuário pode re-selecionar itens (override do LLM)
    - Contador: "X itens filtrados pelo LLM"

15. **Suporte Ollama** (futuro)
    - Mesma interface de `llm_engine.py`
    - Configurar em `rules.yaml`: `provider: "ollama"`
    - Endpoint local: `http://localhost:11434`

---

## Novos arquivos

| Arquivo | Função |
|---------|--------|
| `data/rules.yaml` | Referência central de regras (já criado) |
| `docs/LLM_GUIDELINES.md` | Contexto para LLM Etapa 2 (já criado) |
| `rules_engine.py` | Leitor/parser do rules.yaml |
| `llm_engine.py` | Integração com Gemini/Ollama |

## Arquivos modificados

| Arquivo | Mudanças |
|---------|----------|
| `dou_clipping.py` | Usar rules_engine, Seção 2, split atos, radicais, texto completo |
| `app.py` | Aba LLM, botão enriquecimento, toggle texto, aba filtrados |
| `requirements.txt` | Adicionar `pyyaml`, `google-generativeai` |

## Ordem de execução sugerida

```
FASE 1 (fundação):
  1. rules_engine.py
  2. Migrar dou_clipping.py para usar rules_engine
  3. Fix bug página relatório
  4. Atualizar rodapé

FASE 2 (busca):
  5. Seção 2 (nomeações)
  6. Regras positivas (TCU)
  7. Radicais
  8. Split atos compostos
  9. Toggle texto com contexto
  10. Texto completo no relatório

FASE 3 (LLM):
  11. llm_engine.py
  12. Enriquecimento de termos
  13. Filtragem semântica
  14. Aba filtrados
  15. Suporte Ollama
```
