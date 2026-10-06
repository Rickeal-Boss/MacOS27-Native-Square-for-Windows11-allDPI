Option Explicit
' Reload the pointer set after the registry was written.
' Writing HKCU\Control Panel\Cursors alone does not take effect: the shell
' caches the cursor set, and SystemParametersInfo(SPI_SETCURSORS) is what
' makes it re-read. fWinIni must be 0 -- UPDATEINIFILE|SENDCHANGE returns
' FALSE here; the in-memory refresh is the one that works.
'
' pvParam is declared As Any and passed Nothing. Passing a literal 0 works on
' most builds but can trip a Variant type mismatch on others; Nothing is the
' documented way to pass a null pointer here.
Declare Function SystemParametersInfo Lib "user32" Alias "SystemParametersInfoA" _
  (ByVal uiAction As Long, ByVal uiParam As Long, ByVal pvParam As Any, _
   ByVal fWinIni As Long) As Long

Const SPI_SETCURSORS = &H57

If SystemParametersInfo(SPI_SETCURSORS, 0, Nothing, 0) = 0 Then
  WScript.Quit 1
End If
WScript.Quit 0
