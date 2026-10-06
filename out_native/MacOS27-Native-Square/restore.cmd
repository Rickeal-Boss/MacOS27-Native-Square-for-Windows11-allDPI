@echo off
setlocal
for %%R in ("Arrow" "Help" "AppStarting" "Wait" "Crosshair" "IBeam" "NWPen" "No" "SizeNS" "SizeWE" "SizeNWSE" "SizeNESW" "SizeAll" "UpArrow" "Hand" "Person" "Pin") do (
  reg delete "HKCU\Control Panel\Cursors" /v %%R /f >nul 2>&1
)
reg delete "HKCU\Control Panel\Cursors" /v "Scheme Source" /f >nul 2>&1
reg delete "HKCU\Control Panel\Cursors" /ve /f >nul 2>&1
reg delete "HKCU\Control Panel\Cursors\Schemes" /v "MacOS 27 (Apple Native, square multi-size)" /f >nul 2>&1
if exist "%LOCALAPPDATA%\Microsoft\Windows\Cursors\MacOS27-Native-Square" (
  rd /S /Q "%LOCALAPPDATA%\Microsoft\Windows\Cursors\MacOS27-Native-Square"
)
cscript //nologo "%~dp0refresh.vbs" >nul 2>&1
if errorlevel 1 goto :noflush
echo.
echo   Cleared, and the shell was told to reload. Windows falls back to the
echo   default pointer scheme.
echo.
goto :done
:noflush
echo.
echo   Cleared, but the pointer was not reloaded (cscript may be blocked).
echo   Sign out and back in, or re-apply in the Pointers panel.
:done
echo.
echo   Note: this deletes the scheme, it does not back it up. If another
echo   pointer scheme was active before, reinstall that one afterwards.
echo.
endlocal
