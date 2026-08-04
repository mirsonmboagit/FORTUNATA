# SIGE MPE

Versao atual: `1.0.0`.

Sistema de gestao para mercearia/pequeno comercio, com aplicacoes separadas para administrador e gerente, API local, base de dados SQLite, relatorios PDF, controlo de stock, perdas, reposicao, validade, scanner e apoio por IA.

## Aplicacoes

- `admin_app.py`: aplicacao do administrador. Gere produtos, stock, relatorios, configuracoes, utilizadores e visao geral do negocio.
- `manager_app.py`: aplicacao do gerente/caixa. Focada em vendas, historico e operacao diaria.
- `api_server_app.py`: servidor local da API, usado quando o sistema esta em modo remoto/hibrido.

## Requisitos

- Python 3.11+ recomendado.
- Windows para funcionalidades dependentes de `pywin32`, impressoras e empacotamento atual.
- Dependencias em `requirements.txt`.
- Dependencias de desenvolvimento em `requirements-dev.txt`.
- Dependencias de build em `requirements-build.txt`.

## Instalacao rapida

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Para desenvolvimento e testes:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover
```

Para empacotamento:

```powershell
python -m pip install -r requirements-build.txt
```

Antes de qualquer pacote, execute `python scripts/preflight_release.py`. Os
scripts de build executam esta verificacao automaticamente.

## Execucao

Administrador:

```powershell
python admin_app.py
```

Gerente:

```powershell
python manager_app.py
```

API local:

```powershell
python api_server_app.py
```

Por padrao, a API usa `config/api.json` e a aplicacao usa `config/app.json`.

## Configuracao

Arquivos principais:

- `config/app.json`: modo da base, URL da API, tempos limite e diretorios de runtime.
- `config/api.json`: host, porta e runner da API local.
- `config/service.json`: parametros do servico Windows.
- `config/app_settings.json`: preferencias do sistema, tema, idioma, recibos e scanner.
- `config/.env`: segredos locais, como `API_KEY` e as credenciais SMTP.
- `config/.env.example`: modelo seguro com as variaveis que podem ser configuradas.

Nunca versionar `.env`, bases reais, recibos, relatorios gerados, logs ou builds.

### Envio de codigos por e-mail

Copie `config/.env.example` para `config/.env` e configure o servidor SMTP:

```env
SMTP_HOST=smtp.seu-provedor.com
SMTP_PORT=587
SMTP_USERNAME=seu_utilizador
SMTP_PASSWORD=seu_token_ou_senha
SMTP_FROM_EMAIL=recuperacao@seu-dominio.com
SMTP_FROM_NAME=SIGE MPE
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

O computador que executa a API precisa de acesso a Internet. O sistema envia
os codigos apenas para o e-mail guardado no cadastro; a tela de recuperacao
nunca permite escolher outro destinatario.

## Testes

```powershell
python -m unittest discover
```

Os testes atuais cobrem partes importantes da base de dados, API, configuracao, IA e servicos. Antes de novas funcionalidades grandes, vale adicionar testes de fluxo completo para venda, reposicao, perda, relatorio e recibo.

## Estrutura principal

- `admin_app.py`, `manager_app.py`, `api_server_app.py`: pontos de entrada principais.
- `admin/`: telas e fluxos do administrador.
- `manager/`: tela de vendas e servicos do gerente.
- `database/`: acesso SQLite, cliente remoto/hibrido e automacoes.
- `server/`: API Flask/Waitress.
- `utils/`: configuracoes, i18n, IA, relatorios/telas auxiliares e utilitarios.
- `pdfs/`: geracao e visualizacao de relatorios PDF.
- `AI/`: coleta, analise e alertas inteligentes.
- `api/`: integracoes externas para dados de produtos.
- `scripts/`: automacoes, instaladores, builds e specs de empacotamento.
- `docs/`: documentacao, referencias e materiais academicos.
- `tests/`: testes automatizados.

Para a organizacao detalhada das pastas, ver `docs/ESTRUTURA_PROJETO.md`.

## Proxima fase recomendada

Ver `docs/ROADMAP_TECNICO.md`.
