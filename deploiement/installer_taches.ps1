# ------------------------------------------------------------------------------------------------
# PASL-RH : installation sur le SERVEUR (à lancer UNE fois, dans PowerShell « Exécuter en tant
# qu'administrateur ») :
#     powershell -ExecutionPolicy Bypass -File deploiement\installer_taches.ps1
#
# Crée trois tâches planifiées Windows et ouvre le port dans le pare-feu :
#   - PASL-RH Serveur    : démarre l'application au démarrage de la machine, la relance si elle s'arrête
#   - PASL-RH Mails      : envoie les mails en attente toutes les 10 minutes
#   - PASL-RH Sauvegarde : sauvegarde la base et les pièces jointes chaque soir à 20 h 30
# Relancer le script remplace les tâches existantes (sans risque).
# ------------------------------------------------------------------------------------------------
param(
    [int]$Port = 8000,
    [string]$HeureSauvegarde = "20:30"
)
$ErrorActionPreference = "Stop"
$Dossier = Split-Path -Parent $PSScriptRoot          # dossier de l'application (parent de « deploiement »)
Write-Host "Dossier de l'application : $Dossier"

if (-not (Test-Path "$Dossier\venv\Scripts\python.exe")) { throw "venv introuvable dans $Dossier : installez d'abord l'application (voir DEPLOIEMENT.md)." }
if (-not (Test-Path "$Dossier\.env")) { throw "Fichier .env introuvable dans $Dossier." }

$Compte = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

function Installer($Nom, $Script, $Declencheur, $Reglages) {
    $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Dossier\deploiement\$Script`"" -WorkingDirectory $Dossier
    Unregister-ScheduledTask -TaskName $Nom -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $Nom -Action $Action -Trigger $Declencheur -Principal $Compte -Settings $Reglages | Out-Null
    Write-Host "  Tâche « $Nom » installée."
}

# 1. Serveur : au démarrage, sans limite de durée, relancé toutes les minutes en cas d'arrêt
$env:PASL_RH_PORT = "$Port"
[Environment]::SetEnvironmentVariable("PASL_RH_PORT", "$Port", "Machine")
$ReglagesServeur = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Installer "PASL-RH Serveur" "demarrer_serveur.bat" (New-ScheduledTaskTrigger -AtStartup) $ReglagesServeur

# 2. Mails : toutes les 10 minutes, jamais deux envois en même temps
$ReglagesCourts = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew -StartWhenAvailable
$DeclMails = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 10)
Installer "PASL-RH Mails" "envoyer_mails.bat" $DeclMails $ReglagesCourts

# 3. Sauvegarde : chaque soir
$ReglagesSauvegarde = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew -StartWhenAvailable
Installer "PASL-RH Sauvegarde" "sauvegarder.bat" (New-ScheduledTaskTrigger -Daily -At $HeureSauvegarde) $ReglagesSauvegarde

# 4. Pare-feu : autorise les postes du réseau de l'entreprise à joindre l'application
Remove-NetFirewallRule -DisplayName "PASL-RH (port $Port)" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "PASL-RH (port $Port)" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Domain,Private | Out-Null
Write-Host "  Pare-feu : port $Port ouvert (réseaux Domaine et Privé)."

# 5. Démarrage immédiat du serveur
Start-ScheduledTask -TaskName "PASL-RH Serveur"
Start-Sleep -Seconds 5
try {
    $r = Invoke-WebRequest -Uri "http://localhost:$Port/login" -UseBasicParsing -TimeoutSec 15
    Write-Host "`nOK : l'application répond (HTTP $($r.StatusCode))." -ForegroundColor Green
} catch {
    Write-Host "`nL'application ne répond pas encore : consultez $Dossier\logs\serveur.log" -ForegroundColor Yellow
}
Write-Host "Adresse pour les utilisateurs : http://$($env:COMPUTERNAME):$Port"
