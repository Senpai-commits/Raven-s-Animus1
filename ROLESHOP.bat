@echo off
title RoleShop Bot
color 0D

cls
echo ============================================
echo           ROLESHOP BOT - STARTING
echo ============================================
echo.

cd /d "C:\Users\maxic\OneDrive\Bureau\Discord Dev\roleshop"
echo [%time%] Working directory: %CD%
echo [%time%] Installing dependencies...
pip install -r requirements.txt -q
echo [%time%] Bot is running...
echo Press CTRL+C to stop.
echo.

python -u bot.py

echo.
echo ============================================
echo [%time%] Bot has stopped.
echo Close this window or double-click to restart.
echo ============================================
pause
