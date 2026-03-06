# Clipping DOU - NUATI

Aplicacao web para clipping diario do Diario Oficial da Uniao (DOU), desenvolvida para o Nucleo de Auditoria de TI (NUATI) da Camara dos Deputados.

## O que faz

- Busca publicacoes no DOU por termos configuráveis (44 termos padrão)
- Busca no Boletim Administrativo da Câmara dos Deputados
- Permite selecionar publicacoes relevantes com checkboxes
- Gera relatorio HTML formatado para envio por email (Outlook)
- Copia HTML rico para a area de transferência (cola formatado no Outlook)
- Salva historico de selecoes/rejeicoes no GitHub (para futura filtragem automatica)
- Termos de busca editaveis e persistentes via GitHub

## Estrutura do projeto

```
dou-clipping-app/
  app.py                    # App Streamlit (interface web)
  dou_clipping.py           # Backend de busca no DOU e Boletim Administrativo
  requirements.txt          # Dependencias Python
  .streamlit/
    config.toml             # Tema visual (cores da Camara dos Deputados)
    secrets.toml            # Secrets locais (NAO commitado)
  data/
    selections/             # JSONs de historico (auto-commitados via GitHub API)
      .gitkeep
    search_terms.json       # Termos customizados (auto-commitado via GitHub API)
  docs/
    ARQUITETURA.md          # Documentacao tecnica detalhada
    DEPLOY.md               # Guia de deploy no Streamlit Cloud
    USO.md                  # Manual de uso do app
    ROADMAP_V2.md           # Plano da versao 2 (filtragem automatica)
  .gitignore
```

## Requisitos

- Python 3.10+
- Dependencias: `streamlit`, `requests`, `beautifulsoup4`, `pdfplumber`

## Executar localmente

```bash
# Instalar dependencias
pip install -r requirements.txt

# Rodar o app
streamlit run app.py
```

O app abre em `http://localhost:8501`.

## Deploy no Streamlit Cloud

Ver [docs/DEPLOY.md](docs/DEPLOY.md) para o guia completo.

Resumo:
1. Criar repositorio no GitHub e fazer push
2. Acessar [share.streamlit.io](https://share.streamlit.io) e conectar o repo
3. Configurar Secrets no dashboard: `GITHUB_TOKEN` e `GITHUB_REPO`

## Configurar Secrets (desenvolvimento local)

Criar `.streamlit/secrets.toml`:

```toml
GITHUB_TOKEN = "ghp_seu_token_aqui"
GITHUB_REPO = "seu-usuario/dou-clipping-app"
```

O token precisa de permissao `repo` (ou `contents: write` para fine-grained tokens).

**Os Secrets sao opcionais** — sem eles, o app funciona normalmente para busca e geracao de relatorio. Apenas as funcoes de salvar no GitHub ficam desabilitadas.

## Como usar

1. **Abrir o app** — datas ja vem preenchidas com hoje
2. **Clicar "Buscar"** — aguardar 2-5 minutos (barra de progresso mostra andamento)
3. **Revisar resultados** — cada publicacao mostra titulo, ementa, orgao e termo encontrado
4. **Expandir detalhes** — clicar "Ver detalhes completos" para texto integral com highlight
5. **Selecionar/desmarcar** — checkboxes individuais ou botoes de selecao em massa
6. **Ver estatisticas** — toggle "Estatisticas por termo" mostra contagem por palavra-chave
7. **Gerar relatorio** — botao "Gerar Relatorio" cria HTML com publicacoes selecionadas
8. **Copiar para Outlook** — botao "Copiar HTML" copia formatado; colar com Ctrl+V
9. **Baixar arquivo** — botao "Baixar .htm" como fallback
10. **Salvar historico** — botao "Salvar selecao no GitHub" registra escolhas para V2

## Termos de busca

Os 44 termos padrão cobrem temas de auditoria, TI, governanca e controle. Na sidebar:
- **Editar**: modificar no text_area e clicar "Aplicar"
- **Salvar**: "Salvar termos no GitHub" persiste para proximas sessoes
- **Restaurar**: "Restaurar padrao" volta aos 44 termos originais

## Roadmap

- **V1 (atual)**: Busca, selecao, relatorio, historico
- **V2 (futuro)**: Filtragem automatica baseada em padroes de rejeicao — ver [docs/ROADMAP_V2.md](docs/ROADMAP_V2.md)

## Autor

NUATI/SECIN — Camara dos Deputados
