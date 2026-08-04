# Roadmap tecnico

Este roadmap organiza a proxima fase do SIGE MPE: menos risco operacional, mais clareza de manutencao e melhor base para novas funcionalidades.

## 1. Higiene do projeto

- Manter ambientes virtuais, builds, logs, bases locais, caches, recibos e relatorios fora do Git.
- Usar `README.md` como ponto unico de arranque para instalar, testar, executar e empacotar.
- Separar dependencias de runtime, desenvolvimento e build.
- Evitar guardar artefactos gerados dentro de pastas de codigo.

## 2. Robustez operacional

- Criar uma tela de estado do sistema com:
  - caminho da base de dados;
  - modo atual (`local`, `remote` ou `hybrid`);
  - estado da API;
  - ultimo backup;
  - tamanho da base;
  - ultimos erros importantes.
- Expor uma acao de backup manual e restauracao assistida.
- Mostrar avisos quando `API_KEY` estiver ausente em ambiente de producao.

## 3. Separacao de responsabilidades

- Dividir `database/database.py` em servicos por dominio:
  - produtos;
  - vendas;
  - stock e movimentos;
  - perdas;
  - utilizadores;
  - relatorios;
  - automacoes.
- Reduzir responsabilidade dos ecras Kivy, movendo regras para servicos testaveis.
- Centralizar formatacao de dinheiro, quantidade e datas em utilitarios comuns.

## 4. Testes prioritarios

- Fluxo completo de venda com IVA, reducao de stock e recibo.
- Reposicao de stock com historico.
- Registo de perdas e impacto em stock.
- Geracao de relatorios principais.
- API em modo hibrido com indisponibilidade temporaria.
- Permissoes de administrador e gerente em operacoes sensiveis.

## 5. Funcionalidades de negocio

- Fecho de caixa diario por gerente/terminal.
- Auditoria de cancelamentos, descontos, devolucoes e alteracoes de stock.
- Alertas acionaveis para stock minimo, produtos parados e validade.
- Exportacao de relatorios para Excel/CSV alem do PDF.
- Tela de manutencao para limpeza de cache e logs antigos.

## 6. Qualidade de interface

- Padronizar estados de carregamento, erro e vazio.
- Garantir que telas pesadas carreguem sob demanda.
- Reduzir duplicacao de componentes visuais.
- Rever textos fixos para passarem por i18n.

## Sequencia sugerida

1. Concluir higiene do projeto e documentacao.
2. Adicionar tela de estado do sistema.
3. Cobrir fluxos criticos com testes.
4. Refatorar servicos de dominio aos poucos.
5. Adicionar fecho de caixa e auditoria expandida.

## Progresso aplicado

- `README.md` criado como guia de arranque.
- Dependencias separadas em runtime, desenvolvimento e build.
- Estado do sistema exposto nas configuracoes do Admin.
- Backup manual verificado disponivel no painel de estado.
- Alertas operacionais adicionados para API, backup, API key e integridade da base.
- Formatadores comuns criados para dinheiro, quantidades, numeros e datas.
- Primeiras telas e relatorios migrados para helpers comuns, reduzindo duplicacao.
- `utils/` reorganizado por dominio (`config`, `core`, `business`, `hardware`, `ai`, `screens`) com wrappers de compatibilidade.
