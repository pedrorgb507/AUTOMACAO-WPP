@echo off
chcp 65001 >nul
title TEAMS-WEB-VIGIAR
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python teams_web.py --vigiar
pause
