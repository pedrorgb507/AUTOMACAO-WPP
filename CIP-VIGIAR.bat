@echo off
chcp 65001 >nul
title CIP-VIGIAR
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python vigia_cip.py --vigiar
pause
