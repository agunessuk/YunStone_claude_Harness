"""PreToolUse 훅: 원본 보호(H1), 위험 명령 확인(H2), 읽기 전용 모드(H3), 하네스 자기 보호.

입력: Claude Code가 stdin으로 주는 JSON (tool_name, tool_input, cwd).
출력: 막거나 물어볼 때만 hookSpecificOutput JSON을 stdout에 쓴다. 그 밖에는 아무것도 쓰지 않고 통과.
훅 자체가 실패하면 작업을 막지 않도록 조용히 통과한다(오류는 로그에만 남김).
"""
import fnmatch
import hashlib
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
    (r"\bshutil\.rmtree\b", "폴더째 지우는 shutil.rmtree"),
    (r"\brmSync\([^)]*recursive\s*:\s*true", "폴더째 지우는 fs.rmSync(recursive)"),
    (r"\brimraf\b", "폴더째 지우는 rimraf"),
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
    r"|\b(npm|pnpm|yarn|pip)\s+(install|uninstall|add|remove)\b|\btee\b|(^|[^0-9&>])>>?(?!&)"
    # 셸 동사 없이 파일을 바꾸는 방법: 인라인 코드(python -c, node -e, 히어독), .NET, find, 압축 풀기, 내려받기
    r"|\bopen\([^)]*,\s*['\"][wax]|\.write(_text|_bytes)?\(|\b(write|append)File(Sync)?\("
    r"|\bos\.(remove|unlink|rename|replace|rmdir|removedirs|makedirs|mkdir|truncate)\b|\bshutil\.\w+"
    r"|\b(unlink|rm|rename|copyFile|mkdir|cp)Sync\b|\.unlink\(|\.rename\(|\.rmdir\(|\.touch\("
    r"|\[(System\.)?IO\.(File|Directory)\]::\w*(Write|Append|Delete|Move|Copy|Create|Replace)"
    r"|\s-delete\b|\bExpand-Archive\b|\bunzip\b|\btar\s+-?[a-zA-Z]*x|\b7z\s+[xe]\b|-OutFile\b|\bwget\b|\bcurl\b[^|;&]*\s-[oO]\b)",
    re.IGNORECASE,
)

# 하네스 자기 보호: 셸 명령이 이 경로를 바꾸려 하면 확인 (경로는 소문자·슬래시로 비교)
SELF_PATHS = (".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/local-harness",
              ".claude/protected.txt", ".claude/readonly", ".claude/approvals.json")

# 사용자 승인 기록. 워크벤치가 사용자 답(1회·항상)을 받아 프로젝트 .claude/ 에 쓴다. AI는 직접 못 쓴다.
APPROVALS = "approvals.json"


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


def has_glob(s):
    return any(c in s for c in "*?[")


def matches(rel, pattern):
    # Windows·Mac 파일 시스템은 대소문자를 구별하지 않으므로 비교도 구별하지 않는다(Input/a.txt 우회 방지)
    rel = rel.lower()
    pat = pattern.lower()
    pat = pat[2:] if pat.startswith("./") else pat
    if pat.endswith("/"):
        return rel == pat[:-1] or rel.startswith(pat)
    if fnmatch.fnmatchcase(rel, pat):
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
    # 승인 기록은 사람(워크벤치)만 쓴다. AI가 스스로 승인을 만들 수 없게 어디서든 차단
    if n.endswith("/.claude/" + APPROVALS):
        return ("deny", "승인 기록(.claude/approvals.json)은 사용자와 워크벤치만 씁니다. AI가 직접 고칠 수 없습니다.")

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


WORD_END = " \t\n;|&)"
HEREDOC = re.compile(r"(<<-?\s*(['\"]?)(\w+)\2[^\n]*\n)(.*?)(\n\3[ \t]*(?:\n|$))", re.S)


def strip_heredoc_bodies(cmd):
    """cat·tee로 파일에 쓰는 히어독의 본문은 파일 내용이지 경로가 아니므로 검사에서 뺀다.
    대상(cat > input/a.txt <<EOF)은 첫 줄에 남는다. python·node·bash로 넘기는 본문은 코드라서 그대로 검사한다."""
    def repl(m):
        line_start = max(cmd.rfind("\n", 0, m.start()), cmd.rfind(";", 0, m.start()),
                         cmd.rfind("&&", 0, m.start())) + 1
        if re.match(r"\s*(cat|tee)\b", cmd[line_start:m.start()].lstrip("& ")):
            return m.group(1) + m.group(5).lstrip("\n")
        return m.group(0)
    return HEREDOC.sub(repl, cmd)


def _standalone_word(low, i, j):
    """low[i:j]가 셸 낱말 하나로 서 있는가: 앞뒤가 공백·명령 구분자, 또는 그 낱말만 감싼 따옴표."""
    pre = low[i - 1] if i > 0 else " "
    post = low[j] if j < len(low) else " "
    if pre in "\"'":
        if post != pre:
            return False
        pre = low[i - 2] if i > 1 else " "
        post = low[j + 1] if j + 1 < len(low) else " "
    return (pre in " \t\n;|&(=" or i == 0) and (post in WORD_END)


