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


PATH_BOUNDARY = " \t\"'=(;|&<>,"


def path_forms(p):
    """C:/a/b 와 Git Bash식 /c/a/b 두 가지 모양 (소문자, 슬래시)."""
    p = p.replace("\\", "/").rstrip("/").lower()
    forms = [p]
    if re.match(r"^[a-z]:/", p):
        forms.append("/" + p[0] + p[2:])
    return forms


def mentions_root_path(cmd, prefix, root):
    """명령 안의 prefix가 프로젝트 맨 위 경로를 가리킬 때만 True.
    '작업/던전/서버/plugins/...'처럼 다른 폴더 아래의 같은 이름은 무시한다."""
    low = cmd.lower()
    roots = [r + "/" for r in path_forms(root)]
    pre = prefix.lower()
    # 'input/' 은 끝 슬래시 없이 폴더 자체를 가리키는 'input' 도 본다
    forms = [(pre, False)] + ([(pre.rstrip("/"), True)] if pre.endswith("/") and len(pre) > 1 else [])
    for needle, need_end in forms:
        start = 0
        while True:
            i = low.find(needle, start)
            if i < 0:
                break
            start = i + 1
            j = i + len(needle)
            if need_end and j < len(low) and low[j] not in PATH_BOUNDARY:
                continue
            before = low[:i]
            if i == 0 or before[-1] in PATH_BOUNDARY:
                return True
            if before.endswith("./") and (len(before) == 2 or before[-3] in PATH_BOUNDARY):
                return True
            if any(before.endswith(r) for r in roots):
                return True
    return False


# 임시 폴더 안만 지우는 rm -r / Remove-Item -Recurse 는 묻지 않는다
RECURSIVE_DELETE = re.compile(
    r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b|\bRemove-Item\b[^|;]*-Recurse", re.IGNORECASE)
PS_VALUE_FLAGS = {"-erroraction", "-ea", "-warningaction", "-include", "-exclude", "-filter"}


def temp_dirs():
    import tempfile
    dirs = {tempfile.gettempdir(), os.environ.get("TEMP", ""), os.environ.get("TMP", ""), "/tmp"}
    out = []
    for d in dirs:
        if d:
            out.extend(path_forms(d))
    return out


def in_temp(path, temps):
    if "$" in path or "`" in path or ".." in path.replace("\\", "/").split("/"):
        return False  # 변수·상위 폴더 이동이 섞이면 실제 위치를 알 수 없으니 묻는다
    p = path.replace("\\", "/").lower()
    return any(p.startswith(t + "/") and len(p) > len(t) + 1 for t in temps)


def delete_targets(segment):
    import shlex
    try:
        toks = shlex.split(segment, posix=True)
    except ValueError:
        return None
    idx = next((i for i, t in enumerate(toks) if t.lower() in ("rm", "remove-item")), None)
    if idx is None:
        return None
    targets, skip = [], False
    for t in toks[idx + 1:]:
        if skip:
            skip = False
            continue
        tl = t.lower()
        if tl in PS_VALUE_FLAGS:
            skip = True
            continue
        if t.startswith("-"):
            continue
        targets.append(t)
    return targets


def only_temp_deletes(command):
    """명령 속 '폴더째 지우기'가 전부 임시 폴더 안의 절대 경로만 지우면 True."""
    temps = temp_dirs()
    segments = re.split(r"&&|\|\||[;|\n]", command)
    found = False
    for seg in segments:
        if not RECURSIVE_DELETE.search(seg):
            continue
        found = True
        targets = delete_targets(seg.strip())
        if not targets or not all(in_temp(t, temps) for t in targets):
            return False
    return found


def check_shell(command, root):
    for pattern, label in DANGEROUS:
        if re.search(pattern, command, re.IGNORECASE):
            if "폴더째" in label and only_temp_deletes(command):
                continue
            return ("ask", f"{label} 명령입니다. 실행해도 되는지 확인이 필요합니다.")

    if not root or not MUTATING.search(command):
        return None
    cmd = command.replace("\\", "/")
    for pat in read_patterns(os.path.join(root, ".claude", "protected.txt")):
        prefix = literal_prefix(pat)
        if prefix and mentions_root_path(cmd, prefix, root):
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
