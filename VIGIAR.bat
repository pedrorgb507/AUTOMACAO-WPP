@echo off
title VIGIA WHATSAPP
rem Fica rodando e baixa os documentos dos clientes. Feche a janela para parar.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem espera o OpenWA subir
timeout /t 30 >nul
python vigia_whatsapp.py --vigiar
pause
