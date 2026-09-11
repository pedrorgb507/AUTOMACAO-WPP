@echo off
rem ============================================================
rem  Abre o VS Code no workspace da automacao.
rem  Ao abrir, o proprio VS Code sobe o OpenWA e o VIGIA nos
rem  terminais dele (tarefa "Iniciar tudo", runOn folderOpen).
rem  Chamado pela tarefa agendada "AUTOMACAO WPP - inicio".
rem ============================================================
cd /d "%~dp0"
set "CODE=%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"
if not exist "%CODE%" set "CODE=%ProgramFiles%\Microsoft VS Code\bin\code.cmd"
if not exist "%CODE%" (
  echo [ERRO] VS Code nao encontrado. Abra o workspace na mao.
  exit /b 1
)
call "%CODE%" "%~dp0AUTOMACAO-WPP.code-workspace"
