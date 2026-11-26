"""인디자인 ExtendScript(.jsx · .jsxinc) 정적 검사 — ES3 에 없는 문법과 UTF-8 BOM 누락을 찾는다 (표준 라이브러리만).

  python jsx_lint.py 80_도구/인디자인스크립트
  python jsx_lint.py 조립.jsx 공통.jsxinc --ps1      (.ps1 도 BOM 검사에 넣기)

  [오류] 인디자인에서 실행이 멈추는 것: BOM 없음(한글 깨짐), let/const, 화살표 함수, 템플릿 문자열, class, 펼침 연산자
  [주의] 실행은 되지만 확인할 것: JSON, 배열 고차 함수(forEach·map·filter …), trim, Object.keys,
         문자열 안의 특수 기호(①, −, ≠ … → String.fromCharCode 권장)
  끝 코드: 0 오류 없음 · 1 오류 있음

주석·문자열·정규식 안의 글자는 문법 검사에서 뺀다(간단한 토큰 분리).
"""
import argparse
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BOM = b"\xef\xbb\xbf"
ERRORS = [
    (re.compile(r"\b(let|const)\s+[A-Za-z_$\[{]"), "let/const 는 ES3 에 없음 → var"),
    (re.compile(r"=>"), "화살표 함수는 ES3 에 없음 → function () {}"),
    (re.compile(r"\bclass\s+[A-Za-z_$]"), "class 는 ES3 에 없음"),
    (re.compile(r"\.\.\.[A-Za-z_$\[]"), "펼침 연산자(...)는 ES3 에 없음"),
]
WARNS = [
    (re.compile(r"\bJSON\s*\."), "ExtendScript 에는 JSON 이 없음 (직접 만든 JSON 이 있으면 무시)"),
    (re.compile(r"\.(forEach|map|filter|reduce|some|every|find|findIndex|includes)\s*\("), "배열 고차 함수는 ES3 에 없음 → for 문 (직접 만든 함수면 무시)"),
    (re.compile(r"\.trim\s*\(\s*\)"), "String.trim 은 ES3 에 없음 → replace(/^\\s+|\\s+$/g, '')"),
    (re.compile(r"\bObject\s*\.\s*(keys|assign|entries|values)\b"), "Object.keys 등은 ES3 에 없음 → for…in"),
]
REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")


# 조판 글자로 문서에 들어가면 깨지거나 다른 글자로 바뀌기 쉬운 범위만 (안내 문장의 · — … → 같은 문장 부호는 뺌)
SPECIAL_RANGES = [
    (0x2200, 0x22FF),   # 수학 연산자 (− ≠ ≤ ∩ ⋅ …)
    (0x2460, 0x24FF),   # 원 숫자 ①
    (0x2150, 0x218F),   # 로마 숫자 Ⅱ
    (0x3000, 0x3000),   # 전각 공백
    (0xE000, 0xF8FF),   # 사용자 영역 (글꼴 전용 글리프)
    (0xFF01, 0xFF5E),   # 전각 문자 １
]


def _is_special(ch):
    o = ord(ch)
    return any(a <= o <= b for a, b in SPECIAL_RANGES)


def split_code(src):
    """(코드, 문자열 목록[(줄, 내용)]) — 주석은 지우고 문자열·정규식은 빈 따옴표로 바꾼 코드."""
    out, strings = [], []
    i, n, line = 0, len(src), 1
    last_sig = ""
    while i < n:
        c = src[i]
        nx = src[i + 1] if i + 1 < n else ""
        if c == "\n":
            line += 1
            out.append(c)
            i += 1
            continue
        if c == "/" and nx == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and nx == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            seg = src[i:j]
            line += seg.count("\n")
            out.append("\n" * seg.count("\n"))
            i = j
            continue
        if c in "'\"`":
            q, j, start_line = c, i + 1, line
            buf = []
            while j < n and src[j] != q:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == "\n":
                    if q != "`":
                        break
                    line += 1
                buf.append(src[j])
                j += 1
            strings.append((start_line, "".join(buf), q))
            out.append("``" if q == "`" else "''")
            i = j + 1
            last_sig = "'"
            continue
        if c == "/" and (last_sig in REGEX_PREV or last_sig == "" or re.search(r"\breturn\s*$", "".join(out[-12:]))):
            j, in_cls = i + 1, False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_cls = True
                elif src[j] == "]":
                    in_cls = False
                elif src[j] == "/" and not in_cls:
                    break
                j += 1
            if j < n and src[j] == "/":
                j += 1
                while j < n and src[j].isalpha():
                    j += 1
                out.append("/r/")
                i = j
                last_sig = "r"
                continue
        out.append(c)
        if not c.isspace():
            last_sig = c
        i += 1
    return "".join(out), strings


def lint_file(path, check_syntax=True):
    with open(path, "rb") as f:
        raw = f.read()
    found = []
    if not raw.startswith(BOM):
        found.append(("오류", 1, "UTF-8 BOM 없음 — 한글이 깨지거나 실행 오류 (BOM 붙여 저장)"))
    if not check_syntax:
        return found
    try:
        src = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        found.append(("오류", 1, "UTF-8 로 읽을 수 없음"))
        return found
    code, strings = split_code(src)
    for no, text in enumerate(code.split("\n"), 1):
        for rx, msg in ERRORS:
            if rx.search(text):
                found.append(("오류", no, msg))
        if "``" in text:
            found.append(("오류", no, "템플릿 문자열(`…`)은 ES3 에 없음"))
        for rx, msg in WARNS:
            if rx.search(text):
                found.append(("주의", no, msg))
    for no, text, _q in strings:
        sp = sorted({ch for ch in text if _is_special(ch)})
        if sp:
            shown = " ".join("{}(U+{:04X})".format(ch, ord(ch)) for ch in sp[:5])
            found.append(("주의", no, "문자열 안 특수 기호 " + shown + " → String.fromCharCode 권장"))
    return found


def collect(paths, with_ps1):
    exts = (".jsx", ".jsxinc") + ((".ps1",) if with_ps1 else ())
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for fn in sorted(files):
                    if fn.lower().endswith(exts):
                        yield os.path.join(root, fn)
        else:
            yield p


def main(argv=None):
    ap = argparse.ArgumentParser(description="ExtendScript ES3·BOM 검사")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--ps1", action="store_true", help=".ps1 도 BOM 검사")
    ap.add_argument("--quiet", action="store_true", help="주의는 숨기고 오류만")
    a = ap.parse_args(argv)
    n_err = n_warn = n_files = 0
    for path in collect(a.paths, a.ps1):
        n_files += 1
        results = lint_file(path, check_syntax=not path.lower().endswith(".ps1"))
        for kind, no, msg in results:
            if kind == "오류":
                n_err += 1
            else:
                n_warn += 1
                if a.quiet:
                    continue
            print(f"{path}:{no}: [{kind}] {msg}")
    print(f"파일 {n_files}개 · 오류 {n_err} · 주의 {n_warn}")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
