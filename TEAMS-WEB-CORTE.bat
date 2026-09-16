@echo off
chcp 65001 >nul
title TEAMS-WEB-CORTE
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python teams_web.py --corte
pause
