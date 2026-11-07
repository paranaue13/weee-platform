<#
  ΑΝΤΙΓΡΑΦΟ ΑΣΦΑΛΕΙΑΣ ΤΩΡΑ: τρέχει αμέσως την αντιγραφή εκτός δίσκου (USB + OneDrive + GitHub).
  Καλείται από το «ΑΝΤΙΓΡΑΦΟ ΑΣΦΑΛΕΙΑΣ ΤΩΡΑ.cmd». -NoPause και ό,τι άλλο ακολουθεί: μόνο για δοκιμές (προσωρινοί φάκελοι).
#>
param([switch]$NoPause, [Parameter(ValueFromRemainingArguments = $true)][string[]]$ExtraArgs)
$ErrorActionPreference = 'Continue'
try { chcp 65001 | Out-Null; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::InputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$scripts = Split-Path -Parent $PSScriptRoot
$backend = Split-Path -Parent $scripts
$py = Join-Path $backend '.venv\Scripts\python.exe'
$docs = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'WEEE Platform\Αντίγραφα ασφαλείας'
function Wait-Close { if (-not $NoPause) { Write-Host ''; Read-Host 'Πάτα Enter για να κλείσει αυτό το παράθυρο' | Out-Null } }

if (-not (Test-Path $py)) { Write-Host "ΣΦΑΛΜΑ: δεν βρέθηκε το $py" -ForegroundColor Red; Wait-Close; exit 2 }
Write-Host 'Γίνεται αντίγραφο ασφαλείας εκτός δίσκου (USB + OneDrive + GitHub)...' -ForegroundColor Cyan
Set-Location $scripts
& $py 'offsite_backup.py' @ExtraArgs
$code = $LASTEXITCODE
Write-Host ''
Write-Host 'Δες το αποτέλεσμα στο αρχείο:' -ForegroundColor Cyan
Write-Host ('  ' + (Join-Path $docs 'ΑΝΤΙΓΡΑΦΑ ΑΣΦΑΛΕΙΑΣ - ΚΑΤΑΣΤΑΣΗ.txt'))
Wait-Close
exit $code
