@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist text.csv copy /y text.csv text.csv.bak > nul
python emuurom_tool.py extract
pause
