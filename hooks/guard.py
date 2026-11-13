"""PreToolUse 훅: 원본 보호(H1), 위험 명령 확인(H2), 읽기 전용 모드(H3), 하네스 자기 보호.

입력: Claude Code가 stdin으로 주는 JSON (tool_name, tool_input, cwd).
출력: 막거나 물어볼 때만 hookSpecificOutput JSON을 stdout에 쓴다. 그 밖에는 아무것도 쓰지 않고 통과.
훅 자체가 실패하면 작업을 막지 않도록 조용히 통과한다(오류는 로그에만 남김).
"""
import fnmatch
import json
import os
import re
import sys
import time

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
HOME = os.path.expanduser("~")
HARNESS_DIR = os.path.join(HOME, ".claude", "hooks", "local-harness")
LOG_PATH = os.path.join(HOME, ".claude", "local-harness-log", "events.jsonl")

# H2: 언제나 사용자에게 먼저 묻는 명령
DANGEROUS = [
    (r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b", "폴더째 지우는 rm -r"),
    (r"\bRemove-Item\b[^|;]*-Recurse", "폴더째 지우는 Remove-Item -Recurse"),
    (r"\b(rd|rmdir)\s+/s\b", "폴더째 지우는 rd /s"),
    (r"\bdel\s+(/[a-zA-Z]\s+)*/s\b", "하위까지 지우는 del /s"),
    (r"\bgit\s+reset\s+--hard\b", "커밋하지 않은 변경을 버리는 git reset --hard"),
    (r"\bgit\s+push\b[^|;&]*(--force\b|--force-with-lease\b|\s-f\b)", "원격 기록을 덮어쓰는 git push --force"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "추적하지 않는 파일을 지우는 git clean -f"),
    (r"\bgit\s+checkout\s+(--\s+)?\.(\s|$)", "모든 변경을 버리는 git checkout ."),
    (r"\bgit\s+restore\s+(--\S+\s+)*\.(\s|$)", "모든 변경을 버리는 git restore ."),
    (r"\bformat(\.com)?\s+[a-zA-Z]:", "드라이브 포맷"),
]

# 셸 명령이 파일을 바꾸는지 대략 판단하는 패턴 (H1·H3에서 사용)
MUTATING = re.compile(
    r"(\brm\b|\bdel\b|\berase\b|\brd\b|\brmdir\b|\bmv\b|\bcp\b|\bmove\b|\bcopy\b|\bren\b|\brename\b"
    r"|\bRemove-Item\b|\bMove-Item\b|\bCopy-Item\b|\bRename-Item\b|\bSet-Content\b|\bAdd-Content\b"
    r"|\bOut-File\b|\bNew-Item\b|\bClear-Content\b|\bsed\s+-i\b|\btruncate\b|\btouch\b|\bmkdir\b"
    r"|\bgit\s+(commit|checkout|reset|restore|clean|stash|merge|rebase|pull|apply|rm|mv)\b"
    r"|\b(npm|pnpm|yarn|pip)\s+(install|uninstall|add|remove)\b|\btee\b|(^|[^0-9&>])>>?(?!&))",
    re.IGNORECASE,
)


def read_input():
    raw = sys.stdin.buffer.read()
    return json.loads(raw.decode("utf-8-sig") or "{}")


def emit(decision, reason):
    out = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": "[로컬 하네스] " + reason,
    }}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))


