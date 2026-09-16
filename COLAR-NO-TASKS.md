# Como ligar o VIGIA TEAMS junto com o resto

O Claude não tem permissão para gravar dentro da pasta `.vscode`, então esta parte
é você quem faz — leva 20 segundos, uma vez só.

1. No VS Code, abra `.vscode/tasks.json`.
2. Selecione tudo (Ctrl+A) e apague.
3. Abra o arquivo `tasks-NOVO.json` (está nesta pasta), selecione tudo e copie.
4. Volte no `tasks.json`, cole (Ctrl+V) e salve (Ctrl+S).
5. Feche e abra o workspace de novo, ou aperte Ctrl+Shift+B.

## O que muda

Passam a subir três terminais lado a lado, em vez de dois:

- **OpenWA** — o gateway do WhatsApp
- **Vigia WhatsApp** — baixa os documentos dos clientes do WhatsApp
- **Vigia Teams** — baixa o que a Sólida posta no canal e marca ✅

E ficam disponíveis, no Ctrl+Shift+P → `Tasks: Run Task`:

- WhatsApp: testar (sem salvar nada)
- Teams: testar (sem salvar nada)
- Teams: refazer login da Microsoft
- Abrir painel do OpenWA
