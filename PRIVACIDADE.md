# Política de Privacidade — Automação Finart

**Última atualização: 17 de setembro de 2026**

Este documento descreve o que o aplicativo **Automação Finart** faz com os dados
a que tem acesso. Ele é curto porque o aplicativo faz pouca coisa.

## O que é este aplicativo

É uma automação interna de uma gráfica. Roda em um único computador, dentro da
empresa, operada apenas pelos funcionários dela. Não é um serviço, não tem site,
não tem cadastro e não é distribuído para outras pessoas.

A função dele é uma só: os clientes da gráfica mandam arquivos de impressão por
e-mail, e o programa salva esses arquivos na pasta do cliente no servidor da
empresa, para entrarem em produção.

## Quais dados são acessados

O aplicativo pede uma única permissão do Google:

| Permissão | Para quê |
|---|---|
| `drive.readonly` — ver e baixar arquivos do Google Drive | Baixar o arquivo que o cliente enviou |

Essa permissão é usada **somente** para baixar arquivos que chegam por link no
e-mail da empresa. Quando o arquivo passa do limite de anexo do Gmail, o e-mail
chega sem anexo e com um link do Google Drive no corpo — e é esse link que o
aplicativo segue.

A permissão é de **leitura apenas**. O aplicativo não cria, não altera, não move
e não apaga nada no Google Drive de ninguém.

Nenhuma outra permissão é pedida: não há acesso a contatos, agenda, fotos,
histórico, nem a arquivos do Drive que não tenham sido enviados por um cliente
em um e-mail para a empresa.

## O que é feito com os dados

O arquivo baixado é gravado em uma pasta do servidor de arquivos da própria
gráfica, organizado por cliente e por data. É o mesmo destino que teria se um
funcionário baixasse o arquivo à mão.

Os arquivos são de trabalho — artes e grades de impressão enviadas pelo próprio
cliente para serem produzidas — e ficam guardados enquanto forem necessários à
produção e ao histórico da empresa.

## Com quem os dados são compartilhados

**Com ninguém.** Os arquivos não são enviados a nenhum serviço externo, não são
publicados, não são usados para treinar nada e não são vendidos ou cedidos a
terceiros. Eles saem do Google Drive e vão direto para o servidor da empresa.

Não há analytics, rastreamento, telemetria ou qualquer envio de dados para fora
do computador onde o programa roda.

## Como o acesso é guardado

A autorização do Google fica em um arquivo (`token_drive.json`) no computador
onde o programa roda, e não sai de lá. Ele não é versionado nem enviado a lugar
nenhum.

## Como revogar o acesso

A qualquer momento, em <https://myaccount.google.com/permissions>, selecione
**Automação Finart** e clique em remover o acesso. O aplicativo para de baixar
arquivos imediatamente. Apagar o arquivo `token_drive.json` do computador tem o
mesmo efeito.

## Contato

Dúvidas sobre esta política ou sobre os dados: **finartdigitalgo@gmail.com**

## Código

O programa é aberto e pode ser lido por inteiro em
<https://github.com/pedrorgb507/AUTOMACAO-WPP>. A parte que fala com o Google
Drive está no arquivo `drive_api.py`.
