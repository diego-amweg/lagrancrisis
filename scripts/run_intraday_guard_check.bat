@echo off
REM Wrapper for Task Scheduler: hourly intraday guard check
cd /d C:\Users\Diego\lagrancrisis
set PYTHONIOENCODING=utf-8
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\scripts\intraday_guard_check.py
