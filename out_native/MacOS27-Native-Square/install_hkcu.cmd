@echo off
setlocal enabledelayedexpansion
set "DEST=%LOCALAPPDATA%\Microsoft\Windows\Cursors\MacOS27-Native-Square"
if not exist "%DEST%" mkdir "%DEST%"
rem Every step is checked. Printing "Installed" after a failed copy or a failed
rem regimport is worse than printing nothing: the pointer silently stays on the
rem system one and the user has no reason to suspect the installer.
copy /Y "%~dp0cur\*.cur" "%DEST%" >nul
if errorlevel 1 goto :copyfail
copy /Y "%~dp0ani\*.ani" "%DEST%" >nul
if errorlevel 1 goto :copyfail
rem install.inf names these by bare name and SetupAPI resolves that relative
rem to the INF's own directory, so keep copies next to it as well.
copy /Y "%~dp0cur\*.cur" "%~dp0" >nul
if errorlevel 1 goto :copyfail
copy /Y "%~dp0ani\*.ani" "%~dp0" >nul
if errorlevel 1 goto :copyfail
reg import "%~dp0install_hkcu.reg"
if errorlevel 1 goto :regfail
rem Tell the shell to reload the pointer set now (SPI_SETCURSORS).
cscript //nologo "%~dp0refresh.vbs" >nul 2>&1
if errorlevel 1 (
  echo   Note: automatic refresh was blocked. Apply the scheme
  echo   in Settings ^> Mouse ^> Additional mouse options
  echo   ^> Pointers, choose "MacOS 27 (Apple Native, square multi-size)", then Apply.
)
echo.
echo   Installed. No administrator rights needed.
if errorlevel 1 goto :noflush
goto :done

:copyfail
echo.
echo   FAILED: could not write the cursor files to
echo   "%DEST%".
echo   Close anything using that folder and run this again.
goto :done

:regfail
echo.
echo   FAILED: the registry import was rejected, so nothing was applied.
echo   Close other apps that may hold the Cursors key and run this again.
goto :done

:noflush
echo.
echo   Installed, but the pointer was not reloaded (a security policy may be
echo   blocking cscript). The scheme is registered: apply it from
echo   Settings ^> Bluetooth ^& devices ^> Mouse ^> Additional mouse options
echo   ^> Pointers, choose "MacOS 27 (Apple Native, square multi-size)", then Apply.

:done
echo.
endlocal
