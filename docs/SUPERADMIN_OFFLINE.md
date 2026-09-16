# Superadmin local e licenças por e-mail

Este modo não usa servidor, site, API nem ligação permanente à Internet. O
superadmin trabalha apenas no computador do proprietário, pelo terminal. A
Internet é necessária somente para os e-mails. O emissor automático roda no
computador do proprietário e não abre nenhuma porta de rede.

Cada licença é assinada, ligada ao computador que a pediu e validada
localmente pelo programa. Assim, uma licença copiada para outro computador não
ativa a instalação nova.

## Guardar com segurança

- Use sempre o mesmo utilizador Windows e o mesmo computador para operar o
  superadmin.
- Não apague nem formate esse computador sem preparar uma cópia de segurança
  adequada. A chave privada de assinatura fica protegida pelo Windows (DPAPI)
  e é necessária para emitir renovações compatíveis.
- A palavra-passe do superadmin é pedida apenas no terminal; nunca a envie por
  e-mail, mensagem ou chat.
- Proteja o e-mail que recebe as licenças com palavra-passe forte e MFA.

## Primeira configuração

Abra o PowerShell na pasta do projeto e execute:

```powershell
python .\scripts\superadmin_terminal.py
```

Tambem pode dar duplo clique em `scripts\\abrir_superadmin_local.cmd` para
abrir o mesmo terminal.

Na primeira abertura, o programa reaproveita de forma segura a credencial
local existente, quando houver. Caso contrário, pede a criação da palavra-passe
do superadmin no próprio terminal. O utilizador do superadmin é fixo como
`mirson`.

Depois de entrar, escolha a opção **1** e informe o único e-mail Gmail privado
que deve receber as licenças. Esse e-mail é do proprietário do sistema, não do
cliente.

Em seguida escolha a opção **5** uma única vez. Informe a palavra-passe de
aplicação Gmail, o plano padrão e o prazo que o superadmin decidiu usar. O
prazo é livre: por exemplo, `30s`, `1min`, `1 hora`, `7 dias`, `15 dias`,
`1 mês`, `2 meses` ou `1 ano`. A palavra-passe fica cifrada pelo Windows
(DPAPI) no computador do proprietário; ela não vai para o programa instalado
pelo cliente.

Na mesma opção, deixe **renovações automáticas** em **não** (recomendado) para
o aluguer normal. Assim, a primeira ativação pode ser automática, mas um
cliente expirado só recebe a renovação depois de o proprietário decidir o
prazo e usar a opção **2**. Ative essa opção apenas se quiser conceder o prazo
padrão automaticamente também em todas as renovações.

Ao terminar a opção **5**, confirme o início do emissor automático. A opção
**6** também pode iniciá-lo mais tarde, assim como
`scripts\\iniciar_emissor_automatico.cmd`. Deixe essa pequena janela aberta no
computador do proprietário: ela verifica o Gmail no intervalo configurado e
não exige que o terminal seja usado para cada cliente.

O terminal gera uma chave pública para o aplicativo desktop em
`licensing/offline_issuer_key.py`. Depois da configuração inicial, feche e
abra novamente o aplicativo desktop. Antes de distribuir uma nova versão do
instalador, gere-o novamente para incluir essa chave pública.

## Emitir ou renovar uma licença

1. No computador do cliente, abra a tela de login e clique em **PEDIR
   LICENÇA**. Se o SMTP dessa instalação estiver configurado, o pedido sai
   automaticamente pelo mesmo mecanismo usado para recuperação de senha. O
   cliente pode usar **COPIAR PEDIDO** se o envio por e-mail falhar.
2. O emissor local do proprietário lê esse pedido no Gmail, cria ou renova a
   licença assinada e envia o código apenas ao e-mail privado definido na
   opção 1. O terminal não precisa ser aberto para emitir cada licença.
3. O proprietário encaminha o código ao cliente pelo canal que decidir. O
   cliente cola o código no campo de licença da tela de login para concluir a
   ativação.

Se a instalação do cliente ainda não tiver SMTP configurado, o programa abre a
mensagem já preenchida no aplicativo de e-mail local para o cliente só clicar
em enviar. Esta é a alternativa segura: nunca distribua o Gmail nem a palavra-
passe de aplicação do proprietário dentro do instalador do cliente.

O emissor guarda a identidade do computador e da licença. Se o Gmail falhar
depois de criar a licença, a próxima tentativa reenvia exatamente o mesmo
código; nunca cria uma segunda licença para o mesmo pedido. Quando o mesmo
computador gerar um novo pedido para renovação, o emissor atualiza o prazo e
emite um novo código assinado, mas preserva o mesmo identificador de licença e
o mesmo vínculo da conta admin. Assim, há uma única licença lógica por
computador/cliente, mesmo depois de muitas renovações. A opção **4** continua
disponível para reenvio manual, se necessário.

