# Estrutura do projeto

Este documento explica onde cada tipo de codigo deve viver. A regra geral e simples: telas ficam em `screens`, regras de negocio em `business`, helpers puros em `core`, configuracao em `config`, integracoes fisicas em `hardware` e IA em `ai`.

## Raiz

Manter a raiz pequena. Ela deve conter apenas os pontos de entrada, requisitos, README, configuracoes legadas ainda suportadas e arquivos essenciais do repositorio.

- `admin_app.py`: entrada da aplicacao do administrador.
- `manager_app.py`: entrada da aplicacao do gerente/caixa.
- `api_server_app.py`: entrada da API local.
- `admin/`: telas e componentes especificos do administrador.
- `manager/`: telas e servicos especificos do gerente/caixa.
- `database/`: SQLite, cliente remoto/hibrido, provider e automacoes de dados.
- `server/`: API local Flask/Waitress.
- `api/`: integracoes externas para dados de produtos.
- `pdfs/`: geracao e visualizacao de PDFs.
- `ui/`: componentes visuais reutilizaveis.
- `tests/`: testes automatizados.
- `docs/`: documentacao tecnica e operacional.
- `utils/`: pacote compartilhado, organizado por dominio.
- `assets/`: icones, fontes, imagens e sons usados pela interface.
- `locales/`: traducoes da aplicacao.
- `scripts/`: scripts operacionais, instaladores, builds e empacotamento.
- `config/`: configuracoes versionaveis e exemplos.
- `data/`: dados locais e artefatos gerados em runtime.

## `scripts/`

- `scripts/build_*.ps1`: builds de distribuicao.
- `scripts/install_*_client.ps1` e `scripts/update_*_client.ps1`: instalacao e atualizacao dos clientes.
- `scripts/windows/`: scripts `.bat` auxiliares do Windows.
- `scripts/packaging/`: arquivos `.spec` do PyInstaller.
- `scripts/pyinstaller_kivy_runtime_hook.py`: hook de runtime do PyInstaller/Kivy.

## `docs/`

- `docs/INSTALACAO_ADMIN.md` e `docs/INSTALACAO_MANAGER.md`: guias de instalacao.
- `docs/ROADMAP_TECNICO.md`: proximas melhorias tecnicas.
- `docs/ESTRUTURA_PROJETO.md`: este mapa da estrutura.
- `docs/referencias/`: PDFs e materiais externos de referencia.
- `docs/monografia/`: capitulos e materiais academicos relacionados ao projeto.

## `tests/`

- `tests/test_*.py`: testes automatizados executados por `python -m unittest discover`.
- `tests/helpers.py`: auxiliares compartilhados pelos testes.
- `tests/manual/`: suites ou scripts de teste manual, como `testes_geral.py`.

## `utils/`

Evitar novos arquivos soltos diretamente em `utils/`. Cada modulo deve entrar numa subpasta de dominio. A raiz de `utils` existe apenas para declarar o pacote.

### `utils/config/`

Configuracao, caminhos, runtime e estado operacional:

- `app_config.py`
- `device_config.py`
- `env_loader.py`
- `logging_setup.py`
- `paths.py`
- `system_identity.py`
- `system_status.py`
- `theme.py`

### `utils/core/`

Helpers puros, sem dependencia de Kivy ou banco:

- `formatters.py`
- `focus_navigation.py`
- `i18n.py`
- `i18n_runtime.py`
- `perf_utils.py`

### `utils/business/`

Regras e utilitarios de dominio:

- `expiry_alerts.py`
- `receipt_policy.py`
- `security_questions.py`
- `vat.py`

### `utils/hardware/`

Integracoes com dispositivos e recursos locais:

- `thermal_printer.py`
- `vision.py`

### `utils/ai/`

Experiencias e respostas de IA:

- `ai_assistant_popup.py`
- `ai_insights.py`
- `ai_popups.py`

### `utils/screens/`

Telas compartilhadas e seus `.kv`:

- `settings.py` e `settings_layout.kv`
- `reports_screen.py` e `reports_screen.kv`
- `sales_history_screen.py`
- `losses_screen.py` e `losses_screen.kv`
- `losses_history_screen.py` e `losses_history_screen.kv`
- `restock_screen.py` e `restock_screen.kv`
- `restock_history_screen.py` e `restock_history_screen.kv`

## Imports

Usar sempre os caminhos organizados por dominio. Imports antigos como `from utils.paths import ROOT_DIR` nao devem ser usados.

```python
from utils.config.paths import ROOT_DIR
from utils.core.formatters import format_money
from utils.business.vat import compute_vat_breakdown
```
