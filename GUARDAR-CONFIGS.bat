@echo off
chcp 65001 >nul
title GUARDAR CONFIGS
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Copia os configs para \\servidor\Finart\CONFIGS GUARDADOS.
rem Eles nao vao para o GitHub (repositorio publico, e eles trazem telefone de
rem cliente e a senha de app do Gmail), entao esta e a unica copia fora deste PC.
python guardar_configs.py %*