No terminal, cada licença recebe também uma referência curta e fixa, como
`MIRSON-0001`. Use essa referência (ou apenas `1`) nas opções do CMD. O UUID
técnico continua protegido dentro dos códigos assinados e não precisa ser
copiado. A referência nunca deve ser uma palavra-passe ou outro segredo.

Para definir um prazo específico só para um cliente, use a opção **2** do
terminal e escreva o prazo no formato livre indicado pelo próprio menu. A
opção **5** define o prazo padrão usado pelo emissor automático em pedidos que
ele processar depois disso.

Quando as renovações automáticas estão desativadas, o emissor mantém o pedido
de renovação pendente e informa isso na janela dele. Copie o pedido do Gmail,
abra a opção **2**, escolha o novo prazo e envie a mesma licença renovada. O
identificador da licença continua igual; apenas o código assinado e a validade
mudam.

O botão **PEDIR LICENÇA** usa primeiro a configuração SMTP da própria
instalação, exatamente como a recuperação de senha. Não são guardadas
credenciais Gmail/SMTP do proprietário na instalação do cliente. Sem SMTP, o
botão usa o aplicativo de e-mail local como alternativa.

## O que é verificado no computador do cliente

Antes de liberar o login, o aplicativo verifica localmente a assinatura da
licença, o computador para o qual ela foi emitida, a data de início, a
expiração e o maior horário já observado no cofre local. Isso impede que uma
licença já vista como expirada volte a funcionar simplesmente atrasando o
relógio. Não são enviados dados da loja, vendas, stock, caixa ou contas a um
serviço externo.

Se o sistema for instalado noutro computador, será necessário gerar um novo
pedido e emitir uma nova licença. A transferência não mantém a ativação do
computador antigo.

## Suspender, reativar ou cancelar uma licença

Use **suspensão** quando o bloqueio puder ser revertido, por exemplo enquanto
aguarda pagamento ou confirma uma situação do cliente. No painel CMD, escolha
**11 — Suspender uma licença**. O terminal pede o identificador duas vezes,
emite um único código assinado `SIGE-SUS1` e envia-o ao e-mail privado. A
opção **12** reenvia exatamente o mesmo código.

No computador do cliente, com a licença ainda ativa, escolha **APLICAR CÓDIGO
DE SUSPENSÃO** e cole o `SIGE-SUS1`. O acesso fica bloqueado, mas os dados da
loja e a licença permanecem intactos. Para voltar a permitir o uso, no painel
CMD escolha **13 — Reativar uma licença suspensa**. O código `SIGE-RES1` é
enviado ao e-mail privado; o cliente importa-o em **APLICAR CÓDIGO DE
REATIVAÇÃO**. A opção **14** apenas reenvia esse mesmo código de reativação.

Use **15 — Cancelar uma licença definitivamente** somente quando não desejar
mais permitir aquele computador, por exemplo em caso de fraude ou encerramento
do contrato. Ele cria o código `SIGE-REV1`; a opção **16** reenvia o mesmo
código. No cliente, use **APLICAR CÓDIGO DE CANCELAMENTO**.

Se o superadmin cancelar por engano, existe uma recuperação de emergência:
**17 — Recuperar um cancelamento definitivo**. Ela pede o identificador duas
vezes, preserva o histórico do cancelamento e cria um `SIGE-RST1` ligado
somente àquele cancelamento. A opção **18** reenvia o mesmo código. No cliente,
use **APLICAR CÓDIGO DE RECUPERAÇÃO**. O `SIGE-RST1` não reativa outras
licenças, não remove uma suspensão e não impede o superadmin de emitir um novo
cancelamento posteriormente. Importe-o mesmo se o cliente ainda não tiver
importado o antigo `SIGE-REV1`: isso guarda a correção localmente e impede que
aquele e-mail de cancelamento antigo bloqueie a licença depois.

Em qualquer destes três casos, o estado no terminal é **emitida** ou
**enviada; aguarda importação**. Sem servidor, o computador do proprietário
não consegue saber automaticamente se o cliente já importou o código. O
código bloqueia ou reativa somente depois de ser importado no computador a que
ele pertence.

## Criar a única conta admin do comprador

Depois de a licença estar ativa no computador do comprador, abra o terminal
do superadmin no computador do proprietário e use a opção **7 — Criar conta
admin do comprador**.

1. Escolha a licença emitida para aquele cliente.
2. Informe o utilizador admin, e-mail de recuperação (se houver) e uma
   palavra-passe temporária forte.
