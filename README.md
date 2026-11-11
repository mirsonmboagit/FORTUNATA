# SIGE MPE

Versao atual: `1.1.0`.

Sistema de gestao para mercearia/pequeno comercio, com uma aplicacao desktop, uma unica tela de login e base de dados SQLite partilhada. O perfil autenticado abre o painel de administrador ou de gerente, mantendo as respetivas permissoes.

## Aplicacoes

- `admin_app.py`: ponto de entrada do aplicativo desktop unico.
- `manager_app.py` e `MERCEARIA.py`: atalhos de compatibilidade; abrem o mesmo aplicativo e o mesmo login.
- `licensing/`: licenca offline assinada e ligada ao computador, validada antes do login.
- `scripts/superadmin_terminal.py`: terminal local para o proprietario emitir e renovar licencas.

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
python -m pytest -q
```

Para empacotamento:

```powershell
python -m pip install -r requirements-build.txt
```

Antes de qualquer pacote, execute `python scripts/preflight_release.py`. Os
scripts de build executam esta verificacao automaticamente.

## Execucao

Aplicativo desktop:

```powershell
python admin_app.py
```

Use as credenciais de administrador ou gerente na mesma tela. O sistema abre automaticamente o painel permitido para essa conta.

## Configuracao

Arquivos principais:

- `config/app.json`: caminho da base SQLite e diretorios de runtime.
- `config/app_settings.json`: preferencias do sistema, tema, idioma, recibos e scanner.
- `config/license.json`: ativa o modo de licenca offline assinada.
- `config/.env`: segredos locais, como as credenciais SMTP.
- `config/.env.example`: modelo seguro com as variaveis que podem ser configuradas.

Nunca versionar `.env`, bases reais, recibos, relatorios gerados, logs ou builds.

### Superadmin e licencas offline

Nao existe servidor, site, API de licencas ou painel web. O superadmin trabalha
somente no computador do proprietario pelo terminal local:

```powershell
python .\scripts\superadmin_terminal.py
```

Tambem existe o atalho `scripts\\abrir_superadmin_local.cmd` para abrir o
terminal por duplo clique.

Na primeira execucao, o terminal reaproveita de forma segura a credencial local
existente, quando houver, e cria uma chave privada protegida pelo Windows. A
chave privada nunca vai para o computador do cliente. O terminal configura um
unico e-mail privado do proprietario e envia a licenca assinada apenas para
esse endereco.

Na primeira utilizacao, o cliente clica em **PEDIR LICENCA**: o pedido sai pelo
mesmo SMTP usado na recuperacao de senha e chega ao Gmail privado configurado
pelo proprietario. Um emissor local nesse computador cria e envia a licenca
assinada automaticamente para esse mesmo e-mail; nao existe servidor, site nem
API. O pedido e unico por computador e o cliente nao precisa ver nem copiar o
seu codigo tecnico. Sem SMTP no computador do cliente, o programa abre um
e-mail preenchido como alternativa segura. O login so e liberado depois de
validar localmente a assinatura, o computador e a validade da licenca.

Veja o fluxo completo em [Superadmin offline](docs/SUPERADMIN_OFFLINE.md).
Depois de configurar o terminal pela primeira vez, feche e abra o aplicativo
desktop. Antes de distribuir uma nova versao aos clientes, gere novamente o
instalador para incluir a chave publica do emissor.

O APK antigo do gerente fica bloqueado em Android enquanto nao receber um
cofre seguro e o mesmo protocolo de licenca. Isto evita que ele seja um caminho
alternativo sem o controlo do superadmin.

### Recuperacao de palavra-passe por e-mail

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

O sistema envia os codigos de recuperacao apenas para o e-mail guardado no
cadastro; a tela de recuperacao nunca permite escolher outro destinatario.

Para emitir licencas, o terminal do superadmin pede a conta Gmail e a palavra-
passe de aplicacao uma unica vez na opcao de emissao automatica. Ela fica no
cofre DPAPI do computador do proprietario, nunca no projeto distribuido nem no
computador do cliente. Execute `scripts\\iniciar_emissor_automatico.cmd` para
manter o emissor local a verificar os pedidos recebidos.

## Testes

```powershell
python -m pytest -q
```

Os testes atuais cobrem partes importantes da base de dados, configuracao, IA e servicos. Antes de novas funcionalidades grandes, vale adicionar testes de fluxo completo para venda, reposicao, perda, relatorio e recibo.

## Estrutura principal

- `admin_app.py`: ponto de entrada principal do desktop unificado.
- `admin/`: telas e fluxos do administrador.
- `manager/`: tela de vendas e servicos do gerente.
- `database/`: acesso SQLite e automacoes.
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
