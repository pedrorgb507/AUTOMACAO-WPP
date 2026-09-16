@echo off
chcp 65001 >nul
cd /d "%~dp0"
python reenviar_aviso.py "49894 - FP - chapado fto3 irregular.pdf" "49897 - Nutro Core - envelope 24x34.pdf"
echo.
pause
