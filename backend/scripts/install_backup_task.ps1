<#
  Εγκατάσταση / επανεγκατάσταση των αυτόματων εργασιών αντιγράφων ασφαλείας στο Task Scheduler των Windows.
    1) «WEEE Platform DB Backup»      : κάθε 15 λεπτά, τοπικό αντίγραφο βάσης (backend\scripts\backup_db.py) - όπως ήδη τρέχει
    2) «WEEE Platform Offsite Backup» : κάθε μέρα στις 21:30, εκτός δίσκου (backend\scripts\offsite_backup.py)
  Χρήση (PowerShell):
      powershell -ExecutionPolicy Bypass -File backend\scripts\install_backup_task.ps1              # και οι δύο
      powershell -ExecutionPolicy Bypass -File backend\scripts\install_backup_task.ps1 -Only Offsite # μόνο η νέα (δεν πειράζει την υπάρχουσα των 15')
      powershell -ExecutionPolicy Bypass -File backend\scripts\install_backup_task.ps1 -Remove       # αφαίρεση της Offsite
  Δεν αγγίζει τα αντίγραφα ούτε τη βάση. Τρέχει με τον τρέχοντα χρήστη (όπως η υπάρχουσα εργασία).
#>
param([ValidateSet('Both','Local','Offsite')][string]$Only = 'Both', [switch]$Remove, [string]$At = '21:30')
$ErrorActionPreference = 'Stop'
$backend = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $backend '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $py)) { throw "Δεν βρέθηκε το $py (φτιάξε πρώτα το .venv: python -m venv .venv ; .venv\Scripts\python.exe -m pip install -r requirements.txt)" }
$user = "$env:USERDOMAIN\$env:USERNAME"

function Register([string]$name, [string]$script, $trigger) {
  $action = New-ScheduledTaskAction -Execute $py -Argument "`"$(Join-Path $PSScriptRoot $script)`"" -WorkingDirectory $backend
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
  $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "ΟΚ: δηλώθηκε η εργασία «$name»"
}

if ($Remove) {
  Unregister-ScheduledTask -TaskName 'WEEE Platform Offsite Backup' -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host 'Αφαιρέθηκε η εργασία «WEEE Platform Offsite Backup».'; exit 0
}
if ($Only -in 'Both','Local') {
  $t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
  Register 'WEEE Platform DB Backup' 'backup_db.py' $t
}
if ($Only -in 'Both','Offsite') {
  $t = New-ScheduledTaskTrigger -Daily -At $At
  Register 'WEEE Platform Offsite Backup' 'offsite_backup.py' $t
}
