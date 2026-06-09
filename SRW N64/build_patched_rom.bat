@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set /p "ROM=Original normalized ROM path (.z64 recommended): "
set /p "CSV=Merged translation CSV path: "
set /p "FONT=Korean TTF path: "

python build_current_translation_rom.py "%ROM%" "%CSV%" "%FONT%" "games\Super Robot Taisen 64 (Japan) (patched).n64"
pause
