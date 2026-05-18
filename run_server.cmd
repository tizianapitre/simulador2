@echo off
setlocal
set "PYTHON_EXE=C:\Users\tizia\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" server.py
) else (
  python server.py
)
