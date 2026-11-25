' 서버 자동 시작 (시작 프로그램의 TenderDashboard 바로가기가 이 파일을 실행한다).
'
' 창 없이 서버를 띄우고, 출력을 로그 파일에 남긴다.
'   -u  : 출력을 버퍼에 쌓지 않고 바로 쓴다. 빼면 로그 파일이 한참 동안 비어 있다.
'   로그: server_restart.log (출력), server_restart_err.log (오류), server_boot_retry.log (재시도 기록).
' CLAUDE.md 의 '서버 재시작 절차' Step 3 과 같은 방식이다. 둘 중 하나를 고치면 다른 쪽도 맞춘다.
'
' 시작하자마자 죽으면 다시 띄운다 (2026-11-25 추가).
'   그날 08:30 부팅 직후 5002 포트를 잡지 못해(WinError 10013) 서버가 죽었고, 한 번만 시도하던 탓에
'   15:48 까지 사이트, 크롤, 뉴스 수집이 모두 멈췄다. 이 PC 는 윈도우 임시 포트 범위가 1024 부터라
'   부팅 직후 다른 프로그램이 5002 를 잠깐 집을 수 있다.
'   - 서버가 QUICK_EXIT_SEC 초 안에 끝나면 '시작 실패'로 보고 RETRY_WAIT_SEC 초 뒤 다시 띄운다. 최대 MAX_TRIES 번.
'   - 그보다 오래 돌다 끝났으면 누군가 일부러 내린 것(재시작 절차)이므로 다시 띄우지 않는다.
'   - 다시 띄우기 전에 app.py 가 이미 떠 있으면(사람이 먼저 띄운 경우) 그만둔다. 로그 파일을 덮어쓰지 않으려는 것.
'
' 주의: 이 파일은 UTF-8 로 저장돼 있고 윈도우 스크립트 호스트는 한글 윈도우의 기본 인코딩으로 읽는다.
'   그래서 한글은 주석에만 쓰고, 주석 줄은 반드시 ASCII 글자(마침표 등)로 끝낸다. 문자열에는 ASCII 만 쓴다.
Option Explicit
Const WORK_DIR = "C:\Users\USER\Searcher"
Const PYTHON = "C:\Python314\python.exe"
Const SCRIPT = "app.py"
Const MATCH = "app.py"
Const MAX_TRIES = 10
Const QUICK_EXIT_SEC = 120
Const RETRY_WAIT_SEC = 30

Dim shell, fso, attempt, started, elapsed
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
shell.CurrentDirectory = WORK_DIR

Sub Note(text)
    Dim f
    Set f = fso.OpenTextFile(WORK_DIR & "\server_boot_retry.log", 8, True)
    f.WriteLine Now & "  " & text
    f.Close
End Sub

Function AlreadyRunning()
    Dim wmi, procs, p
    AlreadyRunning = False
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'python.exe'")
    For Each p In procs
        If Not IsNull(p.CommandLine) Then
            If InStr(p.CommandLine, MATCH) > 0 Then AlreadyRunning = True
        End If
    Next
End Function

For attempt = 1 To MAX_TRIES
    If AlreadyRunning() Then
        Note "already running - not starting (attempt " & attempt & ")"
        Exit For
    End If
    started = Now
    shell.Run "cmd /c """"" & PYTHON & """ -u " & SCRIPT & " > server_restart.log 2> server_restart_err.log""", 0, True
    elapsed = DateDiff("s", started, Now)
    If elapsed >= QUICK_EXIT_SEC Then
        Note "server ran " & elapsed & "s then ended - not restarting"
        Exit For
    End If
    If fso.FileExists(WORK_DIR & "\server_restart_err.log") Then
        fso.CopyFile WORK_DIR & "\server_restart_err.log", WORK_DIR & "\server_boot_fail_" & attempt & ".log", True
    End If
    If attempt < MAX_TRIES Then
        Note "START FAILED: exited after " & elapsed & "s (attempt " & attempt & "/" & MAX_TRIES & ") - retry in " & RETRY_WAIT_SEC & "s. error log: server_boot_fail_" & attempt & ".log"
        WScript.Sleep RETRY_WAIT_SEC * 1000
    Else
        Note "START FAILED: all " & MAX_TRIES & " attempts failed - giving up. error log: server_boot_fail_" & attempt & ".log"
    End If
Next