3. O terminal envia para o e-mail privado do proprietário um código
   `SIGE-ADM1`. A palavra-passe temporária **não** vai no e-mail e não é
   guardada em texto; entregue-a ao comprador por outro canal seguro.
4. No computador já licenciado, o comprador cola esse código na tela de
   configuração administrativa e entra com a palavra-passe temporária.
5. No primeiro acesso, a troca da palavra-passe é obrigatória.

O código é assinado, tem validade entre 1 e 30 dias, pertence apenas àquela
licença e àquele computador e deixa um recibo de uso local. A instalação não
cria um admin sem ele, e o painel normal só permite criar contas de gerente.

Use a opção **8** para ver a tabela de contas admin emitidas e a opção **9**
para reenviar o mesmo código ainda válido. Caso ele expire antes da importação,
a opção **10** emite outro código temporário e marca o anterior como
substituído. A tabela mostra a validade do código, não finge saber se o
comprador já o importou — isso exigiria um servidor.

A opção **8** também mostra os dados que o superadmin conhece de cada admin
emitido: cliente, utilizador, e-mail, licença associada, situação do
cancelamento e validade do código. Senhas e hashes nunca são exibidos. Contas
de gerente criadas depois dentro do computador do comprador não aparecem
automaticamente nesse painel offline; para isso seria necessário um relatório
enviado pelo cliente ou uma sincronização/servidor.

A opção **7** cria a conta admin inicial de cada comprador. Existe apenas um
admin por instalação; portanto, criar um segundo admin ao mesmo tempo não é
permitido. Para trocar a pessoa responsável, a conta existente deve ser
substituída de modo controlado, sem revelar a senha anterior.

## Organização do painel CMD

Depois de cada ação, o terminal mostra o resultado e pede Enter para voltar ao
painel. Ao voltar, a tela é limpa para não acumular mensagens. A opção **V**
também limpa e redesenha o menu sem executar nenhuma operação.

## Senhas, auditoria e avisos

Nenhuma senha existente pode ser vista, recuperada ou enviada pelo terminal:
o sistema guarda apenas hashes bcrypt, que não são reversíveis. Quando alguém
esquecer a senha, use recuperação ou uma nova senha temporária, nunca a
tentativa de revelar a senha anterior.

As contas têm data de criação, último acesso, contador de falhas, bloqueio
temporário após cinco tentativas incorretas e marcação de troca obrigatória.
Ao criar ou alterar uma senha, a instalação tenta enviar um alerta ao e-mail
do proprietário com utilizador, computador e data — nunca com a senha, hash
ou código. Esse aviso usa o SMTP da própria instalação, tal como a recuperação
de senha; se o comprador não tiver SMTP configurado, o evento continua no
registo local, mas o e-mail não pode ser garantido sem um servidor.

## Limitação importante do modo offline

Sem servidor, não é possível cancelar instantaneamente uma licença já entregue
enquanto o cliente estiver sem atualizar o programa, nem provar de forma
absoluta a hora se alguém restaurar deliberadamente uma cópia antiga do disco.
Para manter o controlo, emita períodos compatíveis com o contrato (por
exemplo, mensal ou trimestral) e renove apenas clientes em dia. Os prazos de
segundos e minutos servem bem para demonstração e testes; para aluguer real,
períodos de dias ou meses são mais resistentes e práticos. Uma licença
expirada deixa de permitir o uso mesmo sem Internet.


### Licenca vitalicia

No prazo da emissao manual ou automatica, escreva `vitalicia`. O cliente tambem pode solicitar esse prazo. A licenca permanece vinculada ao computador e continua sujeita aos controlos de assinatura, suspensao e cancelamento.

Para compatibilidade com o formato assinado existente, a validade vitalicia usa o valor reservado `9999-12-31T23:59:59+00:00`; o cliente reconhece esse valor como sem expiracao e apresenta "Licenca vitalicia ativa".


### Pedido simplificado

Clique em **PEDIR RENOVACAO** para manter o plano atual. Os dados da licenca sao preenchidos automaticamente, sem formulario ou confirmacao adicional. Para a primeira ativacao, use **PEDIR LICENCA**; o responsavel define o plano ao emitir.

Se o envio direto falhar, abre-se uma mensagem pronta no aplicativo de e-mail. Se isso nao estiver disponivel, **COPIAR PEDIDO** permite encaminha-la por mensagem. Abrir ou copiar o pedido nao o marca como enviado. Depois de receber a licenca, cole o codigo e clique em **APLICAR CODIGO**.

O seletor de plano oferece Mensal, Trimestral, Semestral, Anual e Vitalicia. Na renovacao, a opcao inicial e **Manter plano atual**. O prazo e preenchido pela selecao. Pedidos ja preparados mantem a escolha original nos reenvios.
