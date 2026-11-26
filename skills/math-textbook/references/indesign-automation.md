# 인디자인 자동화 (PowerShell COM + ExtendScript)

## 실행 방식
- PowerShell에서 `New-Object -ComObject InDesign.Application.2026`(없으면 `InDesign.Application`) → `$app.DoScript(코드, 1246973031, …)`. `1246973031`은 JavaScript 언어 상수. 남은 인자는 `[Reflection.Missing]::Value`.
- 스크립트 파일은 `$.evalFile(File('경로'))`로 부른다. 경로는 `/` 슬래시, 작은따옴표는 `\'`로.
- **대화상자 없이**: 열기·내보내기 전에 `app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT`, 끝나면 원래 값으로.
- **시험 모드 패턴**: `$.global.TEST = true; $.global.TEST_OPTIONS = {unit:'01'};` 를 먼저 넣고, 스크립트 안에서 `alert`·`confirm` 대신 로그 배열에 쌓아 마지막 식으로 돌려준다. 같은 스크립트를 사람은 패널에서, Claude는 COM으로 쓴다.
- 오류는 `try { … } catch (e) { 'ERROR: ' + e.message + ' (줄 ' + e.line + ')' }`로 글로 돌려받는다.
- `scripts/indesign_run.ps1`이 이 패턴을 감싼다.

## PowerShell 5.1 함정
- `&&`, `??`, 삼항 연산자 없음. 경로는 `-LiteralPath`.
- 변수 바로 뒤 한글은 변수 이름으로 읽힘 → `"${n}개"`.
- `-File`로 부를 때 배열 인자를 넘기면 첫 값만 들어감 → 쉼표 글자 하나로 넘기고 스크립트 안에서 나눈다.
- `.ps1`·`.jsx`·`.jsxinc`는 **UTF-8 BOM** 필수(없으면 한글이 깨지거나 문법 오류). `scripts/jsx_lint.py`로 검사.

## ExtendScript(ES3) 함정
- 없는 것: `let`/`const`, 화살표 함수, 템플릿 문자열, `JSON`, `Array.prototype.indexOf`·`map`·`forEach`, `String.trim`, 기본 매개변수, 구조 분해. 직접 작은 함수로 만든다.
- 특수 문자(①, −, ≠, 전각 공백 등)는 소스에 직접 쓰지 말고 `String.fromCharCode(0x2212)`. 도구가 `\u` 이스케이프를 바꿔 버리는 경우가 있다.
- 문서 좌표는 **펼침면 원점**이다. 쪽 기준 x를 쓰려면 `page.bounds[1]`을 더한다. 왼쪽·오른쪽 쪽은 여백이 다르므로 왼쪽 쪽은 내용을 일정량 왼쪽으로 옮긴다(템플릿 두 쪽을 재서 정함).
- `measurementUnit`을 mm로 맞추고 시작(`viewPreferences.horizontalMeasurementUnits = MeasurementUnits.MILLIMETERS`, 세로도). 끝나면 되돌린다.

## 쪽 다루기
- 템플릿이 '쪽 섞기 허용' 꺼져 있으면 쪽을 끼울 때 3쪽 펼침면이 생긴다 → 작업본에서 `doc.documentPreferences.allowPageShuffle = true`, 모든 펼침면 `allowPageShuffle = true`.
- `doc.pages[i]`는 순번 참조라 쪽을 넣으면 다른 쪽을 가리킨다 → 붙잡아 둘 쪽은 `doc.pages.itemByID(page.id)`.
- **원형 쪽 방식**: 처음 조립할 때 템플릿 견본 쪽(개념·문항·MEMO)을 레이블 `원형_개념` 등으로 맨 뒤에 남기고, 쪽이 필요할 때마다 `원형.duplicate(LocationOptions.AFTER, 기준쪽)` 한 뒤 견본 내용을 지우고 채운다. PDF 내보낼 때는 원형 쪽을 뺀다.
- 조립한 쪽에는 `page.label = '조립|u=01|k=문항|…'`. 다시 조립하면 그 단원 레이블 쪽만 지우고 같은 자리에 새로 만든다.

