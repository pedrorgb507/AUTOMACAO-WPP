# AUTOMAÇAO WPP

Baixa os documentos que os clientes mandam no WhatsApp e salva na pasta do dia de cada cliente:
`\\servidor\TRABALHO\<CLIENTE>\<MÊS>\<dia>`

Funciona em cima do **OpenWA** (instalado em `C:\Users\Eudson\OpenWA`), que conecta o WhatsApp no PC.

## Como usar no VS Code

| O que | Como |
|---|---|
| Ligar tudo (OpenWA + Vigia) | **Ctrl+Shift+B** |
| Outras tarefas (testar, abrir painel) | **Ctrl+Shift+P** → `Tasks: Run Task` |
| Parar | Clique na lixeira do terminal da tarefa, ou **Ctrl+C** nele |

O Ctrl+Shift+B abre um terminal para cada robô, lado a lado no painel de baixo:
OpenWA, Vigia WhatsApp, **Vigia Sólida (Teams + CIP)** e Vigia Email. Enquanto
estiverem rodando, a automação funciona.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `config.json` | **Lista de clientes** e opções. Editar aqui no VS Code. Não precisa reiniciar: é relido a cada checagem. |
| `vigia_whatsapp.py` | O programa que baixa os arquivos. |
| `vigia.log` | Histórico: o que foi salvo e os erros. |
| `ja_baixados.json` | Controle interno do que já foi baixado (não editar). |
| `AUTOMACAO-WPP.code-workspace` | Abre o projeto no VS Code com as tarefas. **Sempre abra por ele.** |
| `iniciar-openwa.bat` | Liga o OpenWA. Clique duplo também funciona (abre janelas separadas). |
| `VIGIAR.bat` / `TESTAR.bat` | Versões de clique duplo do vigia. |

## Adicionar cliente

No `config.json`, dentro de `"clientes"`, uma linha por número (vírgula entre as linhas):

```json
"clientes": [
  { "pasta": "Emporio Print Arte", "whatsapp": "62 9307-9801" },
  { "pasta": "Nome da Pasta do Cliente", "whatsapp": "62 99999-9999" }
]
```

- `pasta` = nome da pasta do cliente em `\\servidor\TRABALHO` (maiúscula e acento não importam).
- Vários números podem apontar para a mesma pasta.

## O que é baixado

- Só arquivos enviados como **Documento** (📎 → Documento). Fotos da galeria, áudios e figurinhas são ignorados (dá para mudar em `"tipos"`).
- Até 200 MB por arquivo. Maior que isso o log avisa e o arquivo tem que ser baixado pelo celular.
- Nome repetido na mesma pasta vira `_2`, `_3`.

---

# VIGIA TEAMS WEB

Robô de navegador para o Teams de conta **pessoal** (FINART CTP,
`registro_fotolito@hotmail.com`). Baixa o que a Sólida manda, salva na pasta do
dia e marca a mensagem com o ✅.

## Por que existe

A Sólida manda pelo chat da conta pessoal dela, e o anexo mora no OneDrive de
consumidor (`my.microsoftpersonalcontent.com`). Com o token corporativo
`arte@finartdigital` dá **401** no download direto e **403 accessDenied** pelo
Graph. Não é falta de permissão: é fronteira entre a nuvem corporativa e a de
consumidor. Um navegador logado baixa normalmente, que é o que este robô faz.

A sessão fica em `perfil_teams_web/`, separada do Chrome do dia a dia. **Essa
pasta vale como senha** — está no `.gitignore`.

## Como usar

| O que | Como |
|---|---|
| Entrar na conta (uma vez) | `TEAMS-WEB-LOGIN.bat` |
| Ver o que ele baixaria | `TEAMS-WEB-TESTAR.bat` |
| Marcar o que já está tratado | `TEAMS-WEB-CORTE.bat` |
| Rodar continuamente | `TEAMS-WEB-VIGIAR.bat` |

O `--vigiar` mantém o navegador aberto entre as checagens e recarrega só a
página. Uma passada com download leva uns 30 segundos.

## A reação ✅ — o que é verdade

**Ela funciona.** Uma investigação anterior concluiu que não, mas o erro estava
na *conferência*, não no clique: o robô marcava certo e se declarava errado.

Como se enxerga que a reação existe, de verdade:

- O Teams desenha uma pílula de resumo (`fui-ChatMessage__reactions` →
  `diverse-reaction-pill-button`) que **só existe quando há reação**.
- O emoji se reconhece pelo `itemid` da imagem dentro da pílula
  (`2705_whiteheavycheckmark`), que **não muda com o idioma**.
- O `aria-pressed` da pílula separa o que é nosso do que é do cliente: o ➕ que
  a Sólida põe nas nossas mensagens vem como `false`.

O fluxo combinado com a Sólida: **o ➕ é o cliente que põe; o ✅ somos nós, em
todo arquivo que baixarmos.**

### Cuidado: o botão é liga/desliga

Clicar numa mensagem **já marcada REMOVE** o visto. Por isso `reagir()` confere
antes de clicar, e `tem_visto()` devolve `None` (e não `False`) quando não
consegue ver a mensagem — "não sei" virar "não tem" faria o robô desmarcar.

