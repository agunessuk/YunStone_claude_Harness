# YunStone Claude Harness

내 작업 방식에 맞춘 Claude Code 설정 모음입니다. 한 사람의 작업 기록을 분석해 만든 규칙이라, 다른 사람이 쓸 때는 아래 "다른 사람이 쓸 때"를 먼저 읽어 주세요.

## 설치

Windows:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 --dry-run   # 미리보기
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1             # 설치·갱신
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 --uninstall # 제거
```
Mac: `./install.sh` (옵션 같음)

- 이 폴더가 정본입니다. 고친 뒤 다시 설치하면 갱신됩니다.
- 설치는 이 하네스가 넣은 것만 바꿉니다. 같은 이름의 다른 스킬은 건너뛰고, `CLAUDE.md`는 표지 주석 사이 블록만 바꾸며, `settings.json`은 백업한 뒤 훅 연결만 추가합니다.
- 설치 후 새로 연 Claude Code 세션부터 적용됩니다.

## 구성

| 위치 | 내용 |
|---|---|
| `global/CLAUDE.md` | 항상 적용할 원칙 → `~/.claude/CLAUDE.md` 블록 |
| `skills/` | 필요할 때 꺼내 쓰는 절차 11개 → `~/.claude/skills/` |
| `hooks/` | 실제로 막거나 자동 실행하는 훅 → `~/.claude/hooks/local-harness/` |
| `skills/new-project/` | 표준 프로젝트 틀(`template/`)과 만드는 스크립트(`scripts/new_project.py`) |
| `skills/blender-motion/` | 몹 모션 스크립트(`scripts/`), 설계 예시(`templates/`), 좌표·설계·연결 규칙(`references/`) |
| `skills/mob-modeling/` | 몹 모델 검사·프로필·라인업 렌더·밀도·다시 칠하기·부품 보강 스크립트(`scripts/`), 기준 파일 템플릿·설계 예시(`templates/`), 1층 공통 규칙·2층 스타일 프로필·엔진 규칙·설계 요령(`references/`) |
| `tests/` | 시험: `python tests/test_hooks.py`, `python tests/test_new_project.py`, `python tests/test_blender_motion.py`, `python tests/test_mob_modeling.py` |

## 훅이 하는 일

| 훅 | 동작 | 켜는 법 |
|---|---|---|
| 원본 보호 | 목록에 있는 경로를 Edit·Write로 고치면 **차단**(대소문자 구별 없음), 셸 명령으로 건드리면 **확인 요청**. 글롭 패턴(`plugins/*.jar`)은 맞는 파일·폴더 자체·와일드카드일 때만 확인 | 프로젝트에 `.claude/protected.txt` |
| 위험 명령 확인 | `rm -r`, `Remove-Item -Recurse`, `git reset --hard`, `git push --force`, `git clean -f` 등은 실행 전에 **확인 요청** | 항상 켜짐 |
| 읽기 전용 모드 | 허용한 폴더 밖 파일 수정은 **차단**, 파일을 바꾸는 셸 명령은 **확인 요청** | 프로젝트에 `.claude/READONLY` (지우면 꺼짐) |
| 상태 복원 | 세션 시작·재개·문맥 압축 뒤 `PROGRESS.md`, 읽기 전용 여부, 보호 목록을 자동으로 알려 줌 | 프로젝트 루트에 `PROGRESS.md` |
| 자기 보호 | 훅 파일, `settings.json`, 프로젝트의 `protected.txt`·`READONLY`·`approvals.json` 수정은 파일 도구든 셸이든 **확인 요청** (AI가 `approvals.json`을 파일 도구로 쓰면 **차단**) | 항상 켜짐 |
| 사용자 승인 | 확인 요청에 걸린 셸 명령을 사용자가 미리 승인해 두면 **그 명령 문자열 그대로일 때만** 통과. 1회 승인은 한 번 쓰면 끝, 만료 시각 있음. 하네스 설정 변경은 승인으로도 못 엶 | 프로젝트에 `.claude/approvals.json` (워크벤치가 사용자 답을 받아 씀) |

- 차단·확인·승인 사용 기록: `~/.claude/local-harness-log/events.jsonl`
- 승인이 필요한 이유: 헤드리스 실행(`claude -p`)에서는 확인 요청을 받을 사람이 없어 자동 거부된다. 사람이 나중에 "이 명령 1번 허락"이라고 답하면 그 명령만 통과시켜 작업을 이어 갈 수 있다.
- `approvals.json` 형식: `{"approvals": [{"sha256": 명령 문자열(앞뒤 공백 제거)의 sha256, "command": 명령, "once": true, "expires": 유닉스 시각, "used": 0}]}`
- 셸 명령 검사는 글자 패턴으로 하는 대략적인 검사라서 차단하지 않고 확인만 받습니다. 셸 동사(rm, cp, >)뿐 아니라 `python -c`·`node -e`의 파일 쓰기, `[IO.File]::Write…`, `find -delete`, 압축 풀기도 봅니다.
- 알려진 빈틈: `python 스크립트.py input/a.txt`처럼 **스크립트 파일 안에서** 원본을 쓰는 것은 명령만 봐서는 알 수 없어 통과합니다.
- 훅은 고장 나면 조용히 통과합니다. Python을 다시 깔았거나 이상하면 `python install.py --check`로 점검합니다.

## 스킬

| 스킬 | 언제 |
|---|---|
| `new-project` | 새 프로젝트 시작, 하네스 틀 세팅 (표준 폴더·기준 파일·보호 목록을 스크립트로) |
| `resume-work` | 끊긴 작업 이어가기, PROGRESS.md 관리 |
| `feedback-round` | 번호 피드백 반영, 반복 지적을 품질 기준으로 굳히기 |
| `handoff-pack` | 다른 AI·사람·PC로 인계본 만들기 |
| `gpt-collab` | GPT에게 그림 맡기기, GPT 명세·검수 받아 반영 |
| `print-doc-qa` | 시험지·교재·홍보물 레이아웃 검수 |
| `status-report` | 진행 상황과 최종 보고 |
| `project-index` | 토큰을 아끼는 README·파일 색인 |
| `env-and-cleanup` | Windows·Mac 함정, 서버·프로세스·파일 정리 |
| `blender-motion` | 마인크래프트 ModelEngine 몹·보스(.bbmodel)에 Blender로 3D 모션을 만들어 넣고, MythicMobs 판정 타이밍에 연결 (Blender·numpy·Pillow 필요) |
| `mob-modeling` | 몹·보스 모델 스타일 맞추기와 디테일 살리기. 기준은 2층: 1층 공통 규칙(엔진·텍셀 밀도·겹침·색 위생, 스킬 내장) + 2층 스타일 프로필(프로젝트가 고른 기준 몹에서 만듦, 여러 개). 검사·라인업 렌더·밀도·다시 칠하기·큐브 부품 보강 (`blender-motion` 함께 필요, Blender 4.x) |

## 새 프로젝트에 적용하기
Claude에게 "새 프로젝트야, 하네스 틀 세팅해줘"라고 하면 `new-project` 스킬이 아래를 대신합니다. 직접 할 때:
1. `python skills/new-project/scripts/new_project.py "<프로젝트 폴더>" --dry-run`으로 미리 보고, `--dry-run`을 빼고 실행합니다. 이미 있는 파일은 덮어쓰지 않습니다.
2. 표준 폴더: `input/`(원본, 보호) `work/` `output/` `output/확정/`(보호) `handoff/`(zip 보호) `review/` `prompts/` `docs/`
3. 원본이 따로 있으면 `.claude/protected.txt`에 경로를 더 적습니다.
4. 분석만 시킬 때는 `.claude/READONLY.example`을 `READONLY`로 복사합니다.

## 다른 사람이 쓸 때
- `global/CLAUDE.md`는 만든 사람의 작업 방식입니다(한국어 보고, 폰 Remote Control 확인 등). 설치 전에 자기 방식으로 고치세요. 설치기는 이 내용을 `~/.claude/CLAUDE.md`의 표지 주석 사이 블록으로 넣습니다.
- 훅은 Python 3로 돌아갑니다.
- 같은 이름의 스킬이 이미 있으면 덮어쓰지 않고 건너뜁니다. 제거는 `--uninstall`.

### Claude Code에 붙여 넣는 설치 프롬프트
```
YunStone Claude 하네스를 내 Claude Code에 설치해줘.
저장소: https://github.com/agunessuk/YunStone_claude_Harness

순서:
1. 저장소를 내 홈 폴더 아래 `YunStone_claude_Harness`로 받아줘 (git clone). 이미 있으면 git pull로 최신화해.
2. README.md를 읽고 이 하네스가 무엇을 바꾸는지 나에게 짧게 설명해줘.
3. global/CLAUDE.md 내용을 보여주고, 내 작업 방식과 다른 부분이 있으면 고칠지 물어봐줘.
4. 설치 스크립트를 --dry-run 으로 먼저 돌려서 바뀔 파일 목록을 보여줘.
   - Windows: powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 --dry-run
   - Mac/Linux: ./install.sh --dry-run
5. 내가 확인하면 --dry-run 없이 설치해줘.
6. python tests/test_hooks.py 로 훅 시험을 돌리고 결과를 알려줘.
7. 끝나면 새 세션을 열어야 적용된다는 것과 제거 방법(--uninstall)을 알려줘.

Python 3가 없으면 설치하지 말고 먼저 알려줘.
```

## 라이선스와 출처
MIT ([LICENSE](LICENSE)). 일부 스킬은 FOD-team-org/FOD-skills(MIT)를 바탕으로 고쳐 썼습니다. 자세한 출처는 [NOTES.md](NOTES.md).
