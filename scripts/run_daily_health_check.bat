@echo off
REM Wrapper for Task Scheduler: daily health check
cd /d C:\Users\Diego\lagrancrisis
set PYTHONIOENCODING=utf-8
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\scripts\daily_health_check.py
