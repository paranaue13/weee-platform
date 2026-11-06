@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%PATH%;C:\Program Files\Git\bin;C:\Program Files\Git\cmd"
echo ======================================================================
echo  ΑΝΕΒΑΣΜΑ ΤΟΥ ΚΩΔΙΚΑ ΣΤΟ ΙΔΙΩΤΙΚΟ GITHUB (https://github.com/paranaue13/weee-platform)
echo  Την πρώτη φορά θα ανοίξει παράθυρο για σύνδεση στο GitHub: συνδέσου με τον λογαριασμό σου.
echo ======================================================================
git push -u origin master
echo.
git push origin --tags
echo.
echo Αν παραπάνω γράφει "master -> master" ή "Everything up-to-date", ΕΓΙΝΕ.
pause
