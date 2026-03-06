# Roadmap V2 — Filtragem Automatica por Padroes de Rejeicao

## Contexto

Na V1, o usuario faz curadoria manual: recebe ~30-40 publicacoes por dia e seleciona as relevantes. Muitas publicacoes sao consistentemente rejeitadas (ex: editais de prefeituras encontrados pelo termo "Indicadores", portarias de nomeacao, etc.).

A V2 vai analisar o historico de selecoes/rejeicoes salvo na V1 para identificar padroes e filtrar automaticamente publicacoes irrelevantes.

## Base de dados (ja coletada na V1)

Cada vez que o usuario clica "Salvar selecao no GitHub", um JSON e salvo em `data/selections/` com:

```json
{
    "date": "06/03/2026",
    "saved_at": "2026-03-06T15:30:00",
    "selected": [
        {"title": "...", "hierarchy": "...", "found_by": "...", "arttype": "...", ...}
    ],
    "rejected": [
        {"title": "...", "hierarchy": "...", "found_by": "...", "arttype": "...", ...}
    ]
}
```

Cada publicacao **nao selecionada** e uma **rejeicao implicita**. Com semanas de uso, acumula-se um banco de padroes.

## Padroes de filtragem identificaveis

### 1. Por orgao
Certas hierarquias sao consistentemente rejeitadas:
- Prefeituras municipais (encontradas por "Controle interno", "Riscos")
- Universidades (encontradas por "Auditoria interna")
- Orgaos estaduais sem relevancia

**Regra**: Se publicacoes de um orgao foram rejeitadas 10+ vezes e nunca selecionadas, sugerir oculta-lo.

### 2. Por combinacao termo + tipo de ato
Certas combinacoes sao irrelevantes:
- "Indicadores" + Edital (editais de licitacao com indicadores economicos)
- "Riscos" + Extrato de contrato (clausulas padrao de risco)
- "BPM" + Portaria (Business Process Management vs siglas homonimas)

**Regra**: Se a combinacao (found_by, arttype) foi rejeitada 10+ vezes com taxa de rejeicao > 90%, sugerir ocultar.

### 3. Por titulo/regex
Padroes textuais no titulo:
- "EXTRATO DE INEXIGIBILIDADE"
- "AVISO DE LICITACAO"
- Titulos contendo nomes de municipios

**Regra**: Se titulos com determinado padrao regex foram rejeitados 15+ vezes, sugerir filtro.

## Arquitetura proposta para V2

```
data/selections/*.json          # Historico (ja existe)
data/filters.json               # Regras de filtragem (novo)
app.py                          # UI de gestao de filtros (nova aba/secao)
filter_engine.py                # Motor de analise e filtragem (novo modulo)
```

### `filter_engine.py` — Motor de filtragem

```python
def analyze_rejections(selections_dir: str) -> list[FilterSuggestion]:
    """Analisa JSONs de historico e sugere filtros."""

def apply_filters(items: list, filters: list) -> tuple[list, list]:
    """Aplica filtros aos resultados, retornando (visiveis, ocultos)."""

def load_filters(github_repo: str) -> list:
    """Carrega filters.json do GitHub."""

def save_filters(filters: list, github_repo: str):
    """Salva filters.json no GitHub."""
```

### `data/filters.json` — Formato

```json
{
    "version": 2,
    "filters": [
        {
            "id": "f1",
            "type": "org",
            "pattern": "Prefeitura Municipal",
            "action": "hide",
            "reason": "Rejeitado 47 vezes, nunca selecionado",
            "created_at": "2026-04-01",
            "active": true
        },
        {
            "id": "f2",
            "type": "term_arttype",
            "term": "Indicadores",
            "arttype": "Edital",
            "action": "hide",
            "reason": "94% de rejeicao em 32 ocorrencias",
            "created_at": "2026-04-01",
            "active": true
        }
    ]
}
```

### UI de gestao de filtros (app.py)

Nova secao na sidebar ou aba dedicada:
- **Sugestoes**: lista de padroes detectados com botao "Ativar filtro" / "Ignorar"
- **Filtros ativos**: lista com toggle on/off por filtro
- **Publicacoes ocultas**: expander mostrando o que foi filtrado (com opcao de restaurar)
- **Estatisticas**: contagem de publicacoes filtradas por dia/semana

## Cronograma sugerido

| Fase | Descricao | Quando |
|------|-----------|--------|
| V1 uso | Usar V1 diariamente, acumular historico | 2-4 semanas |
| Analise | Rodar analise exploratoria nos JSONs | Apos ~50 JSONs |
| V2 alpha | Implementar filter_engine.py e UI basica | Apos analise |
| V2 beta | Testar filtros sugeridos, ajustar thresholds | 1-2 semanas |
| V2 release | Estabilizar e documentar | Apos beta |

## Metricas de sucesso

- Reducao de 50%+ no numero de publicacoes que precisam de revisao manual
- Zero falsos negativos (publicacoes relevantes nunca devem ser filtradas automaticamente sem opcao de revisao)
- Tempo de curadoria diaria reduzido de ~15min para ~5min

## Principios de design

1. **Conservador**: Nunca ocultar automaticamente sem que o usuario revise a sugestao
2. **Reversivel**: Todo filtro pode ser desativado; publicacoes ocultas sempre visiveis em secao separada
3. **Transparente**: Cada filtro mostra o motivo e as estatisticas que o geraram
4. **Incremental**: Filtros melhoram com o tempo conforme mais dados acumulam