def root_path_hits(cmd, prefix, root):
    """명령 안에서 prefix가 프로젝트 맨 위 경로를 가리키는 곳마다, 그 자리의 경로 토큰(프로젝트 기준, 소문자)을 낸다.
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
            if need_end and not any(before.endswith(r) for r in roots) and not _standalone_word(low, i, j):
                # 슬래시 없는 폴더 이름(input)은 셸 낱말로 따로 설 때만 경로로 본다.
                # 코드 속 querySelector('input'), <input> 같은 것은 무시 (2026-11-14 오탐)
                continue
            if (i == 0 or before[-1] in PATH_BOUNDARY
                    or (before.endswith("./") and (len(before) == 2 or before[-3] in PATH_BOUNDARY))
                    or any(before.endswith(r) for r in roots)):
                k = i
                while k < len(low) and low[k] not in PATH_BOUNDARY:
                    k += 1
                yield low[i:k]


def mentions_root_path(cmd, prefix, root):
    return next(root_path_hits(cmd, prefix, root), None) is not None


def touches_pattern(cmd, pat, root):
    """셸 명령이 보호 패턴을 건드릴 수 있으면 True.
    글롭이 없는 패턴(input/, 원본.pdf)은 이름이 나오기만 하면 True.
    글롭 패턴(plugins/*.jar)은 맞는 파일, 폴더 자체(cd·mv plugins), 와일드카드(plugins/*)일 때만 True.
    plugins/MythicMobs/config.yml 처럼 패턴에 안 맞는 다른 파일은 통과시켜 확인 창 오탐을 줄인다."""
    prefix = literal_prefix(pat)
    if not prefix:
        return False
    if not has_glob(pat):
        return mentions_root_path(cmd, prefix, root)
    pat_l = pat.lower()
    pat_l = pat_l[2:] if pat_l.startswith("./") else pat_l
    dir_part = prefix.lower().rstrip("/")
    for tok in root_path_hits(cmd, prefix, root):
        tok = tok[2:] if tok.startswith("./") else tok
        for r in path_forms(root):
            if tok.startswith(r + "/"):
                tok = tok[len(r) + 1:]
        if tok.rstrip("/") == dir_part or has_glob(tok) or fnmatch.fnmatchcase(tok, pat_l):
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

    if not MUTATING.search(command):
        return None
    cmd = strip_heredoc_bodies(command).replace("\\", "/")
    low = cmd.lower()
    for sp in SELF_PATHS:
        if sp in low:
            return ("ask", f"하네스 설정·훅·보호 목록({sp})을 바꿀 수 있는 명령입니다. 확인이 필요합니다.")

    if not root:
        return None
    for pat in read_patterns(os.path.join(root, ".claude", "protected.txt")):
        if touches_pattern(cmd, pat, root):
            return ("ask", f"보호된 원본({pat})을 건드릴 수 있는 명령입니다. 원본을 바꾸지 않는지 확인이 필요합니다.")
    if os.path.isfile(os.path.join(root, ".claude", "READONLY")):
        return ("ask", "읽기 전용 모드인데 파일을 바꿀 수 있는 명령입니다. 확인이 필요합니다.")
    return None


def command_hash(command):
    return hashlib.sha256(command.strip().replace("\r\n", "\n").encode("utf-8")).hexdigest()


def touches_self(command):
    low = strip_heredoc_bodies(command).replace("\\", "/").lower()
    return any(sp in low for sp in SELF_PATHS)


def consume_approval(root, command):
    """사용자가 미리 승인한 바로 그 명령이면 승인 항목을 돌려주고 사용 횟수를 올린다 (1회 승인은 한 번 쓰면 끝).
    명령 문자열이 한 글자라도 다르면, 만료됐으면, 파일이 깨졌거나 기록을 못 남기면 None → 원래대로 확인 요청."""
    if not root:
        return None
    path = os.path.join(root, ".claude", APPROVALS)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        items = data.get("approvals", [])
    except (OSError, ValueError, AttributeError):
        return None
    h, now = command_hash(command), time.time()
    for a in items:
        if not isinstance(a, dict) or a.get("sha256") != h:
            continue
        if a.get("expires") and now > float(a["expires"]):
            continue
        if a.get("once", True) and int(a.get("used", 0)) >= 1:
            continue
        a["used"] = int(a.get("used", 0)) + 1
        a["last_used"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except OSError:
            return None  # 사용 기록을 못 남기면 1회 승인이 여러 번 쓰일 수 있으니 통과시키지 않는다
        return a
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
        command = tool_input.get("command", "")
        result = check_shell(command, root)
        # 확인 요청 대상이라도 사용자가 이 명령을 미리 승인했으면 통과 (하네스 설정 변경은 승인으로 못 엶)
        if result and result[0] == "ask" and not touches_self(command):
            a = consume_approval(root, command)
            if a:
                kind = "1회" if a.get("once", True) else "항상"
                log({"tool": tool, "decision": "approved", "reason": f"사용자 승인({kind}) 사용: {result[1]}",
                     "card": a.get("card"), "cwd": cwd})
                result = None
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
