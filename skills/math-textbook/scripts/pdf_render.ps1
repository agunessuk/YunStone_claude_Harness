# =====================================================================
#  pdf_render.ps1 — PDF 쪽을 PNG 로 (윈도우 내장 Windows.Data.Pdf, 추가 설치 없음)
#  · 검수용(120~150dpi) · 분석용(300dpi) · 수식 비교(400dpi)
#  · -Ocr : 윈도우 한국어 OCR 로 낱말 좌표를 {이름}_ocr.csv 에 (쪽, 줄, 글자, x, y, w, h — 픽셀)
#  사용 예)
#   powershell -NoProfile -ExecutionPolicy Bypass -File pdf_render.ps1 -Pdf "출력\단원.pdf" -Dpi 120
#   … -Pdf 문제지.pdf -Dpi 300 -Pages "1-3,8" -OutDir "D:\tmp\쪽" -Ocr
#  · 쪽 범위는 글자 하나로 ("1-3,8"). -File 로 부를 때 배열을 넘기면 첫 값만 들어감.
# =====================================================================
param(
    [Parameter(Mandatory = $true)][string]$Pdf,
    [string]$OutDir = '',
    [int]$Dpi = 150,
    [string]$Pages = '',
    [string]$Prefix = '',
    [switch]$Ocr
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }   # 한글 출력이 깨지지 않게
if (-not (Test-Path -LiteralPath $Pdf)) { throw "PDF 를 찾지 못했습니다: $Pdf" }
$item = Get-Item -LiteralPath $Pdf
$base = $item.BaseName.Normalize([Text.NormalizationForm]::FormC)
if (-not $OutDir) { $OutDir = Join-Path $item.DirectoryName ($base + '_쪽') }
if (-not $Prefix) { $Prefix = $base }
if (-not (Test-Path -LiteralPath $OutDir)) { [void](New-Item -ItemType Directory -Path $OutDir -Force) }
$outFull = (Get-Item -LiteralPath $OutDir).FullName

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAct = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
function AwaitAction($op) { $task = $asTaskAct.Invoke($null, @($op)); $task.Wait(-1) | Out-Null }
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
[void][Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime]
[void][Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]

$engine = $null
if ($Ocr) {
    [void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    [void][Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('ko'))
    if (-not $engine) { Write-Host '[주의] 한국어 OCR 이 없어 OCR 없이 진행합니다 (설정 > 언어에서 한국어 추가).'; $Ocr = $false }
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($item.FullName)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
$folder = Await ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($outFull)) ([Windows.Storage.StorageFolder])
$count = [int]$doc.PageCount

$list = New-Object System.Collections.Generic.List[int]
if ($Pages) {
    foreach ($part in ($Pages -split ',')) {
        $part = $part.Trim(); if (-not $part) { continue }
        if ($part -match '^(\d+)\s*-\s*(\d+)$') { for ($i = [int]$Matches[1]; $i -le [int]$Matches[2]; $i++) { if ($i -ge 1 -and $i -le $count) { $list.Add($i) } } }
        elseif ($part -match '^\d+$') { if ([int]$part -ge 1 -and [int]$part -le $count) { $list.Add([int]$part) } }
        else { throw "쪽 범위 형식이 잘못됐습니다: '$part' (예: 1-5,8)" }
    }
} else { for ($i = 1; $i -le $count; $i++) { $list.Add($i) } }

$digits = [Math]::Max(3, "$count".Length)
$rows = New-Object System.Collections.Generic.List[string]
$rows.Add('쪽,줄,글자,x,y,w,h')
foreach ($pn in $list) {
    $page = $doc.GetPage($pn - 1)
    $w = [int][Math]::Round($page.Size.Width / 96.0 * $Dpi)      # Size 단위 = 1/96 인치
    $name = ('{0}_p{1}.png' -f $Prefix, $pn.ToString().PadLeft($digits, '0'))
    $out = Await ($folder.CreateFileAsync($name, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
    $stream = Await ($out.OpenAsync([Windows.Storage.FileAccessMode]::ReadWrite)) ([Windows.Storage.Streams.IRandomAccessStream])
    $opt = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $opt.DestinationWidth = [uint32]$w
    AwaitAction ($page.RenderToStreamAsync($stream, $opt))
    if ($Ocr) {
        $stream.Seek(0)
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $sb = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        if ($sb.PixelWidth -le [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -and $sb.PixelHeight -le [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) {
            $res = Await ($engine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
            $ln = 0
            foreach ($line in @($res.Lines)) {
                $ln++
                foreach ($wd in @($line.Words)) {
                    $r = $wd.BoundingRect
                    $t = $wd.Text.Replace('"', '""')
                    $rows.Add(('{0},{1},"{2}",{3:0},{4:0},{5:0},{6:0}' -f $pn, $ln, $t, $r.X, $r.Y, $r.Width, $r.Height))
                }
            }
        } else { Write-Host "[주의] $pn 쪽은 OCR 최대 크기를 넘어 건너뜀 (-Dpi 를 낮추세요)" }
        $sb.Dispose()
    }
    $stream.Dispose()
    $page.Dispose()
    Write-Host ("  {0}" -f (Join-Path $outFull $name))
}
if ($Ocr) {
    $csv = Join-Path $outFull ($Prefix + '_ocr.csv')
    [IO.File]::WriteAllLines($csv, $rows, (New-Object Text.UTF8Encoding $true))
    Write-Host "  OCR: $csv"
}
Write-Host ("완료: 전체 {0}쪽 중 {1}쪽, {2}dpi → {3}" -f $count, $list.Count, $Dpi, $outFull)
