@echo off
REM Wrapper for Task Scheduler: intraday accumulation
cd /d C:\Users\Diego\lagrancrisis
set PYTHONIOENCODING=utf-8
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\src\main.py --accumulate