## 템플릿 글자 바꾸기
- 템플릿 글상자에 스크립트 레이블(`SERIES_NAME`, `PAGE_TITLE_TEXT` 등)을 찾아 쓴다. 레이블이 없으면 위치·글꼴로 찾되 명세 문서에 적어 둔다.
- 서식을 살린 채 글만 바꾸기: 첫 글자만 남기고 나머지를 지운 뒤 첫 글자의 `contents`를 새 글로. 숫자만 바꿀 때는 끝 숫자 범위만 `characters.itemByRange(a, b).contents = '07'`.
- 긴 제목 한 줄 맞춤: `while ((tf.overflows || tf.lines.length > 1) && pt > 최소) { pt -= 0.5; story.pointSize = pt; }` — 그 제목에만. 탭처럼 같은 역할이 여럿이면 가장 작게 맞춘 크기로 전체 통일.
- 색 찾기는 대소문자 무시(템플릿마다 `X_Base`·`X_BASE`처럼 다를 수 있음).

## 외부 PDF를 벡터로 앉히기
```js
app.pdfPlacePreferences.pageNumber = 쪽;
app.pdfPlacePreferences.pdfCrop = PDFCrop.CROP_PDF;
app.pdfPlacePreferences.transparentBackground = true;   // try 로 감쌈
var rect = page.rectangles.add({ geometricBounds: [Y, X, Y + h*PT*s, X + w*PT*s] });
rect.strokeWeight = 0; rect.fillColor = 'None'; rect.place(pdfFile);
var g = rect.graphics[0]; g.horizontalScale = g.verticalScale = s * 100;
g.move([X - x*PT*s, Y - y*PT*s]);       // 프레임이 영역만 보이게 그림을 밀어 넣음 (PT = 25.4/72)
rect.transparencySettings.blendingSettings.blendMode = BlendMode.MULTIPLY;  // 흰 바탕이 색 바탕 위에 네모로 안 보이게
```
- 한 문항의 조각이 여럿이면 `page.groups.add(조각들)`로 묶고 레이블을 붙인다.
- 인쇄본처럼 PDF 쪽 전체를 앉힐 때는 `CROP_MEDIA` + `transparentBackground = false`.

## 마스터 함정
- 마스터의 배경 그림 하나가 펼침면 전체에 걸쳐 있으면, 두 쪽이 서로 다른 마스터일 때 한쪽 배경이 옆 쪽 위를 덮는다 → 작업본 마스터마다 펼침면 폭의 1.5배 넘는 그림을 쪽별로 둘로 나누고(`duplicate` 후 경계를 쪽 경계로) 맨 뒤로 보낸다.
- 단원별 마스터(현재 단원 탭 강조)는 기본 마스터를 복제해 만든다. 단원 이름이 바뀌면 다시 돌려 모든 마스터를 함께 갱신.

## 글꼴
- 설치하지 않은 글꼴은 작업본 옆 `Document fonts/` 폴더에 넣으면 그 문서에서만 켜진다. 단, **창을 띄워 연 문서에서만** 켜진다(`app.open(f, true)`). 숨겨 열면 대체 글꼴로 짜인다.
- 이미 열린 문서에 글꼴을 새로 넣었으면 저장 상태일 때 닫고 다시 연다.
- `app.fonts`의 상태 값은 Document fonts에 대해 믿을 수 없다 → 글꼴 파일이 그 폴더에 있는지로 판단한다.

## 내보내기·점검
- PDF: `doc.exportFile(ExportFormat.PDF_TYPE, file, false, preset)`, 쪽 범위는 `app.pdfExportPreferences.pageRange = '12-39'`(인쇄 쪽 번호 기준), 끝나면 `PageRange.ALL_PAGES`로 되돌림.
- 점검: 링크 상태(`LINK_MISSING`·`LINK_OUT_OF_DATE`), `effectivePpi` 150 미만, 없는 글꼴, `story.overflows`, 빈 프레임 → 보고서 txt.

## 인디자인이 멈출 때
- CPU가 도는 '응답 없음'은 정상(조립·PDF 중). 몇 분 기다린다.
- CPU 0인데 안 끝나면 주 스레드가 일시 정지(Suspended)됐을 수 있다(백신 추정): `(Get-Process InDesign).Threads | ? WaitReason -eq Suspended`. 한 번 이어 주고(ResumeThread) 보고에 적는다. 자동으로 넣지 않는다.
- 조립·PDF는 백그라운드로 돌리고 끝나면 결과를 확인한다.
