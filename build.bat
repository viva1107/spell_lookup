@echo off
chcp 65001 >nul
title Build NPCSpellLookup EXE
echo ============================================
echo  NPCSpellLookup - Windows EXE Builder
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH
    pause
    exit /b 1
)

echo [1/2] 安装依赖...
python -m pip install --upgrade pip
python -m pip install pyinstaller aiohttp requests
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络
    pause
    exit /b 1
)

echo.
echo [2/2] 打包 EXE...
pyinstaller --onefile --windowed --name NPCSpellLookup ^
    --hidden-import aiohttp --hidden-import multidict --hidden-import yarl ^
    spell_lookup_gui.py
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo  完成！EXE 位置： dist\NPCSpellLookup.exe
echo ============================================
explorer dist
pause
