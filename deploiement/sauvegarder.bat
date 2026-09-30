@echo off
chcp 65001 >nul
REM Sauvegarde de la base et des pièces jointes (tâche planifiée « PASL-RH Sauvegarde », chaque soir)
cd /d "%~dp0.."
venv\Scripts\python.exe -m app.scripts.sauvegarder
