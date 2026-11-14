# 출처와 변경 기록

## 참고한 저장소
| 저장소 | 라이선스 | 가져온 것 |
|---|---|---|
| FOD-team-org/FOD-skills | MIT (Copyright (c) 2026 FOD-team-org) | 아래 스킬의 구조와 일부 규칙을 이 사용자에 맞게 줄이고 고쳐 씀 |
| kyu1204/oh-my-harness | MIT | "글로 쓴 규칙은 부탁, 훅은 강제"라는 개념, 차단 기록(events.jsonl), 하네스 자기 보호 아이디어. 코드는 가져오지 않음 |
| FOD-team-org/codex-task-playbook | — | 첫 작업 지시 프롬프트 틀("이전 대화를 모른다") 참고 |
| FOD-team-org/fod-harness | — | 가져오지 않음 (Pi 기반 전용 터미널은 불필요) |

## 스킬별 출처
| 이 저장소 스킬 | 바탕 | 바꾼 점 |
|---|---|---|
| resume-work | 새로 작성 | 기록에서 "이어서 진행해"가 반복된 것을 근거로 함 |
| feedback-round | 새로 작성 | 이펙트·레이아웃 피드백 반복을 근거로, 반복 지적을 품질 기준으로 굳히는 단계 추가 |
| handoff-pack | FOD `cross-device-handoff`, `delegation-loop` | AI 간 인계, 첫 작업 프롬프트, 변경 이력 빼기, 압축 해제 실행 확인 |
| gpt-collab | FOD `multi-ai-review`, `codex-delegation` | 그림은 GPT, 구현은 Claude라는 분담, 채택 필터 축소 |
| print-doc-qa | FOD `visual-output-qa` | 영상 항목 제거, 시험지·교재 레이아웃 항목으로 교체 |
| status-report | FOD `evidence-status-report` | 사용자 관점 표현, 내부 코드명 풀어쓰기 |
| project-index | 새로 작성 | 파일 ID 색인 요청을 근거로 함 |
| env-and-cleanup | FOD `windows-env-pitfalls`, `macos-env-pitfalls`, `agent-resource-hygiene`, `safe-cleanup` | 해당 항목만 남겨 하나로 합침 |
| blender-motion | 새로 작성 | 베어타이쿤 던전팩 작업에서 검증한 과정을 묶음: 기존 동작을 Blender 로 렌더해 Blockbench 부호 규칙 확인, 해골 3종·수호목 골렘 새 동작 제작, 팩 동작을 판정 틱에 맞춰 연결 |

## 변경 기록
- 2026-11-13 v1: 훅 2개(guard, session_restore), 스킬 8개, 전역 CLAUDE.md, 설치기
- 2026-11-14 v1.1: 보호 경로 검사를 프로젝트 맨 위 경로로 좁힘(하위 폴더의 같은 이름은 통과), 임시 폴더 안만 지우는 rm -r·Remove-Item -Recurse는 확인 없이 통과, 시험 41개
- 2026-11-14 v1.2: 자체 평가에서 나온 문제 수정. 대소문자 다른 경로 우회 차단, `python -c`·`node -e`·.NET·`find -delete`·압축 풀기 쓰기 감지, 셸로 settings.json·훅·보호 목록 수정 시 확인, 글롭 보호(`plugins/*.jar`) 오탐 축소, 시험이 실제 기록 파일을 더럽히지 않게 함, `install.py --check` 점검 추가, `new-project` 스킬과 표준 폴더(templates/project → skills/new-project/template), 피드백 기록(FEEDBACK_LOG.md), 스킬 폴더 이름 통일. 시험 65개 + 틀 시험
- 2026-11-14 v1.3: 보호 경로 오탐 축소. cat·tee 히어독 본문(파일 내용)과 코드 속 낱말('input', <input>)은 보호 폴더로 보지 않음. 쓰는 대상이 보호 폴더이거나 폴더 이름이 셸 낱말로 쓰이면 그대로 확인. 시험 69개
- 2026-11-14 v1.4: 사용자 승인(`.claude/approvals.json`). 확인 요청에 걸린 셸 명령을 사용자가 승인하면 같은 문자열일 때만 통과(1회·항상, 만료). AI는 승인 기록을 직접 못 씀, 하네스 설정 변경은 승인 대상 아님, 기록이 깨지면 원래대로 확인. 폴더째 지우기에 shutil.rmtree·fs.rmSync(recursive)·rimraf 추가. 시험 86개
- 2026-11-14 v1.5: `blender-motion` 스킬 추가. 스크립트 5개(bbpose 자세 계산, inspect_model 모델·기본 자세·정점 점검, make_motion 생성·수치 검사·렌더, pose_check 바닥 뚫림·몸 이동·발 끌림·끊김, blender_preview 정면·옆·위 렌더), 규칙 문서 3개(좌표·부호·덮어쓰기, 동작 설계 사람형·네발, MythicMobs 연결·Template 주의), 설계 예시. 원본 .bbmodel 보호(복사본에만 쓰기, 기존 동작 이름 겹치면 거부). 스킬만 보고 새 모델(엔더 망치머리) 동작을 만드는 시험을 한 번 돌려 나온 문제를 반영. 시험 25개(`tests/test_blender_motion.py`)
- 2026-11-14 v1.5.1: `blender-motion` 문서 정정. 해골 계열은 공격 동작이 덮어쓰기지만 기본 자세가 0 이라 REST_FROM 불필요(이전 문서의 '더하기 방식'은 틀림), 비틀기는 상체로(몸 전체를 돌리면 디딘 발이 미끄러짐). 수치 검사로 해골 3종 동작 6개를 고치며 확인
- 2026-11-14 v1.6: `mob-modeling` 스킬 추가. 조사(오픈소스 도구·제작 기준·ModelEngine 제한·자동화와 AI·보유 모델 67종 수치) 결론: 기존 모델과 새 팩이 따로 노는 원인은 해상도가 아니라 명암·테두리·큐브 밀도, 소수 모델의 밀도 이탈. 스크립트 9개(lint 엔진 규칙·아트 수치 검사, metrics, lineup 같은 축척·마인크래프트 엔티티 조명 라인업, density_fix, reshade 원래 색 유지 다시 칠하기, kitbash 부품 덧붙이기·칠하기, make_detail 설계 파일 실행기, bbtex, skilldeps), 문서 4개, 아트 기준 기본값. 실제 모델로 시험: 사당의 망령 큐브 8→39 보강(2차), 시체 먹는 개미 밀도 56.5→16 px/블록, 잭 오 랜턴 2배 격자+명암. 색 계단 방식이 상징색(호박 주황)을 바꾸는 문제를 찾아 원래 색 유지(adjust)를 기본으로. 시험 6개(`tests/test_mob_modeling.py`)
