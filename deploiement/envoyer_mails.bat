@echo off
chcp 65001 >nul
REM Envoi des mails en attente (tâche planifiée « PASL-RH Mails », toutes les 10 minutes)
cd /d "%~dp0.."
if not exist logs mkdir logs
venv\Scripts\python.exe -m app.scripts.envoyer_mails >> logs\mails.log 2>&1
