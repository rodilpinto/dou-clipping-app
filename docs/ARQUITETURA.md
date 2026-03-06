# Arquitetura Tecnica — Clipping DOU v1.0

## Visao geral

O app e composto por dois modulos Python:

```
app.py (Frontend Streamlit)  -->  dou_clipping.py (Backend de busca)
       |                                  |
       |-- GitHub API (persistencia)      |-- API DOU (in.gov.br)
       |                                  |-- Boletim Administrativo (camara.leg.br)
       |                                  |-- Paginas individuais do DOU (texto completo)
```

## Modulos

### `dou_clipping.py` — Backend

**Responsabilidades:**
- Buscar publicacoes na API do DOU
- Extrair texto completo das paginas
- Buscar e extrair o Boletim Administrativo (PDF)
- Gerar HTML formatado para email
- Aplicar highlight nos termos de busca

**Funcoes principais:**

| Funcao | Descricao |
|--------|-----------|
| `search_dou(term, date_str, sections)` | Busca um termo na API do DOU |
| `search_all_terms(terms, date_str, progress_callback)` | Orquestra busca de todos os termos (Secao 1 + Secao 3) |
| `fetch_full_text(url)` | Extrai texto completo de uma publicacao |
| `fetch_boletim_items(date, terms)` | Baixa e analisa o Boletim Administrativo (PDF) |
| `generate_email_body(items, date_display, search_terms, terms_display)` | Gera HTML do relatorio |
| `highlight_terms(text, terms)` | Aplica destaque amarelo nos termos |
| `clean_html(text)` | Remove tags HTML |
| `get_section_display(section_code)` | Converte codigo de secao para nome legivel |

**Logica de busca por secao:**
- **Secao 1** (do1, do1e): Busca TODOS os termos configurados. Para cada resultado, busca texto completo da pagina.
- **Secao 2**: Ignorada (atos de nomeacao, irrelevantes).
- **Secao 3** (do3): Busca apenas "Camara dos Deputados" (se estiver nos termos configurados).
- **Boletim Administrativo**: Baixa PDF do dia, extrai texto, busca termos configurados.

**Deduplicacao:** Publicacoes com mesmo titulo sao descartadas (primeira ocorrencia prevalece).

**Rate limiting:** Delay de 1.0-2.5s entre requisicoes a API do DOU para evitar bloqueio.

### `app.py` — Frontend Streamlit

**Responsabilidades:**
- Interface web (sidebar + area principal)
- Gerenciamento de estado (session_state)
- Interacao com GitHub API (persistencia)
- Clipboard via JavaScript (copiar HTML rico)

**Fluxo de dados:**

```
1. Sidebar: usuario configura datas e termos
2. Busca: search_all_terms() + fetch_boletim_items()
3. Resultados: salvos em st.session_state["results"]
4. Selecao: checkboxes em st.session_state["sel_0", "sel_1", ...]
5. Relatorio: generate_email_body() → st.session_state["email_html"]
6. Saida: Copiar HTML / Baixar .htm / Salvar no GitHub
```

**Gerenciamento de estado:**

| Chave | Tipo | Descricao |
|-------|------|-----------|
| `results` | list[dict] | Publicacoes retornadas pela busca |
| `email_html` | str | HTML do relatorio gerado |
| `search_done` | bool | Se ja houve busca nesta sessao |
| `search_terms` | list[str] | Termos de busca ativos |
| `sel_{i}` | bool | Checkbox da publicacao i |

## APIs externas

### API do DOU (in.gov.br)
- **URL**: `https://www.in.gov.br/consulta/-/buscar/dou`
- **Metodo**: GET com query params
- **Formato**: HTML com JSON embutido em tag `<script>`
- **Rate limit**: Nao documentado; delays de 1-2.5s sao suficientes
- **Paginacao**: Suportada via params `id`, `displayDate`, `newPage`, `currentPage`

### Paginas do DOU (texto completo)
- **URL**: `https://www.in.gov.br/web/dou/-/{urlTitle}`
- **Formato**: HTML com conteudo em `div.texto-dou`
- **Usado para**: Extrair texto integral de publicacoes da Secao 1

### Boletim Administrativo (Camara)
- **URL**: `https://www.camara.leg.br/boletimadm/{year}/Ba{date}.pdf`
- **Formato**: PDF
- **Extraido com**: pdfplumber

### GitHub API (persistencia)
- **URL**: `https://api.github.com/repos/{repo}/contents/{path}`
- **Metodo**: PUT (criar/atualizar arquivos)
- **Autenticacao**: Personal Access Token via `st.secrets["GITHUB_TOKEN"]`
- **Usado para**: Salvar selecoes (JSONs) e termos customizados

## Formato dos dados

### Item de publicacao (dict)

```python
{
    "section": "DO1",           # Secao do DOU (DO1, DO3, BA)
    "title": "PORTARIA ...",    # Titulo da publicacao
    "href": "https://...",      # URL completa
    "abstract": "...",          # Resumo da API (snippet)
    "full_text": "...",         # Texto completo (Secao 1 apenas)
    "date": "06/03/2026",       # Data de publicacao
    "edition": "43",            # Numero da edicao
    "page": "15",               # Pagina
    "hierarchy": "Min. ...",    # Orgao/hierarquia
    "arttype": "Portaria",      # Tipo do ato
    "found_by": "Riscos",       # Termo que encontrou
}
```

### JSON de selecao (salvo no GitHub)

```json
{
    "date": "06/03/2026",
    "saved_at": "2026-03-06T15:30:00",
    "selected": [ ... ],
    "rejected": [ ... ]
}
```

## Seguranca

- **XSS**: Todos os campos externos passam por `html.escape()` antes de insercao em HTML. JS usa `json.dumps()` para insercao segura.
- **Secrets**: GITHUB_TOKEN via `st.secrets` (nunca no codigo-fonte). `.streamlit/secrets.toml` no `.gitignore`.
- **SSRF**: URLs construidas a partir de bases fixas, sem input direto do usuario.
- **Dados externos**: Campos da API do DOU sao tratados como nao-confiaveis.

## Dependencias

| Pacote | Versao | Uso |
|--------|--------|-----|
| streamlit | >=1.33.0 | Interface web |
| requests | * | HTTP (API DOU, GitHub) |
| beautifulsoup4 | * | Parsing HTML do DOU |
| pdfplumber | * | Extracao de texto do PDF do Boletim |
