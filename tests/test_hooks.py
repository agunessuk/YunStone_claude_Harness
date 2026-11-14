"""훅 동작 시험. 실행: python tests/test_hooks.py

임시 프로젝트 폴더를 만들고 훅에 가짜 입력을 넣어 판정을 확인한다.
막혀야 할 것은 막히고, 막히면 안 되는 것은 통과하는지 둘 다 본다.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "hooks", "guard.py")
RESTORE = os.path.join(HERE, "..", "hooks", "session_restore.py")


FAKE_HOME = tempfile.mkdtemp(prefix="harness-home-")  # 시험 기록이 실제 events.jsonl에 섞이지 않게


def run(script, payload, project):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project, USERPROFILE=FAKE_HOME, HOME=FAKE_HOME)
    p = subprocess.run([sys.executable, script], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, env=env, timeout=20)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    out = p.stdout.decode("utf-8").strip()
    return json.loads(out) if out else None


def decision(project, tool, tool_input):
    res = run(GUARD, {"tool_name": tool, "tool_input": tool_input, "cwd": project}, project)
    return res["hookSpecificOutput"]["permissionDecision"] if res else "pass"


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    failures = []

    def expect(name, got, want):
        mark = "OK " if got == want else "FAIL"
        print(f"[{mark}] {name}: {got} (기대 {want})")
        if got != want:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        proj = os.path.join(tmp, "한글 프로젝트")
        write(os.path.join(proj, ".claude", "protected.txt"), "# 원본\ninput/\n인계용/*.zip\n원본.pdf\n")
        write(os.path.join(proj, "input", "a.txt"), "x")

        p = lambda *xs: os.path.join(proj, *xs)
        # H1 원본 보호: 파일 도구
        expect("보호 폴더 안 파일 수정", decision(proj, "Edit", {"file_path": p("input", "a.txt")}), "deny")
        expect("보호 ZIP 덮어쓰기", decision(proj, "Write", {"file_path": p("인계용", "pack.zip")}), "deny")
        expect("보호 파일 이름 일치", decision(proj, "Write", {"file_path": p("원본.pdf")}), "deny")
        expect("보호 아닌 파일 수정", decision(proj, "Write", {"file_path": p("work", "a.txt")}), "pass")
        expect("보호 폴더 밖 같은 이름", decision(proj, "Write", {"file_path": p("work", "input", "a.txt")}), "pass")
        expect("인계용 폴더의 md는 통과", decision(proj, "Write", {"file_path": p("인계용", "README.md")}), "pass")
        expect("보호 목록 파일 수정은 확인", decision(proj, "Edit", {"file_path": p(".claude", "protected.txt")}), "ask")

        # H1 원본 보호: 셸
        expect("보호 폴더 rm", decision(proj, "Bash", {"command": "rm input/a.txt"}), "ask")
        expect("보호 폴더 읽기", decision(proj, "Bash", {"command": "cat input/a.txt"}), "pass")
        expect("보호 ZIP 목록 보기", decision(proj, "PowerShell", {"command": "Get-ChildItem 인계용"}), "pass")
        expect("보호 ZIP 이동", decision(proj, "PowerShell", {"command": "Move-Item 인계용\\pack.zip old\\"}), "ask")
        # 프로젝트 맨 위 경로만 보호: 다른 폴더 아래 같은 이름은 통과
        expect("하위 폴더의 같은 이름에 복사", decision(proj, "Bash", {"command": "mkdir -p 작업/서버/input/x && cp a.yml 작업/서버/input/x/"}), "pass")
        expect("./ 로 보호 폴더 지정", decision(proj, "Bash", {"command": "mv ./input/a.txt b.txt"}), "ask")
        expect("절대 경로로 보호 폴더 지정", decision(proj, "Bash", {"command": f'rm "{p("input", "a.txt")}"'}), "ask")
        expect("따옴표 안 보호 폴더", decision(proj, "Bash", {"command": 'cp x.txt "input/a.txt"'}), "ask")
        # 오탐: 코드·글 내용 속 같은 단어 (2026-11-14 워크벤치 실행에서 발견)
        expect("히어독 본문 속 단어는 통과", decision(proj, "Bash", {"command":
            "cat > src/app.js <<'EOF'\nconst el = document.querySelector('input');\nEOF"}), "pass")
        expect("python -c 코드 속 단어는 통과", decision(proj, "Bash", {"command":
            "python -c \"open('src/a.html','w').write('<input type=text>')\""}), "pass")
        expect("히어독이어도 대상이 보호 폴더면 확인", decision(proj, "Bash", {"command":
            "cat > input/a.txt <<'EOF'\nhello\nEOF"}), "ask")
        expect("따옴표 폴더 이름 단독은 확인", decision(proj, "Bash", {"command": 'rm -f "input"'}), "ask")

        # 우회 시도 (2026-11-14 평가에서 나온 것)
        expect("대소문자 다른 경로로 수정", decision(proj, "Edit", {"file_path": p("Input", "a.txt")}), "deny")
        expect("대소문자 다른 ZIP", decision(proj, "Write", {"file_path": p("인계용", "PACK.ZIP")}), "deny")
        expect("cd 로 들어가서 rm", decision(proj, "Bash", {"command": "cd input && rm a.txt"}), "ask")
        expect("Set-Location 뒤 Remove-Item", decision(proj, "PowerShell", {"command": "Set-Location input; Remove-Item a.txt"}), "ask")
        expect("python -c 로 쓰기", decision(proj, "Bash", {"command": "python -c \"open('input/a.txt','w').write('x')\""}), "ask")
        expect("python 히어독으로 쓰기", decision(proj, "Bash", {"command": "python - <<'EOF'\nopen('input/a.txt','w')\nEOF"}), "ask")
        expect("node -e 로 쓰기", decision(proj, "Bash", {"command": "node -e \"require('fs').writeFileSync('input/a.txt','x')\""}), "ask")
        expect(".NET WriteAllText", decision(proj, "PowerShell", {"command": "[IO.File]::WriteAllText('input/a.txt','x')"}), "ask")
        expect("find -delete", decision(proj, "Bash", {"command": "find input -name '*.txt' -delete"}), "ask")
        expect("압축을 보호 폴더에 풀기", decision(proj, "PowerShell", {"command": "Expand-Archive x.zip -DestinationPath input"}), "ask")
        expect("python 스크립트로 원본 읽기는 통과", decision(proj, "Bash", {"command": "python tools/count.py input/a.txt"}), "pass")
        expect("python -c 로 원본 읽기만", decision(proj, "Bash", {"command": "python -c \"print(open('input/a.txt').read())\""}), "pass")

        # 글롭 보호의 오탐 (plugins/*.jar 보호 중 jar가 아닌 곳)
        write(os.path.join(proj, ".claude", "protected.txt"), "# 원본\ninput/\n인계용/*.zip\n원본.pdf\nplugins/*.jar\n")
        expect("글롭 보호: 다른 하위 폴더 만들기는 통과", decision(proj, "Bash", {"command": "mkdir -p plugins/MythicMobs/Packs/new"}), "pass")
        expect("글롭 보호: 설정 파일 복사는 통과", decision(proj, "Bash", {"command": "cp a.yml plugins/MythicMobs/config.yml"}), "pass")
        expect("글롭 보호: jar 덮어쓰기는 확인", decision(proj, "Bash", {"command": "cp new.jar plugins/Mythic.jar"}), "ask")
        expect("글롭 보호: 대문자 JAR 도 확인", decision(proj, "Bash", {"command": "rm plugins/Mythic.JAR"}), "ask")
        expect("글롭 보호: 와일드카드 삭제는 확인", decision(proj, "Bash", {"command": "rm plugins/*"}), "ask")
        expect("글롭 보호: 폴더 자체 이동은 확인", decision(proj, "Bash", {"command": "mv plugins plugins_old"}), "ask")
        expect("글롭 보호: cd 로 들어가서 jar 삭제는 확인", decision(proj, "Bash", {"command": "cd plugins && rm a.jar"}), "ask")

        # 하네스 자기 보호: 셸
        expect("셸로 settings.json 덮어쓰기", decision(proj, "Bash", {"command": "echo {} > ~/.claude/settings.json"}), "ask")
        expect("PowerShell로 settings.json 쓰기", decision(proj, "PowerShell", {"command": "Set-Content $env:USERPROFILE\\.claude\\settings.json '{}'"}), "ask")
        expect("셸로 훅 파일 지우기", decision(proj, "Bash", {"command": "rm ~/.claude/hooks/local-harness/guard.py"}), "ask")
        expect("셸로 보호 목록 비우기", decision(proj, "Bash", {"command": "echo > .claude/protected.txt"}), "ask")
        expect("settings.json 읽기는 통과", decision(proj, "Bash", {"command": "cat ~/.claude/settings.json"}), "pass")

        # 임시 폴더 안만 지우는 폴더 삭제는 통과
        t = tempfile.gettempdir()
        expect("임시 폴더 안 rm -rf", decision(proj, "Bash", {"command": f'rm -rf "{os.path.join(t, "claude", "scratch", "x")}"'}), "pass")
        expect("임시 폴더 안 Remove-Item", decision(proj, "PowerShell", {"command": f'Remove-Item -Recurse -Force "{os.path.join(t, "zz")}"'}), "pass")
        expect("임시 폴더 자체 삭제는 확인", decision(proj, "Bash", {"command": f'rm -rf "{t}"'}), "ask")
        expect("임시+다른 폴더 같이 삭제는 확인", decision(proj, "Bash", {"command": f'rm -rf "{os.path.join(t, "a")}" build'}), "ask")
        expect("임시 폴더 안이라도 보호 원본 삭제는 확인", decision(proj, "Bash", {"command": f'rm -rf "{p("input")}"'}), "ask")
        expect("변수 경로 삭제는 확인", decision(proj, "Bash", {"command": 'rm -rf "$S/x"'}), "ask")
        expect("상위 이동 섞인 삭제는 확인", decision(proj, "Bash", {"command": f'rm -rf "{t}/a/../../x"'}), "ask")
        expect("임시 삭제 뒤 다른 위험 명령은 확인", decision(proj, "Bash", {"command": f'rm -rf "{os.path.join(t, "a")}" && git reset --hard'}), "ask")

        # H2 위험 명령 (보호 목록과 무관)
        expect("rm -rf", decision(proj, "Bash", {"command": "rm -rf build"}), "ask")
        expect("Remove-Item -Recurse", decision(proj, "PowerShell", {"command": "Remove-Item -Recurse -Force dist"}), "ask")
        expect("git reset --hard", decision(proj, "Bash", {"command": "git reset --hard HEAD~1"}), "ask")
        expect("git push -f", decision(proj, "Bash", {"command": "git push -f origin main"}), "ask")
        expect("git push 보통", decision(proj, "Bash", {"command": "git push origin main"}), "pass")
        expect("rm 파일 하나", decision(proj, "Bash", {"command": "rm build/tmp.log"}), "pass")
        expect("ls", decision(proj, "Bash", {"command": "ls -la"}), "pass")

        # H3 읽기 전용 모드
        write(p(".claude", "READONLY"), "review/claude/\n")
        expect("읽기 전용: 소스 수정", decision(proj, "Edit", {"file_path": p("src", "a.java")}), "deny")
        expect("읽기 전용: 허용 폴더에 보고서", decision(proj, "Write", {"file_path": p("review", "claude", "r.md")}), "pass")
        expect("읽기 전용: 셸 쓰기", decision(proj, "Bash", {"command": "echo hi > src/a.txt"}), "ask")
        expect("읽기 전용: 셸 읽기", decision(proj, "Bash", {"command": "grep -r foo src 2>&1"}), "pass")
        os.remove(p(".claude", "READONLY"))
        expect("읽기 전용 해제 후 소스 수정", decision(proj, "Edit", {"file_path": p("src", "a.java")}), "pass")

        # 하네스 설정이 없는 폴더
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        expect("설정 없는 폴더 수정", decision(plain, "Write", {"file_path": os.path.join(plain, "a.txt")}), "pass")
        expect("설정 없는 폴더 rm -rf", decision(plain, "Bash", {"command": "rm -rf x"}), "ask")

        # 하위 폴더에서 실행해도 루트를 찾는다
        sub = p("src", "deep")
        os.makedirs(sub)
        res = run(GUARD, {"tool_name": "Edit", "tool_input": {"file_path": p("input", "a.txt")}, "cwd": sub}, sub)
        expect("하위 폴더에서도 보호", res["hookSpecificOutput"]["permissionDecision"] if res else "pass", "deny")

        # H4 상태 복원
        expect("기록 없으면 출력 없음", run(RESTORE, {"source": "startup", "cwd": plain}, plain), None)
        write(p("PROGRESS.md"), "# 진행\n## 다음 할 일\n- 창술사 이펙트\n")
        res = run(RESTORE, {"source": "compact", "cwd": proj}, proj)
        ctx = res["hookSpecificOutput"]["additionalContext"] if res else ""
        expect("압축 뒤 PROGRESS 주입", "창술사 이펙트" in ctx and "압축" in ctx, True)
        expect("보호 목록 안내", "인계용/*.zip" in ctx, True)

    print()
    print("전부 통과" if not failures else f"실패 {len(failures)}건: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
