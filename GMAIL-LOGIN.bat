@echo off
chcp 65001 >nul
title GMAIL-LOGIN
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python drive_web.py --login
pause
