@echo off
cd /d "%~dp0"
set PYTHONUTF8=1

if not exist "network_config.json" (
    copy "config.example.json" "network_config.json" >nul
    echo Fichier network_config.json cree depuis config.example.json
)

if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement virtuel...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

echo.
echo Dashboard : http://127.0.0.1:8000/static/index.html
echo API docs  : http://127.0.0.1:8000/docs
echo.
uvicorn main:app --reload --host 127.0.0.1 --port 8000
pause
