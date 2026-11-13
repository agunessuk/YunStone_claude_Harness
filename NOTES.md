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

## 변경 기록
- 2026-11-13 v1: 훅 2개(guard, session_restore), 스킬 8개, 전역 CLAUDE.md, 설치기
