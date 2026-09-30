@echo off
chcp 65001 >nul
REM ------------------------------------------------------------------------------------------
REM Régénère app\static\vendor\tailwind.css (point 8 : styles embarqués, plus de CDN).
REM A lancer UNIQUEMENT après avoir ajouté de nouvelles classes Tailwind dans les pages HTML.
REM
REM Outil nécessaire (une seule fois) : tailwindcss.exe version 3, sans installation :
REM   https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.17
REM   -> télécharger « tailwindcss-windows-x64.exe », le renommer « tailwindcss.exe »
REM      et le poser dans ce dossier (outils_front).
REM ------------------------------------------------------------------------------------------
cd /d "%~dp0"
if not exist tailwindcss.exe (
  echo tailwindcss.exe introuvable dans %~dp0 : voir les instructions en haut de ce fichier.
  pause
  exit /b 1
)
tailwindcss.exe -c tailwind.config.js -i entree.css -o ..\app\static\vendor\tailwind.css --minify
echo.
echo Terminé. Rechargez les pages avec Ctrl+F5.
pause
