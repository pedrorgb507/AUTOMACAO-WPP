@echo off
chcp 65001 >nul
title INSTALAR BIBLIOTECAS
echo Instalando as bibliotecas que o VIGIA TEAMS usa (msal e requests)...
python -m pip install --user --upgrade msal requests
echo.
echo Pronto. Agora rode o TEAMS-LOGIN.bat.
pause
