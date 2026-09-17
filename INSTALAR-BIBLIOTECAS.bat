@echo off
chcp 65001 >nul
title INSTALAR BIBLIOTECAS
echo Instalando as bibliotecas que os robos usam...
python -m pip install --user --upgrade requests playwright google-api-python-client google-auth-httplib2 google-auth-oauthlib
echo.
echo Instalando o navegador do Playwright (usado pelo robo do Teams)...
python -m playwright install chromium
echo.
echo Pronto.
pause
