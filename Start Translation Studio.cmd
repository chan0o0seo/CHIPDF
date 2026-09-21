@echo off
setlocal
for /f "delims=" %%D in ('dir "%~dp0dist" /b /ad /o-n 2^>nul') do (
    if exist "%~dp0dist\%%D\Translation Studio\Translation Studio.exe" (
        start "" "%~dp0dist\%%D\Translation Studio\Translation Studio.exe" %*
        exit /b 0
    )
)
echo No packaged build found. Build with: python build_portable.py --with-inpaint
pause
exit /b 1
