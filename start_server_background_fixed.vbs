Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 현재 스크립트의 디렉토리 경로 가져오기
ScriptPath = fso.GetParentFolderName(WScript.ScriptFullName)

' 배치 파일 경로
BatchFile = ScriptPath & "\start_server_silent.bat"

' 배치 파일이 없으면 생성
If Not fso.FileExists(BatchFile) Then
    Set objFile = fso.CreateTextFile(BatchFile, True)
    objFile.WriteLine "@echo off"
    objFile.WriteLine "cd /d " & Chr(34) & ScriptPath & Chr(34)
    objFile.WriteLine "python app.py"
    objFile.Close
End If

' 백그라운드에서 배치 파일 실행 (창 숨김)
WshShell.Run Chr(34) & BatchFile & Chr(34), 0, False

Set WshShell = Nothing
Set fso = Nothing
