@echo off
chcp 65001 >nul
title EMAIL-VIGIAR
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python vigia_email.py --vigiar
pause
