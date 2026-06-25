# Capitulo 4 - Apresentacao, Analise e Discussao dos Resultados

## Escopo analisado

Monografia: `Livros/Monografia - Mirson Mboa (Joe)5.docx`, paragrafos do `CAPITULO 4. APRESENTACAO, ANALISE E DISCUSSAO DOS RESULTADOS`.

Base de validacao usada exclusivamente a partir de `Livros`:

- Sommerville, I. (2011). *Engenharia de software*. 9. ed. Sao Paulo: Pearson Prentice Hall.
- Elmasri, R.; Navathe, S. B. (2011). *Sistemas de banco de dados*. 6. ed. Sao Paulo: Pearson Education do Brasil.
- Turban, E.; Volonino, L. (2011). *Tecnologia da informacao para gestao*. 8. ed. Porto Alegre: Bookman.

## Problema 1 - Muthemba & Chirindza nao verificavel

**Texto original da monografia**

> Tais funcionalidades alinham-se com as recomendacoes de Muthemba & Chirindza (2022), que destacam a importancia da tomada de decisao baseada em dados para aumentar a competitividade e a eficiencia das microempresas.

**Analise do problema**

Muthemba & Chirindza (2022) nao consta na pasta `Livros`. A referencia parece externa ao corpus disponibilizado e nao pode sustentar o capitulo. O conteudo deve ser substituido por Turban & Volonino, que tratam da conversao de dados operacionais em informacao, relatorios, analises e previsao.

**Citação verificada extraida dos livros**

> "Dados sobre clientes, vendas e outros elementos importantes"

Referencia: Turban & Volonino (2011), parte I, capitulo 2, pagina PDF 36.

**Novo texto sugerido**

O modulo de relatorios permite transformar dados de vendas, entradas, saidas de stock e produtos mais vendidos em informacao de apoio a gestao. Turban e Volonino (2011) explicam que dados de clientes, vendas e outros elementos relevantes podem ser seleccionados para analises adicionais, incluindo tendencias e previsao de demanda. Assim, a funcionalidade de relatorios do sistema contribui para que o gestor identifique padroes de consumo, acompanhe produtos de baixo desempenho e adopte medidas correctivas com maior fundamento.

**Referencia bibliografica completa**

Turban, E.; Volonino, L. (2011). *Tecnologia da informacao para gestao*. 8. ed. Porto Alegre: Bookman. Parte I, capitulo 2, secao sobre SIG/SSD, pagina PDF 36.

## Problema 2 - "outros estudos de digitalizacao" sem fonte

**Texto original da monografia**

> Espera-se que o tempo medio de processamento de vendas e actualizacao de stock seja significativamente reduzido, conforme observado em outros estudos de digitalizacao de pequenas empresas.

**Analise do problema**

O trecho menciona estudos nao identificados. Como nao ha fonte verificavel, a afirmacao deve ser reformulada como expectativa do prototipo ou resultado observado nos testes locais, sem generalizacao externa.

**Novo texto sugerido**

Nos testes do prototipo, a organizacao das telas e a automatizacao do registo indicam potencial para reduzir o tempo de processamento de vendas e actualizacao de stock em relacao ao procedimento manual observado. Esta conclusao deve ser entendida como resultado preliminar do contexto estudado, exigindo medicao quantitativa posterior para confirmar ganhos de tempo com maior precisao.

**Referencia bibliografica completa**

Sem fonte externa validada na pasta `Livros`; trecho reformulado como resultado local do estudo.

## Problema 3 - Requisitos de software com citacoes diretas longas nao verificadas literalmente

**Textos originais da monografia**

> Segundo Sommerville (2011, p. 103): "Os requisitos de software descrevem os servicos que o sistema deve fornecer..."

> Sommerville (2011, p. 112) destaca: "Os requisitos nao funcionais referem-se as propriedades do sistema..."

**Analise do problema**

Sommerville esta presente na pasta, mas as paginas indicadas na monografia nao foram confirmadas como correspondentes literais aos excertos. A obra disponivel sustenta a engenharia de requisitos, mas e preferivel usar parafrase rastreavel nas paginas encontradas.

