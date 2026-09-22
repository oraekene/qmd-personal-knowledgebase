' Silent Background Launcher for QMD Control Plane
' Launches python -m control_plane.server on port 3333 without popping up a console window.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)

' Change working directory to repo root
WshShell.CurrentDirectory = repoRoot

' Launch python control plane server with window hidden (0 = hidden, False = return immediately)
cmdStr = "python -m control_plane.server --port 3333"
WshShell.Run cmdStr, 0, False
