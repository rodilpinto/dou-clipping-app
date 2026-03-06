# Manual de Uso — Clipping DOU v1.0

## Fluxo diario

### 1. Abrir o app

Acessar a URL do Streamlit Cloud ou `http://localhost:8501` se rodando local.
As datas ja vem preenchidas com o dia de hoje.

### 2. Configurar termos (opcional)

Na sidebar, expandir "Termos de busca":
- O app carrega termos salvos no GitHub (ou os 44 termos padrao)
- Para editar: modificar o texto (um termo por linha) e clicar "Aplicar"
- Para salvar permanentemente: clicar "Salvar termos no GitHub"
- Para voltar ao padrao: clicar "Restaurar padrao"

### 3. Buscar publicacoes

- Ajustar datas se necessario (data inicial e final)
- Clicar **Buscar**
- Aguardar a barra de progresso (2-5 minutos dependendo do numero de termos e datas)
- O progresso mostra qual termo esta sendo buscado e a porcentagem

### 4. Revisar resultados

Cada publicacao mostra diretamente (sem precisar expandir):
- **Titulo** em negrito
- **Termo encontrado**, **Orgao**, **Secao** e **Data** em linha compacta
- **Ementa** (para atos normativos: texto antes do "RESOLVE:")

Para ver o texto completo com highlight dos termos:
- Clicar em **"Ver detalhes completos"** (expander)

### 5. Ver estatisticas por termo

- Ativar o toggle **"Estatisticas por termo"** ao lado da contagem de publicacoes
- Mostra quantas publicacoes cada palavra-chave encontrou
- Util para avaliar quais termos trazem mais resultados

### 6. Selecionar publicacoes relevantes

- **Checkbox individual**: marcar/desmarcar cada publicacao
- **Selecionar todos**: marca todas de uma vez
- **Desmarcar todos**: desmarca todas de uma vez
- Todos os checkboxes iniciam marcados apos a busca

### 7. Gerar relatorio

- Clicar **"Gerar Relatorio"**
- O relatorio HTML e gerado apenas com as publicacoes selecionadas
- Mensagem confirma quantas publicacoes foram incluidas

### 8. Enviar por email

Tres opcoes de saida:

**Opcao A — Copiar HTML (recomendado)**
1. Clicar no botao azul **"Copiar HTML para a area de transferencia"** (dentro do iframe)
2. Abrir o Outlook e criar novo email
3. Colar com **Ctrl+V** — o conteudo cola formatado (negrito, links, highlight)

**Opcao B — Baixar arquivo**
1. Clicar **"Baixar .htm"**
2. Abrir o arquivo .htm no navegador
3. Selecionar tudo (Ctrl+A), copiar (Ctrl+C)
4. Colar no Outlook (Ctrl+V)

**Opcao C — Preview**
1. Expandir **"Preview do email"** para visualizar o relatorio antes de enviar

### 9. Salvar historico (opcional mas recomendado)

- Clicar **"Salvar selecao no GitHub"**
- Salva um JSON com as publicacoes selecionadas E rejeitadas
- Esse historico sera usado na V2 para filtragem automatica

## Dicas

- **Busca rapida**: Se usa os mesmos termos todo dia, basta abrir o app e clicar "Buscar"
- **Multiplas datas**: Para segunda-feira, selecione sexta a segunda como periodo
- **Limite de 30 dias**: O intervalo maximo e 30 dias para evitar sobrecarga
- **Termos customizados**: Adicione termos especificos para projetos temporarios
- **Boletim Administrativo**: O app busca automaticamente o BA da Camara para cada data

## Termos de busca padrao (44 termos)

| Categoria | Termos |
|-----------|--------|
| Camara | Camara dos Deputados |
| TI/TIC | Tecnologia da informacao, Auditoria de TI, Auditoria de TIC, Solucoes de TI |
| Auditoria | Auditoria interna, COSO, AudTI, Sefti/TCU |
| Controle | Controle interno, Controles internos |
| Frameworks | COBIT, Itil, BPM |
| Governanca | Governanca corporativa, Governanca de TI, Governanca de aquisicoes, Governanca de contratacoes |
| Gestao | Gestao de aquisicoes, Gestao de contratacoes, Gestao de contratos, Fiscalizacao de contratos |
| Riscos | Riscos, Processos criticos, Continuidade de negocios |
| Seguranca | Seguranca de informacao, Seguranca da informacao |
| Processos | Gestao de processos, Melhoria de processos |
| Dados | Dados abertos, Dados em formatos abertos, Ciencia de dados |
| Software | Fabrica de Software, Pontos de funcao, Ponto de funcao, Processo de software |
| Inovacao | Inteligencia artificial, Hackers, Hacktivismo |
| Transparencia | Transparencia da informacao, Lei de Acesso a Informacao, LAI |
| Indicadores | Indicadores |
| Fiscalizacao | Secretaria de Fiscalizacao de Tecnologia da Informacao |
