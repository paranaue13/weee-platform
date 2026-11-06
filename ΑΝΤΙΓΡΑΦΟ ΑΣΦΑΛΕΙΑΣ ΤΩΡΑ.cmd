@echo off
chcp 65001 >nul
cd /d "%~dp0backend\scripts"
echo Γίνεται αντίγραφο ασφαλείας εκτός δίσκου (USB + OneDrive + GitHub)...
"..\.venv\Scripts\python.exe" offsite_backup.py
echo.
echo Δες το αποτέλεσμα στο αρχείο "ΑΝΤΙΓΡΑΦΑ ΑΣΦΑΛΕΙΑΣ - ΚΑΤΑΣΤΑΣΗ.txt" στην Επιφάνεια Εργασίας.
pause
