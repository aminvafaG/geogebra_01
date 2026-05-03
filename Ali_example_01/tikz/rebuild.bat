@echo off
rem Double-click this to rebuild the vector PDF from the current .ggb file.
rem Looks for *.ggb in the parent folder; produces a PDF named the same way.
setlocal
cd /d "%~dp0"
python ggb2pdf.py --open
if errorlevel 1 pause
