@echo off
chcp 65001 >nul
rem 표지문구.txt 를 바꾼 뒤 이 파일을 더블클릭하면 PDF 2개(앞표지, 뒤표지)를 새로 만듭니다.
cd /d "%~dp0"
set "BR=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%BR%" set "BR=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%BR%" set "BR=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%BR%" set "BR=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BR%" set "BR=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BR%" (
  echo 크롬이나 엣지를 찾지 못했습니다. 둘 중 하나를 설치해 주세요.
  if not defined COVER_NOPAUSE pause
  exit /b 1
)
set "HERE=%~dp0"
set "URL=file:///%HERE:\=/%표지.html"
if exist "%HERE%표지_앞.pdf" del "%HERE%표지_앞.pdf"
if exist "%HERE%표지_뒤.pdf" del "%HERE%표지_뒤.pdf"
echo 앞표지 만드는 중...
"%BR%" --headless=new --disable-gpu --allow-file-access-from-files --no-pdf-header-footer --virtual-time-budget=3000 --print-to-pdf="%HERE%표지_앞.pdf" "%URL%#front" 2>nul
echo 뒤표지 만드는 중...
"%BR%" --headless=new --disable-gpu --allow-file-access-from-files --no-pdf-header-footer --virtual-time-budget=3000 --print-to-pdf="%HERE%표지_뒤.pdf" "%URL%#back" 2>nul
if exist "%HERE%표지_앞.pdf" if exist "%HERE%표지_뒤.pdf" (
  echo.
  echo 완료: 표지_앞.pdf, 표지_뒤.pdf
  if not defined COVER_NOPAUSE pause
  exit /b 0
)
echo 만들지 못했습니다. 표지문구.txt 의 따옴표가 빠지지 않았는지 확인해 주세요.
if not defined COVER_NOPAUSE pause
exit /b 1
