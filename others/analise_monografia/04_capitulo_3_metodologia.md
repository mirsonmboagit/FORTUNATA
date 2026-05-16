# Capitulo 3 - Metodologia

## O Que Esta Bem

- O capitulo identifica localizacao, caracterizacao do estabelecimento, classificacao da pesquisa, tecnicas de recolha de dados, populacao/amostra, XP e tecnologias.
- A escolha de pesquisa aplicada e estudo de caso e adequada.
- A abordagem qualitativa combina com entrevistas, observacao directa e analise documental.
- A escolha de XP e defensavel, porque o projecto e incremental e depende de feedback do utilizador.
- As tecnologias indicadas correspondem ao projecto real: Python, Kivy, KivyMD, SQLite, Flask, requests, ReportLab e bibliotecas auxiliares.

## Erros e Inconsistencias

- Ha duas secoes numeradas como `3.1`:
  - `3.1 Localizacao e Caracterizacao da Area de Estudo`;
  - `3.1 Classificacao da Pesquisa`.
- Como consequencia, todo o restante capitulo 3 fica numerado de forma errada.
- A subseccao `3.5.1 Python` nao esta formatada como titulo no Word, ao contrario de `3.5.2`.
- Ha mistura de tempos verbais:
  - "serao utilizados";
  - "foi orientado";
  - "foram realizados";
  - "a amostra sera composta";
  - "a populacao foi constituida".
- Em "a dificuldade na gestao manual de vendas e - mediante..." ha frase quebrada. Falta "controlo de stock".
- A metodologia afirma praticas fortes de XP, como programacao em pares, testes automatizados e integracao continua. Se essas praticas nao foram realmente executadas, devem ser removidas ou suavizadas.
- A seccao de testes menciona testes unitarios, integracao e UAT, mas a monografia nao apresenta evidencias, criterios, resultados ou instrumentos de validacao.

## Nova Numeracao Recomendada

- 3.1 Localizacao e Caracterizacao da Area de Estudo
- 3.1.1 Localizacao Geografica
- 3.1.2 Caracterizacao do Estabelecimento
- 3.2 Classificacao da Pesquisa
- 3.3 Instrumentos e Tecnicas de Colecta de Dados
- 3.4 Populacao e Amostra
- 3.5 Metodologia do Desenvolvimento do Sistema
- 3.5.1 Justificativa da Escolha do XP
- 3.5.2 Etapas do Desenvolvimento segundo XP
- 3.6 Tecnologias Utilizadas
- 3.6.1 Python
- 3.6.2 Bibliotecas e Ferramentas Complementares

## Texto Corrigido Para a Frase Quebrada

A presente pesquisa e aplicada porque visa resolver um problema real e especifico da Mercearia Muticane Comercial e Servicos: a dificuldade na gestao manual de vendas e no controlo de stock, mediante o desenvolvimento de uma solucao tecnologica ajustada ao contexto do estabelecimento.

## Texto Sugerido Para Evitar Exagero Sobre XP

No presente estudo, os principios do XP foram aplicados de forma adaptada ao contexto academico e aos recursos disponiveis. O desenvolvimento ocorreu por incrementos funcionais, com validacoes sucessivas das funcionalidades principais, correccoes progressivas e contacto com o utilizador para confirmar a adequacao das telas e dos fluxos operacionais.

## Texto Sugerido Para Validacao

A validacao do prototipo foi realizada por meio de verificacao funcional dos principais modulos, incluindo autenticacao, cadastro de produtos, registo de vendas, actualizacao de stock, emissao de relatorios e consulta de historicos. Tambem foram considerados testes de utilizacao com base em cenarios representativos da rotina da mercearia, permitindo identificar ajustes de usabilidade e consistencia dos dados.

