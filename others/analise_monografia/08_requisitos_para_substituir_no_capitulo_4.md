# Requisitos Para Substituir No Capitulo 4

Este ficheiro consolida uma versao mais adequada dos requisitos para usar na monografia. A base vem dos ficheiros existentes no projecto:

- `others/Requisitos Funcionais do Sistema.md`
- `others/Requisitos Nao Funcionais do Sistema.md`

## Requisitos Funcionais Sugeridos

| ID | Requisito funcional |
| --- | --- |
| RF01 | O sistema deve permitir a seleccao do perfil de acesso e a autenticacao de utilizadores conforme o papel autorizado. |
| RF02 | O sistema deve permitir a configuracao do administrador inicial e a actualizacao das suas credenciais quando necessario. |
| RF03 | O sistema deve permitir a recuperacao de senha por meio de perguntas de seguranca previamente configuradas. |
| RF04 | O sistema deve permitir ao administrador criar, consultar e remover contas de utilizadores, com foco na gestao de contas do tipo gerente. |
| RF05 | O sistema deve permitir o registo, edicao, consulta e remocao logica de produtos. |
| RF06 | O sistema deve permitir o cadastro de produtos com descricao, categoria, preco de venda, preco de compra, stock, codigo de barras, validade, tipo de venda, embalagem e regra de IVA. |
| RF07 | O sistema deve permitir a pesquisa e filtragem de produtos por texto, categoria, codigo de barras, SKU e outras chaves disponiveis. |
| RF08 | O sistema deve permitir a localizacao de produtos por codigo de barras, incluindo seleccao do lote mais adequado quando existirem varios registos. |
| RF09 | O sistema deve permitir o registo de vendas por unidade, por peso e por embalagem, conforme a configuracao de cada artigo. |
| RF10 | O sistema deve calcular automaticamente o valor total da venda e aplicar a regra de IVA activa ao produto vendido. |
| RF11 | O sistema deve actualizar automaticamente o stock existente e o stock vendido apos cada venda registada com sucesso. |
| RF12 | O sistema deve permitir a emissao de recibo de venda em formato PDF apos a conclusao da operacao. |
| RF13 | O sistema deve permitir a consulta do historico de vendas, com filtros por periodo e acesso aos detalhes de cada registo. |
| RF14 | O sistema deve permitir o estorno parcial ou total de uma venda, com devolucao da quantidade ao stock e registo do motivo. |
| RF15 | O sistema deve permitir o registo de perdas e saidas de stock, indicando tipo de perda, quantidade, motivo, notas adicionais e evidencia quando aplicavel. |
| RF16 | O sistema deve submeter para aprovacao administrativa as perdas que ultrapassem limites definidos de quantidade ou valor. |
| RF17 | O sistema deve permitir ao administrador consultar e aprovar movimentos pendentes antes da aplicacao definitiva no stock. |
| RF18 | O sistema deve permitir a consulta do historico de perdas e dos movimentos de stock associados. |
| RF19 | O sistema deve permitir o registo de reposicoes de stock, incluindo quantidade, custo unitario, fornecedor, numero de factura, validade e evidencia quando disponivel. |
| RF20 | O sistema deve tratar reposicoes por lote, podendo reutilizar ou criar registos de produto conforme codigo de barras e validade. |
| RF21 | O sistema deve permitir a consulta do historico de reposicoes e dos respectivos dados operacionais. |
| RF22 | O sistema deve gerar relatorios em PDF sobre vendas, stock, movimentos, perdas, lucro, historico de vendas, produtividade, logs e visao consolidada do negocio. |
| RF23 | O sistema deve apresentar indicadores administrativos como total vendido, produto lider, horario de maior movimento, stock baixo, produtos proximos da validade e produtos com lucro negativo. |
| RF24 | O sistema deve disponibilizar indicadores de produtividade por periodo e por terminal. |
| RF25 | O sistema deve identificar padroes suspeitos de operacao, como perdas acima da media, perdas repetidas por produto, registos fora de horario e movimentos sem evidencia. |
| RF26 | O sistema deve permitir a gestao de regras de IVA, incluindo consulta, edicao, reposicao das regras oficiais e aplicacao dessas regras em novas vendas. |
| RF27 | O sistema deve registar logs das accoes dos utilizadores e permitir consulta, exportacao e limpeza desse historico pelo administrador. |

## Requisitos Nao Funcionais Sugeridos

| ID | Requisito nao funcional |
| --- | --- |
| RNF01 | O sistema deve garantir controlo de acesso por perfil, separando permissoes do administrador e do gerente. |
| RNF02 | O sistema deve proteger as senhas dos utilizadores por meio de hashing seguro antes do armazenamento. |
| RNF03 | O sistema deve limitar e controlar tentativas de recuperacao de acesso com perguntas de seguranca. |
| RNF04 | O sistema deve preservar a integridade dos dados em operacoes criticas, usando transaccoes com confirmacao ou reversao. |
| RNF05 | O sistema nao deve permitir vendas, estornos, perdas ou reposicoes com quantidades invalidas ou incoerentes. |
| RNF06 | O sistema deve manter a consistencia do stock, impedindo saidas superiores ao stock disponivel. |
| RNF07 | O sistema deve continuar operacional quando a API local estiver indisponivel, recorrendo automaticamente a base de dados local. |
| RNF08 | O sistema deve informar o estado da ligacao, distinguindo modo API e modo local. |
| RNF09 | O sistema deve apresentar interface clara, validacoes directas e fluxo simples de uso. |
| RNF10 | O sistema deve oferecer desempenho adequado em consultas frequentes, com paginacao, leituras optimizadas e carregamento em segundo plano nas telas mais pesadas. |
| RNF11 | O sistema deve manter rastreabilidade das accoes por meio de logs, datas, utilizadores, papeis e referencias das operacoes. |
| RNF12 | O sistema deve suportar geracao organizada de documentos PDF, com nomes validos, estrutura por pasta e evitacao de sobrescrita. |
| RNF13 | O sistema deve possuir estrutura modular, separando interface, logica de negocio, persistencia, comunicacao e geracao de relatorios. |
| RNF14 | O sistema deve permitir evolucao futura com inclusao de novos relatorios, regras de IVA, indicadores e modulos sem reescrita total. |
| RNF15 | O sistema deve manter a exactidao fiscal das vendas, guardando os dados de IVA aplicados no momento da operacao. |
| RNF16 | O sistema deve permitir auditoria posterior das operacoes de stock, pois os movimentos guardam origem, actor, data, estado de aprovacao e metadados relevantes. |
| RNF17 | O sistema deve funcionar em ambiente local com Python, Kivy, KivyMD, SQLite, Flask, requests e ReportLab. |
| RNF18 | O sistema deve favorecer recuperacao e verificacao operacional por meio de mecanismos de reconciliacao e rotinas de apoio ao controlo interno. |

## Nota Para a Monografia

Se a tabela ficar demasiado longa no corpo do capitulo, pode-se manter uma versao resumida e colocar a lista completa em apendice. O importante e nao reduzir o sistema a apenas vendas, stock e relatorios, porque o projecto real inclui perdas, reposicoes, estornos, IVA, logs, indicadores, aprovacoes e seguranca.