**Citação verificada extraida dos livros**

> "Especificacao de requisitos."

Referencia: Sommerville (2011), capitulo 2, pagina PDF 40, pagina interna 25.

**Novo texto sugerido**

Os requisitos do sistema foram definidos a partir da observacao das operacoes da mercearia e das necessidades dos utilizadores. Em Sommerville (2011), a engenharia de requisitos inclui a elicitacao, analise e especificacao dos requisitos, transformando informacoes recolhidas junto dos utilizadores e do ambiente de trabalho em uma descricao organizada do que o sistema deve fazer e das restricoes a que deve obedecer. Nesta monografia, os requisitos funcionais representam as operacoes esperadas do sistema, enquanto os requisitos nao funcionais expressam qualidades como seguranca, desempenho, usabilidade e fiabilidade.

**Referencia bibliografica completa**

Sommerville, I. (2011). *Engenharia de software*. 9. ed. Sao Paulo: Pearson Prentice Hall. Capitulo 2, secao sobre processos de engenharia de requisitos, pagina PDF 40, pagina interna 25.

## Problema 3.1 - Pressman (2010) nao verificavel

**Texto original da monografia**

> Os requisitos funcionais indicam as operacoes que o sistema deve executar para satisfazer as necessidades do utilizador. De acordo com Pressman (2010, p. 75): "Requisitos funcionais descrevem as funcoes e comportamentos que um sistema deve possuir..."

**Analise do problema**

Pressman (2010) nao existe na pasta `Livros`. A monografia tambem referencia Pressman & Maxim (2020) na bibliografia, mas essa obra igualmente nao esta disponivel. O conteudo sobre requisitos pode ser fundamentado por Sommerville (2011), que esta presente.

**Novo texto sugerido**

Os requisitos funcionais indicam as operacoes que o sistema deve executar para responder as necessidades dos utilizadores, como autenticar perfis, registar vendas, actualizar stock, gerir produtos e emitir relatorios. A definicao destes requisitos deve resultar da elicitacao e analise junto dos utilizadores e do ambiente operacional, conforme o processo de engenharia de requisitos descrito por Sommerville (2011).

**Referencia bibliografica completa**

Sommerville, I. (2011). *Engenharia de software*. 9. ed. Sao Paulo: Pearson Prentice Hall. Capitulo 2, secao sobre elicitacao, analise e especificacao de requisitos, pagina PDF 40, pagina interna 25.

## Problema 4 - Diagrama de casos de uso e diagrama de classes com referencias nao totalmente alinhadas

**Textos originais da monografia**

> Segundo Sommerville (2011), o Diagrama de Casos de Uso facilita a comunicacao entre utilizadores finais e projectistas de sistemas...

> De acordo com Larman (2005), o Diagrama de Classes e essencial na modelacao de sistemas orientados por objectos...

**Analise do problema**

Sommerville esta disponivel e pode sustentar modelacao de sistemas. Larman nao esta na pasta `Livros`, logo deve ser removido como referencia. Para classes/modelos estruturais, Sommerville tambem fornece base verificavel.

**Citação verificada extraida dos livros**

> "Modelos estruturais de softwares exibem a organizacao de um sistema"

Referencia: Sommerville (2011), capitulo 5, secao 5.3 "Modelos estruturais", pagina PDF 104, pagina interna 89.

**Novo texto sugerido**

O diagrama de casos de uso foi utilizado para representar as principais interaccoes entre os utilizadores e o sistema, auxiliando a comunicacao dos requisitos funcionais. O diagrama de classes, por sua vez, descreve a organizacao estrutural do sistema, indicando entidades, atributos e relacoes relevantes para o funcionamento da aplicacao. Sommerville (2011) apresenta os modelos estruturais como representacoes da organizacao do software em termos de componentes e relacionamentos, o que fundamenta o uso do diagrama de classes nesta monografia.

**Referencia bibliografica completa**

