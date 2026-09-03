@echo off
chcp 65001 > nul
echo =======================================================================
echo   BLUELAB Morning Intelligence 브리핑 웹 뷰어 실행 중...
echo   브라우저 주소: http://localhost:8080
echo   종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo =======================================================================

start http://localhost:8080
cd public
py -m http.server 8080
if %ERRORLEVEL% NEQ 0 (
    python -m http.server 8080
)
