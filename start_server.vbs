' 서버 자동 시작 (시작 프로그램의 TenderDashboard 바로가기가 이 파일을 실행한다)
'
' 창 없이 서버를 띄우고, 출력을 로그 파일에 남긴다.
'   -u  : 출력을 버퍼에 쌓지 않고 바로 쓴다. 빼면 로그 파일이 한참 동안 비어 있다.
'   로그: server_restart.log (출력), server_restart_err.log (오류)
' CLAUDE.md 의 '서버 재시작 절차' Step 3 과 같은 방식이다. 둘 중 하나를 고치면 다른 쪽도 맞춘다.
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "C:\Users\USER\Searcher"
shell.Run "cmd /c """"C:\Python314\python.exe"" -u app.py > server_restart.log 2> server_restart_err.log""", 0, False
Set shell = Nothing
