Dim shell
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "C:\Users\USER\Searcher"
shell.Run """C:\Python314\python.exe"" app.py", 0, False
Set shell = Nothing
