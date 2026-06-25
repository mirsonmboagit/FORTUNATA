# Instalacao da App Manager

Este pacote instala a app `SIGEMPEManager.exe` e inclui um assistente visual para ligar Manager e Admin a mesma API e a mesma base de dados.

## 1. Fluxo recomendado por cliques

Use como servidor o computador que tem a base de dados principal.

No servidor principal:

1. Abra a pasta `SIGEMPEManager`.
2. Dê duplo clique em `Configurar Ligacao.cmd`.
3. Clique em `Preparar servidor`.
4. Aceite a permissao do Windows quando aparecer. O assistente configura a API, libera a porta no firewall e prepara o arranque automatico.
5. Clique em `Guardar ficheiro para clientes`. O ficheiro `SIGEMPELigacao.json` sera criado no Ambiente de Trabalho.

Nos computadores cliente:

1. Copie a pasta `SIGEMPEManager` para o computador cliente.
2. Copie tambem o ficheiro `SIGEMPELigacao.json` criado no servidor.
3. Dê duplo clique em `Configurar Ligacao.cmd`.
4. Clique em `Importar ficheiro` e escolha `SIGEMPELigacao.json`.
5. Clique em `Testar e guardar`.
6. Clique em `Abrir app` ou abra `SIGEMPEManager.exe`.

## 2. O que o assistente faz

No servidor principal, o assistente:

- configura `config\api.json` com `host: 0.0.0.0` e porta `8080`;
- gera ou reaproveita uma chave segura `API_KEY`;
- configura a app local em modo `hybrid`;
- libera a porta da API no firewall do Windows;
- inicia `SIGEMPEAPI.exe`;
- cria uma tarefa do Windows para iniciar a API quando o utilizador entrar no Windows;
- cria o ficheiro `SIGEMPELigacao.json` para os clientes.

Nos computadores cliente, o assistente:

- importa o IP, porta e chave do ficheiro de ligacao;
- configura `config\app.json` com `db_mode: remote_strict`;
- guarda a mesma `API_KEY`;
- testa a API antes de finalizar.

## 3. Instalacao local do cliente

Opcionalmente, um tecnico pode instalar para `%LOCALAPPDATA%\SIGEMPEManager` e criar atalho no ambiente de trabalho:

```powershell
.\install\install_manager_client.ps1 -ServerHost IP_DO_SERVIDOR -Port 8080 -ApiKey "A_MESMA_API_KEY_DO_SERVIDOR"
```

## 4. Regras importantes da API

- O utilizador final deve usar `Configurar Ligacao.cmd`.
- O servidor principal deve ficar ligado quando os clientes estiverem a usar o sistema.
- A chave do ficheiro `SIGEMPELigacao.json` deve ser guardada com cuidado.
- Se o teste falhar no cliente, confirme que o servidor esta ligado, que os dois computadores estao na mesma rede e que o ficheiro de ligacao e o mais recente.

## 5. Gerar o pacote novamente

No computador de desenvolvimento:

```powershell
.\scripts\build_manager_release.ps1
```

O pacote final fica em:

```text
dist\SIGEMPEManager
```

## 6. Atualizar sem apagar dados

Para atualizar um computador que ja tem o Manager instalado, copie a nova pasta `dist\SIGEMPEManager` para esse computador e execute o update a partir da pasta nova:

```powershell
.\install\update_manager_client.ps1 -InstallDir "$env:LOCALAPPDATA\SIGEMPEManager"
```

Se a app estiver instalada noutro local, informe essa pasta em `-InstallDir`.

O update preserva:

- `config\.env`, incluindo `API_KEY`
- `config\app.json`, incluindo `api_base_url` e `db_mode`
- `config\app_settings.json`, incluindo preferencias do utilizador
- base de dados local, se existir
- relatorios, recibos, logs e outros ficheiros gerados em runtime

Nos computadores cliente, a base principal fica no servidor e e acedida pela API. O pacote do Manager nao leva `database\inventory.db`.
