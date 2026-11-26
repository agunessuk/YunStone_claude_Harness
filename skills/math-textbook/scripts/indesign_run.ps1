# =====================================================================
#  indesign_run.ps1 — 인디자인을 COM 으로 열어 JSX 하나를 대화상자 없이 실행하고 결과 글을 돌려줌
#  · JSX 안에서 쓸 수 있는 것:  $.global.TEST (true) · $.global.TEST_OPTIONS (-Options 객체)
#    결과 = JSX 의 마지막 식 값. $.global.TEST_LOG 배열에 글을 쌓았으면 그 글을 줄 단위로 돌려줌
#  · -Doc : 이 작업본을 먼저 엶(이미 열려 있으면 그 문서). Document fonts 가 켜지도록 늘 창을 띄워 엶
#  · -Protect : 경로에 이 글자가 들어간 문서는 열지 않음(템플릿 보호, 예: '템플릿보관소')
#  사용 예)
#   powershell -NoProfile -ExecutionPolicy Bypass -File indesign_run.ps1 -Jsx "도구\인디자인스크립트\조립.jsx" `
#       -Doc "교재제작\공통수학1\A\2_작업본\나\공통수학1_A_v01_나.indd" -Options "{unit:'01'}" -Protect 템플릿보관소
#   … -Code "app.activeDocument.pages.length"         (파일 대신 짧은 코드)
#  · 조립·PDF 처럼 몇 분 걸리는 일은 백그라운드로 돌릴 것. CPU 0 인데 안 끝나면 주 스레드 일시 정지 여부 확인:
#      (Get-Process InDesign).Threads | ? WaitReason -eq Suspended
# =====================================================================
param(
    [string]$Jsx = '',
    [string]$Code = '',
    [string]$Doc = '',
    [string]$Options = '{}',
    [string]$Protect = '',
    [switch]$Save
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }   # 한글 출력이 깨지지 않게
if (-not $Jsx -and -not $Code) { throw '-Jsx 파일 또는 -Code 를 주세요.' }
$missing = [Reflection.Missing]::Value
$app = $null
foreach ($prog in 'InDesign.Application.2026', 'InDesign.Application') {
    try { $app = New-Object -ComObject $prog; break } catch { }
}
if (-not $app) { throw '인디자인을 COM 으로 열지 못했습니다 (설치·버전 확인).' }
function Invoke-Js([string]$src) { return $app.DoScript($src, 1246973031, $missing, $missing, $missing) }   # 1246973031 = JavaScript
function To-JsPath([string]$p) { return ((Resolve-Path -LiteralPath $p).Path -replace '\\', '/').Replace("'", "\'") }

if ($Doc) {
    if ($Protect -and $Doc.Contains($Protect)) { throw "보호 경로의 문서는 열지 않습니다: $Doc" }
    $dp = To-JsPath $Doc
    $open = @"
var old = app.scriptPreferences.userInteractionLevel; app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
var f = File('$dp'), d = null, i;
for (i = 0; i < app.documents.length; i++) { if (app.documents[i].fullName.fsName == f.fsName) { d = app.documents[i]; } }
if (!d) { d = app.open(f, true); }
app.activeDocument = d; app.scriptPreferences.userInteractionLevel = old;
d.name + ' (' + d.pages.length + '쪽)';
"@
    Write-Host ('문서: ' + (Invoke-Js $open))
}

if ($Jsx) {
    $jp = To-JsPath $Jsx
    $body = "__r = `$.evalFile(File('$jp'));"
} else {
    $body = "__r = eval(" + ("'" + $Code.Replace('\', '\\').Replace("'", "\'").Replace("`r", '').Replace("`n", '\n') + "'") + ");"
}
$run = @"
`$.global.TEST = true; `$.global.TEST_OPTIONS = $Options; `$.global.TEST_LOG = [];
var __old = app.scriptPreferences.userInteractionLevel; app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
var __r = '';
try { $body if (`$.global.TEST_LOG.length) { __r = `$.global.TEST_LOG.join('\n'); } }
catch (e) { __r = 'ERROR: ' + e.message + ' (줄 ' + e.line + ')'; }
app.scriptPreferences.userInteractionLevel = __old;
String(__r);
"@
$result = Invoke-Js $run
if ($Save -and $Doc) { [void](Invoke-Js "app.activeDocument.save(); 'ok';") ; Write-Host '저장함' }
Write-Output $result
if ("$result".StartsWith('ERROR:')) { exit 1 }
