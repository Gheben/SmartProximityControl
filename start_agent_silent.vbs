Set WshShell = CreateObject("WScript.Shell")
' Avvia l'applicazione in modalità agent senza mostrare finestre
' Modifica il percorso se hai installato l'app in un'altra cartella
WshShell.Run """C:\en\scripts\Smart Proximity Control\SmartProximityControl.exe"" --agent", 0, False
Set WshShell = Nothing
