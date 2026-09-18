# Consertos aplicados no OpenWA

O OpenWA fica em `C:\Users\Eudson\OpenWA` e **não** faz parte deste
repositório. Os arquivos `.patch` desta pasta são correções feitas lá dentro.

## Por que isto existe

Uma atualização do OpenWA sobrescreve esses arquivos e **o conserto some sem
avisar**. No caso da reação, a falha não aparece em log nenhum: a API continua
respondendo `success`, o robô continua dizendo que marcou, e só o cliente
percebe — semanas depois — que ninguém confirmou o recebimento.

Depois de atualizar o OpenWA, reaplique:

```
cd C:\Users\Eudson\OpenWA
git apply "C:\Finart\AUTOMAÇAO WPP\patches-openwa\<arquivo>.patch"
```

Se o `git apply` recusar, o código mudou de lugar: abra o patch, ele é curto e
explica o que precisa valer.

---

## reacao-1a1-participant-vazio.patch

**Versão do OpenWA em que foi feito:** `e661c8d1` (09/09/2026)
**Data:** 18/09/2026
**Arquivo:** `src/engine/adapters/baileys-messaging.ts`

### O sintoma

Reação (o ✅ de "arquivo recebido") aparecia em **grupo** e nunca em **conversa
individual**. Voprix, Prime e o número pessoal do Pedro: nenhum marcava.

Nada acusava o problema:

- a API respondia `{"success": true}`;
- o log do OpenWA não registrava erro (e o do baileys vinha `silent` de fábrica);
- no protocolo, a reação saía para os **mesmos aparelhos** e pela mesma rota que
  um texto que era entregue normalmente.

### A causa

A chave da mensagem é guardada no banco em JSON e volta com
`participant: ""` em toda conversa individual. O protobuf grava um campo sempre
que a propriedade **existe** (`WAProto/index.js`, `MessageKey.encode`):

```js
if (m.participant != null && Object.hasOwnProperty.call(m, "participant"))
    w.uint32(34).string(m.participant);
```

Então `participant: ""` não equivale a ausente: vai no pacote como um
participante explicitamente vazio — que é o formato de chave de **grupo**
colado numa mensagem de conversa individual. Em grupo o campo vem preenchido de
verdade, e por isso só lá funcionava.

### O conserto

`wireKey()` recorta a chave para os quatro campos que `proto.MessageKey`
realmente tem (`remoteJid`, `fromMe`, `id`, `participant`) e **só inclui o
participant quando ele tem valor**. De quebra, deixa de fora três campos que o
proto nem define e que estavam sendo enviados junto: `remoteJidAlt`,
`participantAlt` e `addressingMode`.

### Como conferir que ainda funciona

Não dá para conferir por API: com o motor baileys, ler reações devolve
`501 getMessageReactions`. **A conferência é olhar o WhatsApp.** Mande um
arquivo de um número qualquer para a Finart e veja se o ✅ aparece na conversa
individual — se aparecer em grupo mas não em conversa individual, o patch caiu.
