<#
  ΑΝΕΒΑΣΜΑ ΣΤΟ GITHUB: ανεβάζει τον κώδικα (ΟΧΙ τη βάση, ΟΧΙ το .env) στο ιδιωτικό GitHub.
  Καλείται από το «ΑΝΕΒΑΣΜΑ ΣΤΟ GITHUB.cmd». -RepoDir/-Remote/-Branch/-NoPause: μόνο για δοκιμές (προσωρινό αποθετήριο).
#>
param([string]$RepoDir = '', [string]$Remote = 'origin', [string]$Branch = 'master', [switch]$NoPause)
$ErrorActionPreference = 'Continue'
try { chcp 65001 | Out-Null; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::InputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$scripts = Split-Path -Parent $PSScriptRoot
$backend = Split-Path -Parent $scripts
function Wait-Close { if (-not $NoPause) { Write-Host ''; Read-Host 'Πάτα Enter για να κλείσει αυτό το παράθυρο' | Out-Null } }

if (-not $RepoDir) { $RepoDir = Split-Path -Parent $backend }
$env:PATH = $env:PATH + ';C:\Program Files\Git\bin;C:\Program Files\Git\cmd'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host 'ΣΦΑΛΜΑ: δεν βρέθηκε το Git (git-scm.com).' -ForegroundColor Red; Wait-Close; exit 2 }
Set-Location $RepoDir
Write-Host ('=' * 70)
Write-Host ' ΑΝΕΒΑΣΜΑ ΤΟΥ ΚΩΔΙΚΑ ΣΤΟ ΙΔΙΩΤΙΚΟ GITHUB (https://github.com/paranaue13/weee-platform)'
Write-Host ' Την πρώτη φορά θα ανοίξει παράθυρο για σύνδεση στο GitHub: συνδέσου με τον λογαριασμό σου.'
Write-Host ('=' * 70)
git push -u $Remote $Branch
$c1 = $LASTEXITCODE
Write-Host ''
git push $Remote --tags
$c2 = $LASTEXITCODE
Write-Host ''
if ($c1 -eq 0 -and $c2 -eq 0) { Write-Host 'ΕΓΙΝΕ: ο κώδικας ανέβηκε στο GitHub (παραπάνω γράφει «master -> master» ή «Everything up-to-date»).' -ForegroundColor Green }
else { Write-Host 'ΔΕΝ ανέβηκε. Αν δεν έχεις συνδεθεί στο GitHub, ξαναδοκίμασε και συνδέσου όταν ανοίξει το παράθυρο.' -ForegroundColor Red }
Wait-Close
exit ([int]($c1 -ne 0 -or $c2 -ne 0))
