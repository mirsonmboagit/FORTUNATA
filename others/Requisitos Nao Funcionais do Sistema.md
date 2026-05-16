# Requisitos Nao Funcionais do Sistema

Este documento apresenta os requisitos nao funcionais observados na estrutura e no comportamento do sistema. Os pontos abaixo descrevem qualidades esperadas para seguranca, desempenho, fiabilidade, manutencao e continuidade operacional.

Lista de requisitos:

RNF01. O sistema deve garantir controlo de acesso por perfil, separando claramente as permissoes do administrador e do gerente.

RNF02. O sistema deve proteger as senhas dos utilizadores por meio de hashing seguro antes do armazenamento em base de dados.

RNF03. O sistema deve limitar e controlar tentativas de recuperacao de acesso com perguntas de seguranca, reduzindo o risco de uso indevido.

RNF04. O sistema deve preservar a integridade dos dados em operacoes criticas, usando transaccoes com confirmacao ou reversao conforme o resultado da operacao.

RNF05. O sistema nao deve permitir vendas, estornos, perdas ou reposicoes com quantidades invalidas ou incoerentes com as regras de negocio.

RNF06. O sistema deve manter a consistencia do stock, impedindo saidas superiores ao stock disponivel e actualizando os valores de forma controlada.

RNF07. O sistema deve continuar operacional mesmo quando a API local estiver indisponivel, recorrendo automaticamente a base de dados local.

RNF08. O sistema deve informar o estado da ligacao, distinguindo o modo de uso da API e o modo local, para melhorar a transparencia operacional.

RNF09. O sistema deve apresentar interface clara, validacoes directas e fluxo simples de uso, facilitando a operacao diaria pelos utilizadores.

RNF10. O sistema deve oferecer desempenho adequado em consultas frequentes, recorrendo a paginacao, leituras optimizadas e carregamento em segundo plano nas telas mais pesadas.

RNF11. O sistema deve manter rastreabilidade das accoes por meio de logs, datas, utilizadores, papeis e referencias das operacoes executadas.

RNF12. O sistema deve suportar geracao organizada de documentos PDF, com nomes validos, estrutura por pasta e evitacao de sobrescrita de ficheiros.

RNF13. O sistema deve possuir estrutura modular, separando interface, logica de negocio, persistencia, comunicacao e geracao de relatorios.

RNF14. O sistema deve permitir evolucao futura com inclusao de novos relatorios, novas regras de IVA, novos indicadores e novos modulos sem reescrita total da aplicacao.

RNF15. O sistema deve manter a exactidao fiscal das vendas, guardando no registo os dados de IVA efectivamente aplicados no momento da operacao.

RNF16. O sistema deve permitir auditoria posterior das operacoes de stock, uma vez que os movimentos guardam origem, actor, data, estado de aprovacao e outros metadados relevantes.

RNF17. O sistema deve funcionar em ambiente local com a pilha tecnologica adoptada no projecto, nomeadamente Python, Kivy, KivyMD, SQLite, Flask, requests e ReportLab.

RNF18. O sistema deve favorecer a recuperacao e a verificacao operacional por meio de mecanismos de reconciliacao e rotinas de apoio ao controlo interno existentes na base de dados.

