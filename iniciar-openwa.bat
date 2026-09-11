@echo off
setlocal EnableExtensions EnableDelayedExpansion
title OpenWA
rem Pasta desta automacao (AUTOMACAO WPP) - calculada sozinha, sem digitar o caminho
set "AQUI=%~dp0"
rem O OpenWA em si fica instalado em C:\Users\Eudson\OpenWA
set "DEST=%USERPROFILE%\OpenWA"
set "MODO=%~1"
if /i "%MODO%"=="chave" goto :chave

echo ============================================
echo   OpenWA - instalacao / inicializacao
echo   Pasta: %DEST%
echo ============================================
echo.

rem --- 1. Git ---
where git >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Git nao encontrado. Instalando...
  where scoop >nul 2>nul && (call scoop install git) || (winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements)
  where git >nul 2>nul || (echo [ERRO] Instale o Git ^(git-scm.com^), feche e rode de novo. & pause & exit /b 1)
)

rem --- 2. Node 22.13+ ---
set "NV=0"
for /f "tokens=1 delims=." %%v in ('node -v 2^>nul') do set "NV=%%v"
set "NV=%NV:v=%"
if %NV% LSS 22 (
  echo [AVISO] Node 22+ nao encontrado ^(atual: %NV%^). Instalando Node LTS...
  where winget >nul 2>nul && (winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements) || (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "scoop config last_update ([DateTime]::Now.ToString('o'))" >nul 2>nul
    call scoop install nodejs-lts
  )
  if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%ProgramFiles%\nodejs;%PATH%"
  set "NV=0"
  for /f "tokens=1 delims=." %%v in ('node -v 2^>nul') do set "NV=%%v"
  set "NV=!NV:v=!"
  if !NV! LSS 22 (echo [ERRO] Node instalado, mas esta janela nao enxerga ainda. Feche e rode o arquivo de novo. & pause & exit /b 1)
)
echo [ok] git e node:
git --version
node -v

rem 'patch' do Git ajuda nos ajustes do whatsapp-web.js durante o npm ci
if exist "%ProgramFiles%\Git\usr\bin\patch.exe" set "PATH=%PATH%;%ProgramFiles%\Git\usr\bin"
if exist "%USERPROFILE%\scoop\apps\git\current\usr\bin\patch.exe" set "PATH=%PATH%;%USERPROFILE%\scoop\apps\git\current\usr\bin"

rem --- 3. Clonar (fora do OneDrive) ---
if not exist "%DEST%\package.json" (
  echo.
  echo [..] Clonando repositorio...
  git clone https://github.com/rmyndharis/OpenWA.git "%DEST%" || (echo [ERRO] Falha no git clone. & pause & exit /b 1)
)
cd /d "%DEST%"

rem --- 4. Dependencias (so ate dar certo uma vez) ---
rem  better-sqlite3 ja vem com o binario pronto pro Windows, mas o "node-gyp rebuild"
rem  automatico do npm exige Visual Studio. Por isso instalamos sem scripts e rodamos
rem  depois so os scripts necessarios.
if not exist "%DEST%\node_modules\.openwa-ok" (
  echo.
  echo [..] Instalando dependencias ^(npm ci^) - demora alguns minutos...
  call npm ci --ignore-scripts || (echo [ERRO] npm ci falhou. Tire print desta tela e mande pro Claude. & pause & exit /b 1)
  echo [..] Baixando o Chrome do puppeteer...
  call npm rebuild puppeteer || (echo [ERRO] Falha ao baixar o Chrome do puppeteer. & pause & exit /b 1)
  echo [..] Instalando o dashboard e aplicando ajustes do OpenWA...
  call node scripts\postinstall.js || (echo [ERRO] postinstall falhou. Tire print e mande pro Claude. & pause & exit /b 1)
  node -e "require('better-sqlite3')(':memory:').close(); console.log('[ok] better-sqlite3 funcionando')" || (echo [ERRO] better-sqlite3 nao carregou. & pause & exit /b 1)
  echo ok> "%DEST%\node_modules\.openwa-ok"
)

rem --- 5. API Key ---
if /i "%MODO%"=="vscode" (
  if exist "%DEST%\data\.api-key" (echo. & echo API Key do painel: & type "%DEST%\data\.api-key" & echo.)
) else (
  rem clique duplo: janela auxiliar mostra a chave e abre o painel
  start "OpenWA - chave" cmd /c ""%~f0" chave"
)

rem --- 6. Subir API + Dashboard ---
echo.
echo [..] Iniciando OpenWA. Deixe esta janela aberta ^(Ctrl+C para parar^).
echo      Dashboard: http://localhost:2886
echo      API:       http://localhost:2785/api
echo      Swagger:   http://localhost:2785/api/docs
echo.
rem Religa sozinha a sessao do WhatsApp que ja estava conectada
set "AUTO_START_SESSIONS=true"
rem Aceita arquivos de ate 200 MB vindos do WhatsApp (padrao era 50 MB)
set "MEDIA_DOWNLOAD_MAX_BYTES=209715200"
set "MEDIA_DOWNLOAD_TIMEOUT_MS=300000"
rem Clique duplo: liga o VIGIA WHATSAPP numa janela separada.
rem No VS Code o vigia roda como outra tarefa, no proprio terminal do VS Code.
if /i not "%MODO%"=="vscode" start "VIGIA WHATSAPP" /min "%AQUI%VIGIAR.bat"
call npm run dev
if /i not "%MODO%"=="vscode" pause
exit /b 0

:chave
cd /d "%DEST%"
echo Aguardando o OpenWA subir...
for /l %%i in (1,1,150) do if not exist "data\.api-key" timeout /t 2 >nul
echo.
echo ===== SUA API KEY (cole no login do dashboard) =====
type "data\.api-key"
echo.
echo ====================================================
timeout /t 10 >nul
start "" http://localhost:2886
echo.
pause
exit /b 0
