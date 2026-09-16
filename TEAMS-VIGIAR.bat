@echo off
chcp 65001 >nul
title TEAMS-VIGIAR
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python vigia_teams.py --vigiar
pause