def log(event):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        event["time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def norm(p):
    return os.path.normcase(os.path.abspath(p)).replace("\\", "/")


def find_root(start):
    """start에서 위로 올라가며 .claude/protected.txt 또는 .claude/READONLY가 있는 폴더를 찾는다. 홈과 드라이브 루트에서 멈춘다."""
    cur = os.path.abspath(start)
    home = norm(HOME)
    while True:
        claude_dir = os.path.join(cur, ".claude")
        if norm(cur) != home and (
            os.path.isfile(os.path.join(claude_dir, "protected.txt"))
            or os.path.isfile(os.path.join(claude_dir, "READONLY"))
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur or norm(cur) == home:
            return None
        cur = parent


def read_patterns(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln.strip().replace("\\", "/") for ln in f]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def rel_to(root, path):
    rel = os.path.relpath(os.path.abspath(path), root).replace("\\", "/")
    return None if rel.startswith("../") or rel == ".." else rel


def matches(rel, pattern):
    pat = pattern[2:] if pattern.startswith("./") else pattern
    if pat.endswith("/"):
        return rel == pat[:-1] or rel.startswith(pat)
    if fnmatch.fnmatch(rel, pat):
        return True
    # 폴더 이름만 적은 경우(예: input) 그 아래 전부
    return "/" not in pat and not any(c in pat for c in "*?[") and rel.startswith(pat + "/")


def literal_prefix(pattern):
    """'인계용/*.zip' -> '인계용/' 처럼 글롭 문자 앞까지. 셸 명령 안에서 찾는 데 쓴다."""
    cut = len(pattern)
    for i, c in enumerate(pattern):
        if c in "*?[":
            cut = i
            break
    return pattern[:cut].strip()


def check_edit(tool_input, root, cwd):
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)

    # 하네스 자기 보호: 훅이나 설정을 고쳐 가드를 끄는 것을 막지 않고 묻는다
    n = norm(path)
    if n.startswith(norm(HARNESS_DIR) + "/") or n == norm(os.path.join(HOME, ".claude", "settings.json")):
        return ("ask", f"하네스 훅이나 전역 설정을 고치려 합니다: {path}")

    if not root:
        return None
    rel = rel_to(root, path)
    if rel is None:
        return None
    if rel.startswith(".claude/") and rel.split("/")[1] in ("protected.txt", "READONLY"):
        return ("ask", f"하네스 보호 설정 파일을 고치려 합니다: {rel}")

    for pat in read_patterns(os.path.join(root, ".claude", "protected.txt")):
        if matches(rel, pat):
            return ("deny", f"보호된 원본입니다({pat}). 복사본을 만들어 작업하세요: {rel}")

    readonly = os.path.join(root, ".claude", "READONLY")
    if os.path.isfile(readonly):
        allowed = read_patterns(readonly)
        if not any(matches(rel, pat) for pat in allowed):
            hint = f" 쓸 수 있는 곳: {', '.join(allowed)}" if allowed else ""
            return ("deny", f"읽기 전용 모드입니다(.claude/READONLY). 파일을 고치지 마세요: {rel}.{hint}")
    return None


def check_shell(command, root):
    for pattern, label in DANGEROUS:
        if re.search(pattern, command, re.IGNORECASE):
            return ("ask", f"{label} 명령입니다. 실행해도 되는지 확인이 필요합니다.")

    if not root or not MUTATING.search(command):
        return None
    cmd = command.replace("\\", "/")
    for pat in read_patterns(os.path.join(root, ".claude", "protected.txt")):
        prefix = literal_prefix(pat)
        if prefix and prefix in cmd:
            return ("ask", f"보호된 원본({pat})을 건드릴 수 있는 명령입니다. 원본을 바꾸지 않는지 확인이 필요합니다.")
    if os.path.isfile(os.path.join(root, ".claude", "READONLY")):
        return ("ask", "읽기 전용 모드인데 파일을 바꿀 수 있는 명령입니다. 확인이 필요합니다.")
    return None


def main():
    data = read_input()
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    root = find_root(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)

    if tool in EDIT_TOOLS:
        result = check_edit(tool_input, root, cwd)
    elif tool in SHELL_TOOLS:
        result = check_shell(tool_input.get("command", ""), root)
    else:
        result = None

    if result:
        decision, reason = result
        log({"tool": tool, "decision": decision, "reason": reason, "cwd": cwd})
        emit(decision, reason)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅 오류로 작업 전체가 멈추지 않게 한다
        log({"error": repr(e)})
    sys.exit(0)
