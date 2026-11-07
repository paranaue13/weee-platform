<#
  ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ BACKUP: τυπώνει καθαρά ελληνικά μηνύματα, τρέχει το setup_backup_key.py και λέει ρητά αν ο κωδικός ορίστηκε.
  Καλείται από το «ΡΥΘΜΙΣΗ ΚΩΔΙΚΟΥ BACKUP.cmd» (ένα απλό αρχείο μόνο με αγγλικά γράμματα).
  -NoPause και ό,τι άλλο ακολουθεί: μόνο για δοκιμές.
#>
param([switch]$NoPause, [Parameter(ValueFromRemainingArguments = $true)][string[]]$ExtraArgs)
$ErrorActionPreference = 'Continue'
try { chcp 65001 | Out-Null; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::InputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$scripts = Split-Path -Parent $PSScriptRoot
$backend = Split-Path -Parent $scripts
$py = Join-Path $backend '.venv\Scripts\python.exe'
function Wait-Close { if (-not $NoPause) { Write-Host ''; Read-Host 'Πάτα Enter για να κλείσει αυτό το παράθυρο' | Out-Null } }

if (-not (Test-Path $py)) { Write-Host "ΣΦΑΛΜΑ: δεν βρέθηκε το $py" -ForegroundColor Red; Wait-Close; exit 2 }
& $py (Join-Path $scripts 'setup_backup_key.py') @ExtraArgs
$code = $LASTEXITCODE
Write-Host ''
if ($code -eq 0) { Write-Host 'ΤΕΛΟΣ. Μπορείς να κλείσεις αυτό το παράθυρο.' -ForegroundColor Green }
else { Write-Host 'ΔΕΝ ορίστηκε κωδικός. Διάβασε το μήνυμα παραπάνω και ξαναπροσπάθησε.' -ForegroundColor Red }
Wait-Close
exit $code
