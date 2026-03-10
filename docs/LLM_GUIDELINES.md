# Diretrizes para Filtragem por LLM — DOU Clipping NUATI

Este documento é o contexto que o LLM recebe na Etapa 2 (filtragem semântica).
Ele define o perfil do usuário, critérios de relevância e instruções de análise.

## Contexto institucional

O **Núcleo de Auditoria de TI (NUATI)** faz parte da **Secretaria de Controle Interno (SECIN)** da **Câmara dos Deputados**. A equipe monitora diariamente o Diário Oficial da União (DOU) para identificar publicações relevantes sobre:

- Normativos, acórdãos e decisões que impactem a Câmara dos Deputados
- Temas de auditoria, governança e controle no setor público
- Tecnologia da informação e comunicação (TIC) no governo
- Boas práticas de gestão e fiscalização

## Critérios de relevância (INCLUIR)

### Alta relevância (sempre incluir)
1. **Acórdãos do TCU sobre a Câmara dos Deputados** — qualquer acórdão que mencione a CD como objeto, ou que contenha recomendações/determinações dirigidas à Câmara
2. **Normativos de TI/TIC do governo federal** — instruções normativas, decretos, portarias que regulem TI, segurança da informação, governança digital, contratações de TI
3. **Publicações da própria Câmara dos Deputados** — atos da Mesa, portarias do Diretor-Geral, resoluções
4. **Nomeações relevantes** — FC 3+ na Ditec (Departamento de Inovação e Tecnologia da Informação), FC 4+ no restante da Câmara
5. **Acórdãos do TCU sobre TI** — mesmo que não mencionem a CD, se tratam de governança de TI, contratações de TI, segurança da informação no setor público
6. **Normativos do SISP** — Sistema de Administração dos Recursos de Tecnologia da Informação
7. **Publicações sobre LGPD** — proteção de dados pessoais no setor público

### Média relevância (incluir com ressalva)
1. **Acórdãos do TCU sobre outros órgãos do Legislativo** — Senado Federal, TCU (auto-referência)
2. **Normativos de governança corporativa** — mesmo sem foco em TI, se tratam de controle interno, gestão de riscos, compliance
3. **Editais de licitação de TI de outros órgãos** — como referência de boas práticas

### Baixa relevância (analisar caso a caso)
1. **Publicações genéricas que mencionam termos de busca** — ex: "riscos" em contexto de saúde pública, "indicadores" em contexto econômico
2. **Nomeações de baixo escalão** — FC 1-2 ou cargos sem relação com TI/auditoria

## Critérios de exclusão (NÃO incluir)

1. **Publicações de prefeituras municipais** — mesmo que mencionem termos de busca
2. **Editais de concurso** — salvo se forem da CD ou de órgão de controle
3. **Publicações repetidas/duplicadas** — mesmo conteúdo com título levemente diferente
4. **Termos fora de contexto** — ex: "BPM" como sigla de outra coisa, "LAI" em outro contexto, "COSO" como nome próprio
5. **Atos de aposentadoria, pensão, licença** — rotina administrativa sem impacto em TI/auditoria

## Instruções para o LLM

Ao analisar cada publicação:

1. **Leia o título e a ementa/resumo completos**
2. **Identifique o órgão emissor** — priorize publicações da CD, TCU, e órgãos do SISP
3. **Avalie o contexto do termo encontrado** — o termo está sendo usado no sentido relevante para auditoria de TI?
4. **Classifique**: RELEVANTE, PARCIALMENTE RELEVANTE, ou NÃO RELEVANTE
5. **Justifique em 1 frase** — por que incluir ou excluir

### Formato de resposta esperado

```json
{
  "classificacao": "RELEVANTE|PARCIALMENTE_RELEVANTE|NAO_RELEVANTE",
  "justificativa": "Acórdão do TCU com determinações para a CD sobre governança de TI.",
  "confianca": 0.95
}
```

## Princípios

- **Segurança**: na dúvida, INCLUIR. É melhor o humano descartar do que perder uma publicação relevante.
- **Transparência**: toda exclusão pelo LLM fica disponível para revisão humana em aba separada.
- **Escalabilidade**: o LLM atua DEPOIS da filtragem determinística (Etapa 1), reduzindo volume e custo.