### Medições que dão FALSO POSITIVO (não use)

1. Procurar o emoji como texto — os botões são rotulados em português.
2. `innerText.includes('marca de seleção')` — vem da barra de hover.
3. `elemento.screenshot()` do `[data-mid]` — o recorte corta a faixa da reação.
4. **Acreditar que o clique deu certo** — foi esse o erro que custou mais tempo.

## Seletores confirmados

| O quê | Seletor |
|---|---|
| Lista de conversas | `[role="treeitem"]` |
| Mensagens | `[data-tid="chat-pane-message"]`, id em `data-mid` |
| Anexo | `[data-tid^="file-chiclet-"]` (o tid traz o nome) |
| Autor | `[data-tid="message-author-name"]` |
| Visto na barra de hover | `[data-tid="message-actions-2705_whiteheavycheckmark"]` |
| Abrir o painel de emojis | `[data-tid="add-reaction-picker-entry-point-button"]` |
| Emoji dentro do painel | `[data-tid="emoticon-button-<itemid>"]` |
| Baixar, na aba do OneDrive | `[aria-label^="Baixar esse arquivo"]` |

**Não abra o painel para pôr o visto.** O ✅ fica na barra de hover; o painel
aberto passa por cima dela e engole o clique. Pior: o painel nem tem o `2705` —
ele oferece o `2714_heavycheckmark`, que é outro emoji.

**Baixar tem dois passos:** clicar no anexo não baixa, abre uma aba no
`onedrive.live.com`; o botão de baixar está lá.

## Armadilhas da lista de mensagens

- **A conversa pode abrir na errada.** O Teams reabre na última conversa usada, e
  esperar um tempo fixo depois do clique não garante a troca. `abrir_conversa()`
  confere quem assina as mensagens e **se recusa** a trabalhar se não for o
  cliente. Já aconteceu de reagir na conversa de outro contato sem isso.
- **A conversa pode abrir semanas atrás.** A lista é virtualizada: só existe no
  DOM o que está perto da tela. Sem rolar até o fim, o robô lê uma janela velha,
  não acha nada e não reclama. `ir_para_o_fim()` rola com a roda do mouse —
  **não clique na última mensagem para rolar**, porque se ela for um anexo o
  clique abre o arquivo.
- **`dias_para_tras`** (no config) ignora mensagem mais velha que isso. É a rede
  de segurança para o caso de a rolagem falhar: sem ela, uma janela antiga faria
  o robô baixar arquivo velho para a pasta de hoje.

## Enviar os .ppf (vigia_cip.py)

O `vigia_cip.py` manda os `.ppf` por aqui, não mais pelo Graph. Some o upload
para o OneDrive, a liberação de leitura para o cliente e o `token_cip.bin`.

No `config_cip.json`, a entrada com `"destino": "teams"` usa **`conversa`** — o
nome da conversa como aparece no Teams — no lugar de `chat_id`.

**Enviar tem a mesma armadilha da reação:** ver o anexo subir na caixa não prova
que a mensagem saiu. Dois `.ppf` já foram dados como enviados, arquivados em
ENVIADOS, e não chegaram ao cliente. Por isso `enviar_arquivo()` só confirma
depois que a mensagem aparece na conversa **com id do servidor** e **continua lá
sete segundos depois** — o Teams desenha a mensagem antes de aceitá-la, e ela
some se o envio falhar.

Se um envio falhar no meio, o anexo fica pendurado na caixa e iria junto do
próximo; por isso a caixa é limpa antes de anexar.

## Aviso no grupo do WhatsApp

Depois de baixar e marcar, o robô procura no grupo a mensagem em que a Sólida
anunciou aquela OS (`49941 - FPF Tech - pasta`) e põe ✅ nela, para o pessoal
ver de relance o que entrou em produção. É o `marcar_no_grupo.py`.

O anúncio às vezes chega **depois** do arquivo. Por isso o arquivo nunca
espera: é baixado na hora e a OS fica pendente em `pendencias_os.json`,
tentada de novo a cada passada. Passado o prazo do config, vira aviso no log.

Depende do **OpenWA estar rodando**. Sem ele o robô não para: registra o aviso
no log e a OS continua na fila.

## Um navegador para os dois robôs

O perfil do Chrome (`perfil_teams_web/`) aceita **um dono só**. Se o vigia que
baixa e o que manda os `.ppf` abrirem cada um o seu, o segundo não sobe. Por
isso os dois rodam no mesmo processo — `vigiar_teams_e_cip.py` — e pedem a
janela à mesma `SessaoNavegador`.

Consequência prática: **se o robô for morto sem fechar direito, o Chrome dele
continua rodando e tranca o perfil.** O próximo start falha até você fechar
essas janelas (ou encerrar `chrome.exe` no Gerenciador de Tarefas). O erro diz
isso quando acontece.

## Falta fazer

Nada pendente da lista antiga. O Teams corporativo foi removido: `vigia_teams.py`,
`config_teams.json`, `token_teams.bin`, `graph_anexo.py` e `reenviar_aviso.py`
saíram, junto dos `.bat` deles. Estão no git (commit `3bede1b`) e há cópia dos
não versionados em `copias-de-seguranca/`.
