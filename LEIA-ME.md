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

Os dois terminais (OpenWA e Vigia) abrem lado a lado no painel de baixo. Enquanto estiverem rodando, a automação funciona.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `config.json` | **Lista de clientes** e opções. Editar aqui no VS Code. Não precisa reiniciar: é relido a cada checagem. |
| `vigia_whatsapp.py` | O programa que baixa os arquivos. |
| `vigia.log` | Histórico: o que foi salvo e os erros. |
| `ja_baixados.json` | Controle interno do que já foi baixado (não editar). |
| `AUTOMACAO-WPP.code-workspace` | Abre o projeto no VS Code com as tarefas. **Sempre abra por ele** (ou pelo `ABRIR NO VS CODE.bat`). |
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
