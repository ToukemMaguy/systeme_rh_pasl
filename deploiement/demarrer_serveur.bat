@echo off
chcp 65001 >nul
REM ------------------------------------------------------------------------------------------
REM PASL-RH : démarrage du serveur en PRODUCTION (lancé automatiquement par la tâche planifiée
REM « PASL-RH Serveur » au démarrage de la machine ; peut aussi être lancé à la main pour tester).
REM Différences avec le mode développement : pas de --reload, écoute sur le réseau (0.0.0.0),
REM pas de journal de chaque page visitée (les erreurs vont dans logs\app.log).
REM ------------------------------------------------------------------------------------------
cd /d "%~dp0.."
if not exist logs mkdir logs
if not exist venv\Scripts\python.exe (
  echo Environnement Python introuvable : venv\Scripts\python.exe
  exit /b 1
)
set PORT=8000
if not "%PASL_RH_PORT%"=="" set PORT=%PASL_RH_PORT%
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --workers 1 --no-access-log --timeout-keep-alive 30 >> logs\serveur.log 2>&1
