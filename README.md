# AUTOMACAO-WPP

Automação interna de uma gráfica: recebe os arquivos que os clientes mandam por
WhatsApp, Teams e e-mail, salva cada um na pasta do dia do cliente e devolve os
arquivos de saída do CTP pelo mesmo canal por onde o pedido chegou.

São robôs pequenos, um por canal, rodando no PC da produção:

| Robô | O que faz |
|---|---|
| `vigia_whatsapp.py` | Baixa os documentos que os clientes mandam no WhatsApp (via OpenWA). |
| `teams_web.py` | Baixa o que o cliente manda no Teams, marca a mensagem e envia arquivos de volta. Usa um navegador, não a API. |
| `vigia_cip.py` | Vigia as pastas do CTP e devolve os arquivos prontos ao cliente. |
| `vigia_email.py` | Baixa os anexos do e-mail. |
| `marcar_no_grupo.py` | Marca no grupo do WhatsApp a OS cujo arquivo já entrou em produção. |

O Teams usa navegador e não API porque o cliente manda de uma conta pessoal, e
o anexo fica no OneDrive de consumidor: o token corporativo leva 401 no download
direto e 403 pelo Graph. É fronteira entre as duas nuvens, e nenhuma permissão
resolve — um navegador logado baixa normalmente.

**A documentação de verdade está no [LEIA-ME.md](LEIA-ME.md)**, em português e
escrita para quem opera, não para quem programa. Lá estão as armadilhas que
custaram caro — em especial a lição que se repetiu três vezes: **confirmar que
um comando foi dado não é o mesmo que confirmar que ele teve efeito.**

As configurações não são versionadas: nomeiam clientes, pastas e grupos. Os
moldes estão nos arquivos `*.EXEMPLO.json`.
