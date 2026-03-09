# Plano V2 — Construcao de Dados de Treinamento a partir dos Emails Historicos

## Objetivo

Criar um script Python (`build_training_data.py`) que processa os emails historicos
em `Ro-dou/emails de saida/` para gerar JSONs de selecao/rejeicao no mesmo formato
que a V1 salva no GitHub. Isso acelera a V2 sem esperar semanas de uso manual.

## Inventario dos Emails Historicos

### Tier 1 — HTML gerado pelo script (parseable, com URLs in.gov.br)
| Arquivo | Data | Links |
|---------|------|-------|
| `DOU_02032026.htm` | 02/03/2026 | 228 |
| `DOU_03032026.htm` | 03/03/2026 | 131 |
| `DOU_04032026.htm` | 04/03/2026 | 402 |
| `DOU_05032026.htm` | 05/03/2026 | 30 |

### Tier 2 — HTML do Word/Outlook (formato inconsistente, poucos URLs)
| Arquivo | Data(s) | Links |
|---------|---------|-------|
| `DOU 270226.htm` | 27/02/2026 | 5 |
| `DOU de 522026.htm` | 05/02/2026 | 4 |
| `DOU 24022026.htm` | 24/02/2026 | 2 |
| `DOU 25062026.htm` | 25/06/2026? | 2 |
| `DOU de 18 a 20 de fevereiro de 2026.htm` | 18-20/02/2026 | 2 |
| `DOU de 1222026.htm` | 12/02/2026 | 1 |

### Tier 3 — Word HTML sem URLs (matching so por titulo)
| Arquivo | Data |
|---------|------|
| `DOU 26022026.htm` | 26/02/2026 |
| `DOU 27022026.htm` | 27/02/2026 |
| `DOU de 322026.htm` | 03/02/2026 |
| `DOU de 1322026.htm` | 13/02/2026 |

## Estrategia

### Fase 1: Script `build_training_data.py`

Um script standalone que:

1. **Parseia cada email HTML** para extrair as publicacoes selecionadas:
   - Tier 1: Extrai URLs (`href` contendo `in.gov.br`) e titulos (`<b>` dentro de `<a>`)
   - Tier 2/3: Extrai titulos de publicacoes via regex em texto (PORTARIA, RESOLUCAO, etc.)

2. **Roda a busca para cada data** usando `search_all_terms()` do `dou_clipping.py`:
   - Usa os 44 termos de busca atuais
   - Respeita rate limiting (1-2.5s entre requests)
   - Tempo estimado: ~3-5 min por data

3. **Compara resultados** (matching):
   - **Match primario**: URL normalizada (remove protocolo, trailing slash)
   - **Match secundario**: titulo normalizado (lowercase, sem acentos, sem espacos extras)
   - Resultado: cada item do search e classificado como `selected` ou `rejected`

4. **Salva JSON** no formato V1:
   ```json
   {
     "date": "05/03/2026",
     "saved_at": "2026-03-07T...",
     "source": "historical_email",
     "source_file": "DOU_05032026.htm",
     "selected": [...],
     "rejected": [...],
     "stats": {
       "total_search": 45,
       "matched_selected": 30,
       "unmatched_email": 2,
       "rejected": 13
     }
   }
   ```

### Fase 2: Processamento sequencial

O script processa UM email por vez para evitar problemas de memoria/rate limit:

```
python build_training_data.py                    # Processa todos
python build_training_data.py --file DOU_05032026.htm  # Processa um especifico
python build_training_data.py --dry-run          # So parseia emails, sem chamar API
```

Fluxo por email:
```
[1] Parseia email HTML → extrai titulos/URLs selecionados
[2] Infere data a partir do nome do arquivo
[3] Chama search_all_terms(terms, date) → resultados completos
[4] Matching: classifica cada resultado como selected/rejected
[5] Salva JSON em data/training/selection_DDMMYYYY.json
[6] Imprime relatorio resumo
[7] Pausa antes do proximo email
```

### Fase 3: Relatorio de qualidade

Apos processar todos os emails, gerar relatorio:
- Quantas publicacoes do email NAO foram encontradas na busca (gaps)
- Quantas publicacoes da busca NAO estavam no email (rejeicoes)
- Taxa de selecao por termo de busca
- Orgaos mais rejeitados
- Combinacoes (termo + arttype) mais rejeitadas

## Decisoes Tecnicas

1. **Priorizar Tier 1** (4 arquivos com HTML limpo) — maior confiabilidade no matching
2. **Tier 2/3 como bonus** — matching por titulo e menos confiavel mas ainda util
3. **Nao modificar dou_clipping.py** — importar e usar as funcoes existentes
4. **Saida em `data/training/`** separada de `data/selections/` (V1) para nao misturar
5. **Logging detalhado** — cada step logado para debug

## Arquivos a criar/modificar

| Arquivo | Acao |
|---------|------|
| `build_training_data.py` | **CRIAR** — script principal |
| `data/training/` | **CRIAR** — diretorio para JSONs de treinamento |
| Nenhum arquivo existente modificado | |

## Riscos e Mitigacoes

| Risco | Mitigacao |
|-------|-----------|
| API DOU pode nao ter dados antigos (fev 2026) | Testar com --dry-run primeiro; datas sao recentes (~3 semanas) |
| Termos de busca mudaram desde os emails | Aceitar — o matching por URL/titulo ainda funciona |
| Rate limiting da API | Delays ja implementados em search_all_terms() |
| Email tem publicacoes que a busca atual nao encontra | Registrar como "unmatched_email" nas stats |
| Encoding windows-1252 nos arquivos Word | Usar chardet ou tentar multiple encodings |
