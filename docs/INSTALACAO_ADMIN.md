# Instalacao da App Admin

Este pacote instala a app `MerceariaAdmin.exe` e deixa a ligacao a API pronta para computadores cliente.

## 1. Computador servidor

Use como servidor o computador que tem a base de dados principal.

1. Descubra o IP do servidor na rede local:

   ```powershell
   ipconfig
   ```

2. Configure a API para aceitar ligacoes da rede e gerar uma chave forte:

   ```powershell
   .\scripts\configure_api.ps1 -Role Server -ServerHost 0.0.0.0 -Port 8080 -GenerateApiKey
   ```

   Guarde a `API_KEY` mostrada no terminal. Essa mesma chave deve ser usada em todos os computadores cliente.

3. Inicie a API no servidor:

   ```powershell
   python server\run_api.py
   ```

   Para deixar a API como servico do Windows, use o `install_service.bat` do projeto no computador servidor depois de colocar o `nssm.exe` no caminho configurado em `config\service.json`.

4. Libere a porta no firewall do Windows, se necessario:

   ```powershell
   New-NetFirewallRule -DisplayName "Loja API 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
   ```

## 2. Computadores cliente

Copie a pasta `dist\MerceariaAdmin` inteira para o outro computador.

No computador cliente, configure a app para apontar para o IP do servidor:

```powershell
.\install\configure_api.ps1 -Role Client -ServerHost IP_DO_SERVIDOR -Port 8080 -ApiKey "A_MESMA_API_KEY_DO_SERVIDOR" -TestConnection
```

Exemplo:

```powershell
.\install\configure_api.ps1 -Role Client -ServerHost 192.168.1.20 -Port 8080 -ApiKey "cole-a-chave-aqui" -TestConnection
```

Depois abra:

```powershell
.\MerceariaAdmin.exe
```

## 3. Instalacao local do cliente

Opcionalmente, no computador cliente, pode instalar para `%LOCALAPPDATA%\MerceariaAdmin` e criar atalho no ambiente de trabalho:

```powershell
.\install\install_admin_client.ps1 -ServerHost IP_DO_SERVIDOR -Port 8080 -ApiKey "A_MESMA_API_KEY_DO_SERVIDOR"
```

## 4. Regras importantes da API

- No servidor, `config\api.json` deve usar `host: 0.0.0.0` para aceitar outros computadores.
- Nos clientes, `config\app.json` deve usar `db_mode: remote_strict` para evitar vendas/produtos gravados num SQLite local por engano.
- A `API_KEY` no servidor e em todos os clientes deve ser exatamente igual.
- O endereco `api_base_url` nos clientes deve usar o IP real do servidor, por exemplo `http://192.168.1.20:8080`.
- Se o teste falhar, confirme rede, firewall, porta `8080`, IP do servidor e `API_KEY`.

## 5. Gerar o pacote novamente

No computador de desenvolvimento:

```powershell
.\scripts\build_admin_release.ps1
```

O pacote final fica em:

```text
dist\MerceariaAdmin
```
