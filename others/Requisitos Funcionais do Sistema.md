# Requisitos Funcionais do Sistema

Este documento apresenta os requisitos funcionais com base no comportamento real do sistema. A descricao foi organizada a partir dos modulos de autenticacao, gestao de produtos, vendas, stock, perdas, reposicoes, relatorios, IVA, logs e monitorizacao administrativa.

Actores principais:
- Administrador
- Gerente

Lista de requisitos:

RF01. O sistema deve permitir a seleccao do perfil de acesso e a autenticacao de utilizadores conforme o papel autorizado.

RF02. O sistema deve permitir a configuracao do administrador inicial e a actualizacao das suas credenciais quando necessario.

RF03. O sistema deve permitir a recuperacao de senha por meio de perguntas de seguranca previamente configuradas.

RF04. O sistema deve permitir ao administrador criar, consultar e remover contas de utilizadores do sistema, com foco na gestao de contas do tipo manager.

RF05. O sistema deve permitir o registo, a edicao, a consulta e a remocao logica de produtos.

RF06. O sistema deve permitir o cadastro de produtos com dados como descricao, categoria, preco de venda, preco de compra, stock, codigo de barras, data de validade, tipo de venda, dados de embalagem e regra de IVA.

RF07. O sistema deve permitir a pesquisa e a filtragem de produtos por texto, categoria, codigo de barras, SKU e outras chaves de identificacao disponiveis.

RF08. O sistema deve permitir a localizacao de produtos por codigo de barras, incluindo a seleccao do lote mais adequado quando existirem varios registos para o mesmo codigo.

RF09. O sistema deve permitir o registo de vendas de produtos por unidade, por peso e por embalagem, de acordo com a configuracao de cada artigo.

RF10. O sistema deve calcular automaticamente o valor total da venda e aplicar a regra de IVA activa ao produto vendido.

RF11. O sistema deve actualizar automaticamente o stock existente e o stock vendido apos cada venda registada com sucesso.

RF12. O sistema deve permitir a emissao de recibo de venda em formato PDF apos a conclusao da operacao comercial.

RF13. O sistema deve permitir a consulta do historico de vendas, com filtros por periodo e com acesso aos detalhes de cada registo.

RF14. O sistema deve permitir o estorno parcial ou total de uma venda, com devolucao da quantidade ao stock e registo do motivo do estorno.

RF15. O sistema deve permitir o registo de perdas e saidas de stock, indicando o tipo de perda, a quantidade, o motivo, notas adicionais e, quando aplicavel, evidencia anexada.

RF16. O sistema deve submeter para aprovacao administrativa as perdas que ultrapassem os limites definidos de quantidade ou valor.

RF17. O sistema deve permitir ao administrador consultar e aprovar movimentos pendentes antes da aplicacao definitiva no stock.

RF18. O sistema deve permitir a consulta do historico de perdas e de movimentos de stock associados a essas ocorrencias.

RF19. O sistema deve permitir o registo de reposicoes de stock, incluindo quantidade, custo unitario, fornecedor, numero de factura, validade e evidencia quando disponivel.

RF20. O sistema deve tratar reposicoes por lote, podendo reutilizar ou criar registos de produto conforme o codigo de barras e a data de validade informada.

RF21. O sistema deve permitir a consulta do historico de reposicoes de stock e dos respectivos dados operacionais.

RF22. O sistema deve gerar relatorios em PDF para areas como vendas, stock, movimentos, perdas, lucro, historico de vendas, produtividade, logs e visao consolidada do negocio.

RF23. O sistema deve apresentar indicadores administrativos como total vendido, produto lider, horario de maior movimento, stock baixo, produtos proximos da validade e produtos com lucro negativo.

RF24. O sistema deve disponibilizar indicadores de produtividade por periodo e por terminal, apoiando a leitura do desempenho operacional.

RF25. O sistema deve identificar padroes suspeitos de operacao, como perdas acima da media, perdas repetidas por produto, registos fora de horario e movimentos sem evidencia.

RF26. O sistema deve permitir a gestao de regras de IVA, incluindo consulta, edicao, reposicao das regras oficiais e aplicacao dessas regras nas novas vendas.

RF27. O sistema deve registar logs das accoes dos utilizadores e permitir a consulta, exportacao e limpeza desse historico pelo administrador.

