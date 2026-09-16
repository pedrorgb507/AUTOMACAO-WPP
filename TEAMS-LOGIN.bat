@echo off
chcp 65001 >nul
title TEAMS-LOGIN
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python vigia_teams.py --login
pause
