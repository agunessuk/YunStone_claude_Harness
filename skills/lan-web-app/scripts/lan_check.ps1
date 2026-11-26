# 내부망 접속 점검 (읽기만 함, 아무 설정도 바꾸지 않음)
# 사용: powershell -NoProfile -ExecutionPolicy Bypass -File lan_check.ps1 [-Port 8810]
param([int]$Port = 8810)

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

function Line($ok, $msg) {
    $tag = if ($ok -eq $true) { 'OK  ' } elseif ($ok -eq $false) { 'X   ' } else { '..  ' }
    Write-Output ($tag + $msg)
}

Write-Output "== 내부망 접속 점검 (포트 $Port) =="

# 1. 내부 주소
$ips = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown'
})
if ($ips.Count -eq 0) { Line $false '내부 IPv4 주소가 없습니다(네트워크 연결 확인)' }
foreach ($ip in $ips) { Line $null ("주소 {0}  ({1})  → 다른 기기에서 http://{0}:{2}" -f $ip.IPAddress, $ip.InterfaceAlias, $Port) }

# 2. 네트워크 프로필
foreach ($p in @(Get-NetConnectionProfile)) {
    $priv = ($p.NetworkCategory -eq 'Private' -or $p.NetworkCategory -eq 'DomainAuthenticated')
    Line $priv ("네트워크 '{0}' ({1}) 프로필: {2}" -f $p.Name, $p.InterfaceAlias, $p.NetworkCategory)
}

# 3. 듣고 있는지
$listen = @(Get-NetTCPConnection -LocalPort $Port -State Listen)
if ($listen.Count -eq 0) {
    Line $false "포트 $Port 에서 듣고 있는 프로그램이 없습니다(서버가 꺼졌거나 포트가 다름)"
} else {
    foreach ($l in $listen) {
        $proc = (Get-Process -Id $l.OwningProcess).ProcessName
        $all = ($l.LocalAddress -eq '0.0.0.0' -or $l.LocalAddress -eq '::')
        Line $all ("듣는 주소 {0}:{1}  프로그램 {2} (PID {3}){4}" -f $l.LocalAddress, $Port, $proc, $l.OwningProcess, $(if ($all) { '' } else { '  ← 이 주소에만 열려 있어 다른 기기는 못 들어옴' }))
    }
}

# 4. 방화벽 규칙 (들어오는 허용, 켜진 것)
$rules = @(Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow)
$portRules = @()
foreach ($r in $rules) {
    $pf = $r | Get-NetFirewallPortFilter
    if ($pf.Protocol -eq 'TCP' -and ($pf.LocalPort -contains "$Port")) { $portRules += $r }
}
$appRules = @($rules | Where-Object { $_.DisplayName -match 'python' })
if ($portRules.Count -gt 0) {
    foreach ($r in $portRules) {
        $af = $r | Get-NetFirewallAddressFilter
        Line $true ("포트 규칙 '{0}' 프로필 {1} 원격 {2}" -f $r.DisplayName, $r.Profile, ($af.RemoteAddress -join ','))
    }
} else { Line $null "포트 $Port 를 직접 여는 규칙 없음(앱 허용 규칙이 있으면 괜찮음)" }
if ($appRules.Count -gt 0) {
    foreach ($r in $appRules) { Line $null ("앱 규칙 '{0}' 프로필 {1}" -f $r.DisplayName, $r.Profile) }
} else { Line $null "python 앱 허용 규칙 없음" }

# 5. 이 PC에서 실제로 열리는지
foreach ($u in @("http://127.0.0.1:$Port/") + @($ips | ForEach-Object { "http://$($_.IPAddress):$Port/" })) {
    try {
        $resp = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 3
        Line $true ("$u 응답 {0}" -f $resp.StatusCode)
    } catch {
        $code = $null
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        if ($code) { Line $true "$u 응답 $code" } else { Line $false "$u 응답 없음" }
    }
}

Write-Output ""
Write-Output "X 줄이 있으면 references/network-troubleshoot.md 의 차례를 따릅니다. 이 스크립트는 설정을 바꾸지 않았습니다."
