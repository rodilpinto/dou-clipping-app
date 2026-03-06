# Guia de Deploy — Streamlit Cloud

## Pre-requisitos

1. Conta no GitHub (gratuita)
2. Conta no Streamlit Cloud (gratuita, login com GitHub)
3. Personal Access Token do GitHub (para persistencia)

## Passo 1: Criar repositorio no GitHub

```bash
cd dou-clipping-app

# Inicializar git
git init
git add .
git commit -m "V1.0 - Clipping DOU app"

# Criar repo no GitHub (via CLI ou interface web)
gh repo create dou-clipping-app --public --source=. --remote=origin --push
```

Ou pela interface web:
1. Acessar github.com/new
2. Nome: `dou-clipping-app`
3. Visibilidade: Public (necessario para Streamlit Cloud gratuito)
4. Criar e seguir instrucoes de push

## Passo 2: Criar Personal Access Token

O token e usado pelo app para salvar selecoes e termos no repositorio.

1. Acessar github.com > Settings > Developer Settings > Personal Access Tokens > Fine-grained tokens
2. Clicar "Generate new token"
3. Configurar:
   - **Nome**: `dou-clipping-app`
   - **Expiration**: 1 ano (ou sem expiracao)
   - **Repository access**: Only select repositories > `dou-clipping-app`
   - **Permissions**: Contents > Read and write
4. Copiar o token gerado (comeca com `github_pat_`)

## Passo 3: Deploy no Streamlit Cloud

1. Acessar [share.streamlit.io](https://share.streamlit.io)
2. Login com GitHub
3. Clicar "New app"
4. Configurar:
   - **Repository**: `seu-usuario/dou-clipping-app`
   - **Branch**: `main`
   - **Main file path**: `app.py`
5. Em **Advanced settings**, configurar Secrets:

```toml
GITHUB_TOKEN = "github_pat_seu_token_aqui"
GITHUB_REPO = "seu-usuario/dou-clipping-app"
```

6. Clicar "Deploy!"

O app ficara disponivel em `https://dou-clipping-app.streamlit.app` (ou URL similar).

## Passo 4: Verificar

1. Acessar a URL do app
2. Clicar "Buscar" com a data de hoje
3. Selecionar publicacoes e clicar "Gerar Relatorio"
4. Testar "Copiar HTML" e colar no Outlook
5. Testar "Salvar selecao no GitHub" — verificar se JSON aparece em `data/selections/`

## Atualizacoes

Cada `git push` para o branch `main` dispara redeploy automatico no Streamlit Cloud.

```bash
# Fazer alteracao
git add .
git commit -m "Descricao da mudanca"
git push
```

## Limites do Streamlit Cloud (plano gratuito)

- 1 app por conta
- App "dorme" apos 7 dias sem acesso (acorda automaticamente ao acessar)
- Repositorio precisa ser publico
- Sem dominio customizado
- Recursos: 1 GB RAM, CPU compartilhada

## Alternativa: rodar localmente

Se preferir nao fazer deploy, o app funciona perfeitamente rodando local:

```bash
streamlit run app.py
```

A unica limitacao local e que o "Copiar HTML" pode nao funcionar em `http://localhost` em alguns navegadores (Clipboard API requer HTTPS). O botao "Baixar .htm" funciona como alternativa.

## Troubleshooting

| Problema | Solucao |
|----------|---------|
| App nao inicia no Cloud | Verificar requirements.txt e erros no log |
| "Secrets not found" | Configurar Secrets no dashboard do Streamlit Cloud |
| "Erro ao salvar no GitHub" | Verificar token e permissoes do PAT |
| App lento na busca | Normal — a busca faz ~45 requisicoes com delays |
| "Copiar HTML" falha | Verificar HTTPS; usar "Baixar .htm" como fallback |
