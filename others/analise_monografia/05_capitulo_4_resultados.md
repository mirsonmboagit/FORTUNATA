# Capitulo 4 - Apresentacao, Analise e Discussao dos Resultados

## O Que Esta Bem

- O capitulo apresenta o sistema desenvolvido e tenta ligar funcionalidades aos problemas identificados.
- A separacao entre area administrativa e area operacional esta correcta.
- A inclusao de requisitos, diagramas e telas fortalece a demonstracao do produto.
- O texto mostra preocupacao com autenticacao, stock, vendas, relatorios e indicadores.

## Problemas Graves

- Os dois primeiros paragrafos do capitulo estao formatados como `Titulo 2`, mas devem ser texto normal.
- Varios paragrafos das seccoes 4.1 e 4.2 tambem estao como `Titulo 2`, gerando erro no indice automatico.
- A expressao "responde as necessidades" deve ser "responde as necessidades" apenas se sem acento por limitacao tipografica, mas o correcto academico e "responde as necessidades" com crase inexistente em portugues; melhor: "responde as necessidades" ou "responde as exigencias". Em norma cuidada: "responde as necessidades" deve ser revisto para "responde as necessidades" nao resolve visualmente sem acentos; usar "atende as necessidades" ou "responde as necessidades identificadas" conforme norma local.
- A palavra "analise" aparece sem acento em varias partes. Corrigir para "analise" se o documento estiver sem acentos por opcao, ou "analise" com acento se estiver em portugues academico completo. Como o documento usa acentos, deve ser "analise".
- Ha dados numericos sem prova metodologica:
  - reducao de erros de 8% para 0,5%;
  - divergencias de stock de 12% para 1,2%;
  - reducao de tempo de 5 para 2 minutos.
- A frase "achados de que destacam" esta incompleta. Falta o autor ou a expressao deve ser reformulada.
- O texto diz "feedback simulado do gestor". Feedback simulado enfraquece a credibilidade. Deve ser "feedback preliminar", se houve contacto real, ou retirar.
- Ha contradicao com o capitulo 5, que afirma que o sistema ainda nao foi implementado na pratica.
- A tabela de requisitos funcionais esta demasiado curta e nao corresponde ao sistema real.
- A tabela de requisitos nao funcionais esta demasiado curta e nao corresponde ao ficheiro de RNF existente no projecto.
- A fonte das tabelas de requisitos aparece como "Adaptado do Sommerville, 2011)", com parenteses a mais e sem autoria propria.
- As figuras estao mal numeradas: ha duas Figuras 5 no corpo.

## Alteracoes Recomendadas

1. Mudar todos os paragrafos narrativos do capitulo 4 para estilo normal.
2. Reformular a seccao 4.2 para nao apresentar estimativas como resultados medidos.
3. Substituir "feedback simulado" por "validacao preliminar" apenas se houve validacao real.
4. Substituir as tabelas de requisitos por versoes alinhadas aos ficheiros:
   - `others/Requisitos Funcionais do Sistema.md`
   - `others/Requisitos Nao Funcionais do Sistema.md`
5. Corrigir legendas e lista de figuras.

## Texto Sugerido Para 4.2

A analise dos resultados obtidos com o prototipo demonstra que a informatizacao dos processos comerciais pode reduzir falhas comuns associadas ao registo manual, especialmente nos processos de venda, actualizacao de stock, consulta de historicos e emissao de relatorios. Ao centralizar as operacoes numa unica base de dados, o sistema diminui a repeticao de registos, melhora a rastreabilidade das movimentacoes e facilita a consulta de informacoes pelo gestor.

No modulo de vendas, o sistema permite registar produtos, quantidades, precos e dados da operacao de forma estruturada. A actualizacao automatica do stock apos a conclusao da venda reduz a dependencia de anotacoes posteriores e contribui para maior consistencia entre as vendas realizadas e as quantidades disponiveis.

No controlo de stock, a solucao permite acompanhar entradas, saidas, perdas, reposicoes e produtos proximos da validade. Esta funcionalidade responde a uma das principais fragilidades observadas no cenario manual: a dificuldade de conhecer, em tempo oportuno, a situacao real dos produtos existentes na mercearia.

O modulo de relatorios e indicadores amplia a capacidade de analise do gestor, permitindo consultar informacoes sobre vendas, stock, perdas, lucro, produtividade e historico de operacoes. Assim, o sistema nao apenas regista dados, mas tambem organiza informacao relevante para apoiar a tomada de decisao.

## Correcao Das Legendas De Figuras

- Figura 1: substituir por figura adequada ao tema.
- Figura 2: Diagrama de Casos de Uso.
- Figura 3: Diagrama de Classes.
- Figura 4: Tela de Login.
- Figura 5: Tela de Inicio.
- Figura 6: Tela de Vendas.
- Figura 7: Tela de Controlo de Stock.
- Figura 8: Tela de Gestao de Produtos.
- Figura 9: Tela de Relatorios.

## Requisitos

As tabelas actuais do capitulo 4 devem ser substituidas por requisitos mais completos. O conteudo base ja esta nos ficheiros:

- `others/Requisitos Funcionais do Sistema.md`
- `others/Requisitos Nao Funcionais do Sistema.md`

Para a monografia, pode-se manter uma versao resumida, mas ela deve incluir pelo menos autenticacao, gestao de utilizadores, produtos, vendas, historico, estornos, perdas, aprovacoes, reposicoes, relatorios, indicadores, IVA e logs.

