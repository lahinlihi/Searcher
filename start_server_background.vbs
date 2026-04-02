Set WshShell = CreateObject("WScript.Shell")

' 현재 스크립트의 디렉토리 경로 가져오기
Set fso = CreateObject("Scripting.FileSystemObject")
ScriptPath = fso.GetParentFolderName(WScript.ScriptFullName)

' Python 경로 찾기
PythonPath = ""
On Error Resume Next
PythonPath = WshShell.RegRead("HKEY_LOCAL_MACHINE\SOFTWARE\Python\PythonCore\3.14\InstallPath\")
On Error Goto 0

' Python 경로를 못 찾으면 기본 명령어 사용
If PythonPath = "" Then
    PythonCmd = "python.exe"
Else
    PythonCmd = PythonPath & "python.exe"
End If

' 작업 디렉토리로 이동 후 Python 앱 실행
' 0 = 창 숨김, False = 비동기 실행
WshShell.CurrentDirectory = ScriptPath
WshShell.Run PythonCmd & " app.py", 0, False

Set WshShell = Nothing
Set fso = Nothing
