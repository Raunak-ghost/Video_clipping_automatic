@echo off
setlocal
cd /d "%~dp0"
if exist "D:\ComfyUI\venv\Scripts\python.exe" (
    "D:\ComfyUI\venv\Scripts\python.exe" gtracking_generate_baby_rhymes.py %*
) else (
    python gtracking_generate_baby_rhymes.py %*
)