Sommerville, I. (2011). *Engenharia de software*. 9. ed. Sao Paulo: Pearson Prentice Hall. Capitulo 5, secao 5.3 "Modelos estruturais", pagina PDF 104, pagina interna 89.

## Problema 5 - Base de dados do sistema precisa de fundamentacao propria

**Texto original relacionado**

Requisitos e telas descrevem registo de produtos, vendas, fornecedores, reposicoes, perdas e relatorios, mas a fundamentacao bibliografica da persistencia de dados esta dispersa.

**Analise do problema**

Como o sistema desenvolvido depende de armazenamento e consulta de dados, convem inserir base teorica sobre banco de dados.

**Citação verificada extraida dos livros**

> "geracao de relatorios com base nos dados"

Referencia: Elmasri & Navathe (2011), capitulo 1, pagina PDF 23.

**Novo texto sugerido**

A persistencia dos dados do sistema justifica-se pela necessidade de armazenar, actualizar, consultar e gerar relatorios sobre vendas, produtos, stock e perdas. Elmasri e Navathe (2011) explicam que a manipulacao de banco de dados inclui consultas, actualizacoes e geracao de relatorios com base nos dados, funcoes directamente relacionadas aos modulos implementados no prototipo.

**Referencia bibliografica completa**

Elmasri, R.; Navathe, S. B. (2011). *Sistemas de banco de dados*. 6. ed. Sao Paulo: Pearson Education do Brasil. Capitulo 1, secao sobre SGBD e manipulacao de dados, pagina PDF 23.

## Referencias utilizadas neste capitulo

Elmasri, R.; Navathe, S. B. (2011). *Sistemas de banco de dados*. 6. ed. Sao Paulo: Pearson Education do Brasil.

Sommerville, I. (2011). *Engenharia de software*. 9. ed. Sao Paulo: Pearson Prentice Hall.

Turban, E.; Volonino, L. (2011). *Tecnologia da informacao para gestao*. 8. ed. Porto Alegre: Bookman.

## Ajuste de citacoes ao padrao solicitado

Regra aplicada: as citacoes curtas devem aparecer obrigatoriamente entre aspas, no modelo `Autor, ano "citacao" (pagina)`. As citacoes longas devem seguir o padrao da monografia: frase introdutoria variada, autor, ano, pagina, dois pontos e excerto em bloco.

### Citacoes curtas prontas para substituicao

1. De acordo com Turban e Volonino, 2011 "Dados sobre clientes, vendas e outros elementos importantes" (p. PDF 36) podem ser seleccionados para analises adicionais, o que fundamenta o modulo de relatorios do sistema.

2. Conforme Sommerville, 2011 "Especificacao de requisitos" (p. PDF 40), as informacoes obtidas na analise devem ser transformadas em requisitos organizados.

3. Segundo Sommerville, 2011 "Modelos estruturais de softwares exibem a organizacao de um sistema" (p. PDF 104), o diagrama de classes e adequado para representar componentes, atributos e relacoes do sistema.

4. Elmasri e Navathe, 2011 "geracao de relatorios com base nos dados" (p. PDF 23) corresponde a uma das funcoes da manipulacao de bancos de dados, directamente associada aos relatorios do prototipo.

### Citacoes longas sugeridas no padrao da monografia

Para fundamentar os requisitos do sistema, pode ser introduzida a seguinte citacao:

Conforme Sommerville (2011, p. PDF 40):

> Especificacao de requisitos. E a atividade de traduzir as informacoes obtidas durante a atividade de analise em um documento que defina um conjunto de requisitos.

Para fundamentar o diagrama de classes, pode ser introduzida a seguinte citacao:

Segundo Sommerville (2011, p. PDF 104):

> Os modelos estruturais de softwares exibem a organizacao de um sistema em termos de seus componentes e seus relacionamentos.

Referencia: Sommerville, I. (2011). *Engenharia de software*. 9. ed. Sao Paulo: Pearson Prentice Hall. Capitulo 2, pagina PDF 40; capitulo 5, secao 5.3, pagina PDF 104.
