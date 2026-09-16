# Relatório de otimização de desempenho

Data: 14 de setembro de 2026

## Alcance da análise

A auditoria analisou 176 ficheiros Python e KV (88 603 linhas), procurando
consultas SQLite, threads, trabalhos agendados pelo Clock, recriação de
widgets, listas extensas e imports no caminho de arranque. O inventário
reproduzível está em `docs/performance-audit.json`.

As alterações preservam as regras de negócio, os dados devolvidos e o desenho
visual. O catálogo desktop já usava paginação e RecycleView; a otimização foi
concentrada nos pontos que ainda criavam widgets ou faziam trabalho repetido.

## Alterações aplicadas

| Área | Problema encontrado | Alteração | Ganho esperado |
| --- | --- | --- | --- |
| Arranque SQLite | Cada arranque recalculava e escrevia todos os SKUs, incluindo os já corretos. | `_rebuild_all_skus()` lê em lotes de 512 e escreve apenas os SKUs alterados. | Menos I/O, WAL e tempo de arranque em catálogos grandes. |
| Insights administrativos | Havia uma consulta de vendas por cada produto com stock baixo. | A velocidade de vendas é agregada uma vez e reutilizada pelos produtos. | Menos consultas e menor CPU na HOME. |
| Filtros históricos | Consultas por proprietário usavam `COALESCE(owner_username, '')` e `DATE(sale_date)` sem índice correspondente. | Índice de expressão `idx_sales_owner_day`. | Procura indexada de histórico para sessões com proprietário ativo. |
| Threads SQLite | HOME, histórico de reposições e histórico de perdas partilhavam cursor/conexão com a UI. | `background_connection()` abre uma conexão isolada por worker, com cache de 4 MiB, e fecha-a ao terminar. | Elimina conflitos de cursor e reduz RAM de workers breves. |
| Threads SQLite | Workers voltavam a negociar WAL. | Conexões de background reutilizam o journal configurado pela conexão principal. | Menos trabalho e menor risco de contenção ao abrir workers. |
| HOME responsiva | Vários eventos de redimensionamento agendavam o mesmo cálculo de layout. | `Clock.create_trigger()` coalesce pedidos por frame. | Menor CPU durante resize/orientação. |
| Consistência da HOME | Uma resposta atrasada podia pertencer ao período anterior do gráfico. | O período é capturado antes da thread; respostas obsoletas são descartadas e recarregadas. | Evita renderização de dados de um filtro diferente. |
| Logs administrativos | Cada registo criava widgets próprios. | RecycleView reutiliza os cartões visíveis e preserva textos, cores, filtros e altura. | RAM e tempo de scroll proporcionais às linhas visíveis. |
| Relatórios | `pandas` era importado ao criar a tela, mesmo sem consulta. | Import adiado até existirem dados para transformar. | Abertura mais rápida e menor RAM quando Relatórios não é usado. |
| POS mobile | Cliente, login e POS eram importados antes de decidir o acesso. | Imports adiados; POS criado no primeiro acesso e depois reutilizado. | Menor tempo de arranque e memória inicial. |
| APK | Código exclusivamente desktop ainda podia seguir para a fonte do Buildozer. | Padrões de exclusão para base local, telas desktop, servidores, PDFs, IA e artefactos. | 21 ficheiros, 1 126 929 bytes de código-fonte elegíveis para exclusão antes de compressão. |

## Medição reproduzível

O benchmark usa uma base temporária com 1 000 produtos e 30 000 vendas. O
ficheiro `docs/performance-benchmark.json` guarda o resultado e
`scripts/benchmark_performance.py` permite repeti-lo sem tocar na base real.

| Operação | Antes | Depois | Resultado |
| --- | ---: | ---: | --- |
| Reconstrução de SKUs | 12,869 ms; 1 002 instruções SQL; 1 000 escritas | 8,444 ms; 2 instruções SQL; 0 escritas | elimina as escritas quando não há alteração |
| Insights administrativos | 103,708 ms; 1 008 instruções SQL | 96,658 ms; 9 instruções SQL | mesmos insights (`identical_insights: true`) |

O plano de execução também confirma uso de `idx_sales_owner_day` em consultas
por proprietário e dia. Os tempos são indicativos: variam com hardware,
tamanho real da base e conteúdo do cache SQLite.

## Validação

- Suite completa: `202 passed`.
- Validação direcionada posterior: `42 passed`.
- `compileall` nos módulos alterados.
- Verificação visual do RecycleView de logs: 60 linhas usaram 4 cartões
  visíveis reutilizados, preservando conteúdo e aparência.

## Próximas melhorias por prioridade

1. Medir no dispositivo Android e em bases reais com `py-spy` ou Android Studio
   profiler; os números atuais são sintéticos e não substituem perfil de APK.
2. Converter as listas paginadas de perdas e reposições para RecycleView se o
   limite deixar de ser 300 ou se houver scroll frequente em dispositivos com
   pouca RAM. A paginação e renderização por lotes atuais já evitam bloqueio.
3. Rever `get_admin_home_snapshot()` e os relatórios com `EXPLAIN QUERY PLAN`
   nas bases de clientes antes de adicionar mais índices; índices redundantes
   aumentam o custo de escrita.
4. Criar um build release Android e comparar tamanho e arranque reais antes e
   depois. A exclusão foi validada pela configuração, não por um APK assinado
   neste ambiente Windows.
5. Consolidar o padrão de worker SQLite nos restantes módulos que ainda usam
   `Thread`, sempre mantendo widgets e propriedades Kivy no thread principal.
