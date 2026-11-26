"""PDF에 박힌 글꼴 이름 목록을 뽑고, 수식 글꼴 규칙을 검사한다 (표준 라이브러리만 사용).

  python pdf_fonts.py 단원.pdf
  python pdf_fonts.py 단원.pdf --family KaTeX_ --allow KaTeX_Main-Regular KaTeX_Math-Italic KaTeX_Size1-Regular
  python pdf_fonts.py 단원.pdf --forbid TimesNewRoman Gulim --json

  --family 접두어 + --allow 이름들 : 그 접두어로 시작하는 글꼴은 allow 목록에 있어야 함 (예: KaTeX 굵은 글꼴이 섞이면 실패)
  --forbid 글자들                   : 이름에 이 글자가 들어간 글꼴이 있으면 실패 (대소문자·공백 무시)
  끝 코드: 0 통과 · 1 규칙 위반 · 2 파일 문제

원리: PDF 본문과 FlateDecode 스트림(객체 스트림 포함)을 풀어 /BaseFont /이름 을 모두 찾는다.
하위 집합 접두어(ABCDEF+)와 #20 같은 이름 이스케이프는 풀어서 보여 준다.
"""
import argparse
import json
import re
import sys
import zlib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASEFONT = re.compile(rb"/BaseFont\s*/([^\s/\[\]<>()%{}]+)")
STREAM = re.compile(rb"stream\r?\n")
SUBSET = re.compile(r"^[A-Z]{6}\+")


def _unescape(name: bytes) -> str:
    out = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), name)
    for enc in ("utf-8", "cp949", "latin-1"):
        try:
            return out.decode(enc)
        except UnicodeDecodeError:
            continue
    return out.decode("latin-1")


def _streams(data: bytes):
    """FlateDecode 로 풀리는 스트림 내용을 모두 돌려준다 (길이 값을 믿지 않고 endstream 까지)."""
    pos = 0
    while True:
        m = STREAM.search(data, pos)
        if not m:
            return
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            return
        head = data[max(0, m.start() - 400):m.start()]
        if b"FlateDecode" in head:
            raw = data[start:end]
            try:
                yield zlib.decompressobj().decompress(raw)
            except zlib.error:
                pass
        pos = end + 9


def font_names(path: str, keep_subset: bool = False):
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"%PDF"):
        raise ValueError("PDF 파일이 아닙니다")
    found = set()
    chunks = [data]
    chunks.extend(_streams(data))
    for chunk in chunks:
        for m in BASEFONT.finditer(chunk):
            name = _unescape(m.group(1))
            if not keep_subset:
                name = SUBSET.sub("", name)
            found.add(name)
    return sorted(found)


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]", "", s).lower()


def check(names, family=None, allow=None, forbid=None):
    problems = []
    if family:
        allowed = set(allow or [])
        for n in names:
            if n.startswith(family) and n not in allowed:
                problems.append(f"허용 목록 밖의 {family} 글꼴: {n}")
    for bad in forbid or []:
        for n in names:
            if _norm(bad) in _norm(n):
                problems.append(f"쓰지 말아야 할 글꼴: {n} ('{bad}')")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="PDF 글꼴 목록·수식 글꼴 검사")
    ap.add_argument("pdf")
    ap.add_argument("--family", help="검사할 글꼴 접두어 (예: KaTeX_)")
    ap.add_argument("--allow", nargs="*", default=[], help="--family 글꼴 중 허용할 정확한 이름")
    ap.add_argument("--forbid", nargs="*", default=[], help="이름에 들어가면 실패할 글자")
    ap.add_argument("--subset", action="store_true", help="ABCDEF+ 하위 집합 접두어를 그대로 보여 줌")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        names = font_names(a.pdf, keep_subset=a.subset)
    except (OSError, ValueError) as e:
        print(f"[오류] {a.pdf}: {e}")
        return 2
    problems = check(names, a.family, a.allow, a.forbid)
    if a.json:
        print(json.dumps({"fonts": names, "problems": problems}, ensure_ascii=False, indent=1))
    else:
        print(f"글꼴 {len(names)}개 — {a.pdf}")
        for n in names:
            print("  " + n)
        if a.family or a.forbid:
            print("통과" if not problems else "문제 {}건".format(len(problems)))
            for p in problems:
                print("  [문제] " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
