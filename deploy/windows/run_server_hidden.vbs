' GameNet - Hidden Process Runner
' Runs a command or script in background with no command prompt window.
If WScript.Arguments.Count = 0 Then
    WScript.Quit 1
End If

Set WshShell = CreateObject("WScript.Shell")
Dim cmdLine, i
cmdLine = ""
For i = 0 To WScript.Arguments.Count - 1
    If i > 0 Then cmdLine = cmdLine & " "
    cmdLine = cmdLine & chr(34) & WScript.Arguments(i) & chr(34)
Next

WshShell.Run cmdLine, 0, False
Set WshShell = Nothing
