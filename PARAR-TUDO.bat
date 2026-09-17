@echo off
chcp 65001 >nul
title PARAR TUDO
cd /d "%~dp0"

echo ============================================
echo   PARANDO TODOS OS ROBOS
echo ============================================
echo.
echo Fechar o terminal nao mata o Python; matar o Python nao mata o Chrome do
echo robo, que fica segurando o perfil; e o OpenWA deixa processos do npm
echo presos na porta. Este arquivo encerra os tres casos e confere no fim.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0parar-tudo.ps1"

echo.
echo ============================================
echo   Para religar: abra o projeto no VS Code
echo   e tecle Ctrl+Shift+B
echo ============================================
echo.
pause
