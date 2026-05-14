@echo off
REM Review batch script for Task Scheduler
REM Executes operational_review.py

cd /d C:\Users\Diego\lagrancrisis
set PYTHONIOENCODING=utf-8
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\scripts\wait_for_close_artifacts.py --repo-root C:\Users\Diego\lagrancrisis
if errorlevel 1 exit /b 1
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\scripts\operational_review.py
