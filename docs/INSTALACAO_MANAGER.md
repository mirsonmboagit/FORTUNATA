# Instalacao da App Manager

O pacote `SIGEMPEManager` e apenas o cliente de vendas. A API e a base de dados principal sao instaladas separadamente no pacote `LojaAPI`, no computador servidor.

## 1. Preparar o servidor uma vez

1. Copie a pasta `LojaAPI` para o computador que ficara ligado durante o uso do sistema.
2. Clique com o botao direito em `ATIVAR_API.bat` e escolha **Executar como administrador**.
3. Depois de ativar a API, execute `GERAR_LIGACAO_CLIENTE.bat`.
4. O ficheiro `SIGEMPELigacao.json` sera criado no Ambiente de Trabalho. Guarde-o com cuidado: ele contem a chave de ligacao.

O pacote da API configura o servico Windows, a base de dados e a chave segura. Nenhum destes elementos e criado dentro do Manager.

## 2. Ligar o Manager ao servidor

1. Copie a pasta inteira `SIGEMPEManager` para o computador cliente.
2. Copie tambem o ficheiro `SIGEMPELigacao.json` gerado no servidor.
3. Abra `Configurar Ligacao.cmd`.
4. Clique em **Importar ficheiro** e selecione `SIGEMPELigacao.json`.
5. Clique em **Testar e guardar**. A configuracao so e gravada se a API responder.
6. Clique em **Abrir app** ou execute `SIGEMPEManager.exe`.

## 3. O que o assistente do cliente faz

- importa IP, porta e chave do ficheiro de ligacao;
- testa a API antes de alterar a configuracao local;
- configura `config\app.json` com `db_mode: remote_strict`;
- guarda a chave em `config\.env` no computador cliente;
- abre o Manager quando a ligacao estiver pronta.

## 4. Regras importantes

- O servidor com `LojaAPI` deve estar ligado antes de abrir o Manager.
- O Manager nao inclui `LojaAPI.exe` nem uma base de dados de producao.
- Se o teste falhar, confirme o IP, a porta, a chave, o firewall e a rede local.
- Gere outro ficheiro de ligacao se a chave da API for alterada.

## 5. Instalacao local do cliente

Opcionalmente, um tecnico pode instalar para `%LOCALAPPDATA%\SIGEMPEManager` e criar atalho no Ambiente de Trabalho:

```powershell
.\install\install_manager_client.ps1 -ServerHost IP_DO_SERVIDOR -Port 8080 -ApiKey "A_CHAVE_DO_SERVIDOR"
```

## 6. Gerar o pacote novamente

No computador de desenvolvimento:

```powershell
.\scripts\build_manager_release.ps1
```

## 7. Atualizar sem apagar dados

Execute o actualizador da nova pasta:

```powershell
.\install\update_manager_client.ps1 -InstallDir "$env:LOCALAPPDATA\SIGEMPEManager"
```

O update preserva `config\.env`, configuracoes, relatorios, recibos e outros dados de runtime. A base principal continua no servidor e nao e levada pelo pacote Manager.
