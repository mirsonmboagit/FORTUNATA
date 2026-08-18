# SIGE MPE Manager Mobile

O Manager Mobile e um APK Android separado. Liga-se sempre a API SIGE MPE
central: nao leva SQLite, nao cria vendas offline e nao mistura dados do
telefone com os dados da loja.

## Funcionalidades incluídas

- Catálogo, carrinho e pagamento adaptados a telefone e tablet.
- Dinheiro, cartão, M-Pesa e E-MOLA em grelha responsiva (4 colunas em ecrãs
  largos, 2×2 em telefones).
- Caixa por terminal móvel, com identificador privado da app.
- Leitor de código USB/Bluetooth HID no campo de pesquisa.
- Venda de vários produtos gravada numa única transação atómica com um único
  `transaction_code`. Se a resposta da API se perder, repetir FINALIZAR
  confirma o mesmo código sem duplicar produtos ou stock.
- Histórico agrupado por venda, detalhe de produtos e estorno por item até
  10 minutos; a API volta a validar o prazo antes de aceitar o estorno.
- Configuração inicial dentro da app: URL HTTPS/HTTP da API + chave de API,
  testada antes de ser gravada no armazenamento privado Android.

## Limites deliberados desta versão

O leitor por câmara do executável Windows usa OpenCV/ZBar e não é compatível
com Android. Por isso esta versão não apresenta um botão de câmara que falhe:
suporta leitor HID/manual. O scanner por câmara deve ser acrescentado numa
próxima versão com CameraX/ML Kit e permissão `CAMERA`.

A impressão térmica Windows também não é empacotada. O recibo e o histórico
ficam disponíveis no servidor; uma integração Android Print/partilha pode ser
adicionada sem alterar as vendas.

## Compilar o APK

O Buildozer requer Linux. Neste computador ainda não existe uma distribuição
WSL/Linux, Android SDK nem JDK 17, portanto o APK não pode ser gerado localmente
até esse ambiente ser instalado.

Em Ubuntu/WSL2, a partir da raiz do projeto:

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
  build-essential libffi-dev libssl-dev autoconf libtool pkg-config zlib1g-dev
python3 -m venv .venv-mobile
source .venv-mobile/bin/activate
pip install --upgrade pip setuptools wheel
pip install buildozer cython==0.29.36
cp buildozer-manager-mobile.spec buildozer.spec
buildozer -v android debug
```

O APK de teste sai em `bin/`. Para distribuição, usar uma keystore mantida em
segredo e compilar `buildozer android release`; assinar todos os lançamentos
com a mesma keystore.

## Atualizações seguras

Android reconhece a atualização sem apagar a configuração da app quando se
mantêm: o mesmo `package.domain`/`package.name`, a mesma keystore e uma versão
superior no `buildozer-manager-mobile.spec`. Publique apenas APK/AAB assinado
num canal controlado (Google Play, MDM ou portal HTTPS da empresa). O Android
pedirá confirmação quando a instalação for fora da Play Store.

## Ligação à API

No telefone use o IP/DNS acessível da loja, por exemplo
`https://api.minhaloja.mz` ou `http://192.168.1.20:8080`. `127.0.0.1` aponta
para o próprio telefone e não para o computador da API. Em produção, use HTTPS
e uma chave de API distinta por instalação/equipa quando possível.
