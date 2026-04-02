' 시작 프로그램 폴더에 바로가기 생성
Set WshShell = WScript.CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 경로 설정
startupFolder = WshShell.SpecialFolders("Startup")
scriptPath = "D:\tender_dashboard"
targetFile = scriptPath & "\start_server_background.vbs"
linkFile = startupFolder & "\입찰공고시스템.lnk"

' 기존 바로가기 삭제
If fso.FileExists(linkFile) Then
    fso.DeleteFile linkFile
End If

' 새 바로가기 생성
Set oLink = WshShell.CreateShortcut(linkFile)
oLink.TargetPath = targetFile
oLink.WorkingDirectory = scriptPath
oLink.Description = "입찰공고 통합 검색 시스템"
oLink.WindowStyle = 7
oLink.Save

WScript.Echo "바로가기 생성 완료: " & linkFile

Set oLink = Nothing
Set fso = Nothing
Set WshShell = Nothing
