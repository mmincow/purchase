@echo off
chcp 65001 > nul
cd /d "C:\Users\somin\OneDrive\Desktop\자동화\purchase"

REM 서버가 이미 실행 중이면 스킵
netstat -ano | findstr ":8000 " > nul 2>&1
if not errorlevel 1 (
    start "" "http://localhost:8000"
    exit /b
)

REM 백그라운드로 웹서버 실행 (창 숨김)
start "" /min cmd /c "python app.py"

REM 서버 뜰 때까지 대기
timeout /t 4 /nobreak > nul

REM 기본 브라우저로 웹앱 열기
start "" "http://localhost:8000"
