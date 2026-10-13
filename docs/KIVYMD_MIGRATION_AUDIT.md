# Auditoria de migração KivyMD para Kivy

## Estado inicial

A pesquisa recursiva de fontes Python e KV identificou dependência direta de
KivyMD em telas, componentes reutilizáveis, popups, visualizador PDF e nas
configurações de empacotamento. O worktree já continha alterações locais antes
desta auditoria; elas não devem ser descartadas durante a migração.

Contagens de referências no código de interface:

| Componente | Referências |
| --- | ---: |
| `MDLabel` | 513 |
| `MDBoxLayout` | 443 |
| `MDFlatButton` | 213 |
| `MDDialog` | 159 |
| `MDRaisedButton` | 159 |
| `MDCard` | 155 |
| `MDTextField` | 141 |
| `MDIcon` | 44 |
| `MDDropdownMenu` | 31 |
| `MDGridLayout` | 30 |
| `MDScreen` | 26 |

As propriedades Material mais usadas são `theme_text_color` (598),
`md_bg_color` (456), `font_style` (261), `radius` (235), `elevation` (207) e
`adaptive_height` (90). Portanto uma substituição global por widgets Kivy
base quebraria regras KV e alteraria o visual.

## Superfícies afetadas

- Aplicação e tema: `app_base.py` (`MDApp` e `theme_cls`).
- Telas: login, admin, manager, mobile e telas de stock, relatórios, perdas e
  histórico.
- Componentes próprios que atualmente herdam KivyMD:
  `tooltip_widgets.py`, `hover_widgets.py`, dashboards, banners e popups AI.
- UI criada dinamicamente em Python: formulários, menus, diálogos, snackbars,
  seletores de data e listas.
- KV: telas de login, admin, manager, mobile, settings, relatórios, stock e
  perdas.
- Empacotamento: `requirements-runtime.txt`, `requirements-mobile.txt` e
  especificações de build que citam KivyMD.

## Dependências funcionais a reproduzir em Kivy

1. Tema nativo da aplicação e tokens de cor, sem `theme_cls` de KivyMD.
2. Card com preenchimento, borda, raio e sombra leve desenhados em canvas.
3. Label com tipografia compatível e cores explícitas.
4. Botões com estados normal, hover, pressionado, ícone e tooltip.
5. Campo de texto com rótulo, cor de foco/erro e aparência rectangular.
6. Diálogo modal, menu ancorado, snackbar, seletor de data e controles de
   seleção/progresso.
7. Barra superior, listas e suporte a ícones através de uma fonte/atlas local
   independente de KivyMD.

## Ordem segura de migração

1. Criar widgets nativos reutilizáveis e testes unitários para suas
   propriedades visuais e eventos.
2. Migrar `BaseApp` e o tema, mantendo temporariamente os nomes de tokens da
   aplicação.
3. Migrar componentes próprios e estruturas KV.
4. Migrar telas uma a uma, incluindo UI dinâmica, validando inicialização,
   navegação e testes após cada grupo.
5. Remover imports, regras KV e requisitos KivyMD somente quando a busca
   final não encontrar dependências produtivas.

## Progresso da implementação

- `BaseApp`: migrado de `MDApp` para `kivy.app.App`; `NativeTheme` mantém o
  contrato temporário de `theme_cls` para telas ainda em migração.
- Camada criada: `ui/components/native_widgets.py`, sem imports KivyMD, com
  screen, layouts, label, card, botões, campo, separador e desenho em canvas.
- Telas concluídas: `MobileLicenseRequiredScreen` e
  `MobileConnectionScreen`, `RestockHistoryScreen` e
  `LossesHistoryScreen`, além de `MobileManagerSalesScreen`, incluindo regras
  KV, criação incremental de linhas e diálogos próprios destas telas.
- Fluxo `mobile/manager/` e ecrã de licença mobile: sem imports, heranças ou
  widgets KivyMD em execução.
- Infraestrutura adicional: barra superior com ações, diálogo modal e
  catálogo local de ícones baseado no asset versionado; menu ancorado e
  snackbar nativos prontos para os consumidores desktop.
- Contratos mobile/histórico após a migração: `8 passed`, `18 passed` e
  `16 passed` nos grupos relacionados.

Contagem atual de referências remanescentes dos componentes estruturais:

| Componente | Inicial | Restante |
| --- | ---: | ---: |
| `MDLabel` | 513 | 468 |
| `MDBoxLayout` | 443 | 408 |
| `MDCard` | 155 | 149 |
| `MDTextField` | 141 | 128 |
| `MDScreen` | 26 | 17 |
| `MDGridLayout` | 30 | 31 |

## Riscos a controlar

- Não substituir `MDCard` por `BoxLayout` sem canvas: isso perde fundo,
  bordas, cantos e elevação.
- Não substituir `MDTextField`, menus, diálogos, date picker ou ícones por
  widgets mínimos: esses elementos têm comportamento e aparência próprios.
- As telas de admin e manager compartilham login, histórico e perdas; a
  conversão deve manter ambos os fluxos compatíveis.
- O catálogo de ícones de KivyMD não está versionado nos assets do projeto.
  Uma fonte/atlas local e o mapeamento necessário devem existir antes de
  remover a dependência de empacotamento.

## Estado final da migração

- Dependências executáveis `kivymd`: **0** (imports Python, KV, bootstrap e
  factories testadas).
- PDF viewer: usa `Popup`, `ScrollView`, `KivyImage` e controles `Native*`;
  navegação, zoom, impressão, abertura externa e tratamento de erro foram
  preservados.
- AI: assistant e banners usam cards, campos, menus, progresso e ícones da
  camada nativa. O mapa de ícones e a fonte estão no repositório.
- i18n: o hook de diálogos agora observa `NativeDialog` e preserva a
  localização reativa dos widgets.
- Empacotamento: KivyMD foi removido de requirements, Buildozer e specs
  PyInstaller.
- Prova sem KivyMD: um import hook bloqueou o pacote e construiu login,
  Manager, Admin, relatórios, reposição, perdas, histórico e Settings, além
  de carregar PDF, AI e i18n.
- As regras KV ainda usam nomes `MD*` como nomes de compatibilidade, mas o
  `Factory` resolve todos para `Native*`; nenhum deles carrega KivyMD.
- Falha não relacionada conhecida: `test_license_control_inbox` espera a
  assinatura integral de uma licença, mas o extrator atual retorna somente o
  payload (`SIGE-LIC1.payload`).
