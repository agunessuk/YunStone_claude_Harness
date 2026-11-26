# 다른 기기에서 내부망 주소가 안 열릴 때

서버 PC에서는 `localhost`로 열리는데 다른 컴퓨터·휴대폰에서 안 열리는 경우. 위에서부터 차례로 본다. 서버 PC에서 `scripts/lan_check.ps1 -Port <포트>`를 먼저 돌리면 1~5번을 한 번에 볼 수 있다.

## 오류 문구로 먼저 가르기
| 보이는 것 | 뜻 | 먼저 볼 곳 |
|---|---|---|
| `ERR_ADDRESS_UNREACHABLE` | 그 주소까지 길을 못 찾음(방화벽 이전 단계) | 같은 공유기인지, 주소 숫자, 접속하는 기기의 로컬 네트워크 허용(맥·크롬) |
| `ERR_CONNECTION_TIMED_OUT` | 도착했지만 응답 없음 | 서버 PC 방화벽, 네트워크 프로필 '공용' |
| `ERR_CONNECTION_REFUSED` | 그 포트에 아무도 안 듣고 있음 | 서버가 꺼짐, 포트 다름, 서버가 127.0.0.1에만 묶임(`0.0.0.0`으로 열어야 함) |
| `Bad address` (검은 창·앱 빨간 글씨) | 윈도우 오류 14. 백신이 python·uv 실행·연결을 가로챌 때 흔함 | 창을 닫고 다시 켜기, 반복되면 백신 예외에 앱 폴더 |
| `Bad address` (주소창) | 주소를 잘못 적음 | `http://` 빠짐, `:` 대신 `;`, 숫자 틀림 |

## 차례
1. **주소**: 서버가 출력한 '내부망 접속: http://…:포트' 그대로. https 아님, 끝에 포트 필수. 서버 PC에서도 localhost 말고 그 주소로 열어 본다.
2. **같은 공유기**: 게스트 와이파이·휴대폰 데이터가 아닌지. 주소 앞 세 자리(192.168.0.)가 서버 PC와 같은지. 서버 PC에 IP가 여러 개(유선+무선, 가상 어댑터)면 공유기 쪽 주소를 고른다.
3. **네트워크 프로필 '개인'**: 설정 → 네트워크 및 인터넷 → 연결된 네트워크 → 네트워크 프로필 유형 [개인]. '공용'이면 윈도우가 들어오는 연결을 막는다.
   - 와이파이가 '공용'으로만 잡히면(관리자 터미널):
     `Get-NetConnectionProfile` → `Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private`
4. **방화벽 앱 허용**: Windows 보안 → 방화벽 및 네트워크 보호 → 방화벽에서 앱 허용 → 설정 변경 → 'Python'(여러 개면 모두) [개인] 체크.
5. **포트 직접 열기**(관리자 터미널):
   `New-NetFirewallRule -DisplayName "App 8810" -Direction Inbound -Protocol TCP -LocalPort 8810 -Action Allow -Profile Private,Domain`
   - 프로필이 끝내 '공용'에서 안 바뀌면 같은 공유기 기기만:
     `New-NetFirewallRule -DisplayName "App 8810 LAN" -Direction Inbound -Protocol TCP -LocalPort 8810 -Action Allow -Profile Any -RemoteAddress LocalSubnet`
   - 되돌리기: `Remove-NetFirewallRule -DisplayName "App 8810 LAN"`
6. **백신 방화벽**(V3·알약 등): 그 프로그램에서도 포트나 python을 허용.
7. **접속하는 쪽 기기**:
   - 맥(macOS 15 이후): 시스템 설정 → 개인정보 보호 및 보안 → **로컬 네트워크** → 크롬(또는 쓰는 브라우저) 켜기.
   - 크롬 최신판: 사이트가 내부망 주소에 접근할 때 '로컬 네트워크 접근' 허용을 묻거나 막는다. 주소창 왼쪽 사이트 설정에서 허용. 크롬 창이 여러 개 떠 있어도 설정은 브라우저 하나에 한 번.
8. **공유기**: 일부 공유기는 '무선 기기끼리 통신 차단(AP 격리)'이 켜져 있다. 공유기 설정은 사용자가 직접.

## 안내할 때
- 관리자 명령은 한 줄씩 코드 블록으로, 되돌리는 명령도 함께.
- 사용자가 화면 사진을 보내면 거기 적힌 글자(네트워크 이름, 프로필, 오류 코드)로 다음 단계를 고른다.
