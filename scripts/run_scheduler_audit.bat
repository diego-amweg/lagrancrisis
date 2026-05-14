@echo off
REM Wrapper for Task Scheduler: one-off post-close scheduler audit
cd /d C:\Users\Diego\lagrancrisis
set PYTHONIOENCODING=utf-8
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\scripts\scheduler_postclose_audit.py