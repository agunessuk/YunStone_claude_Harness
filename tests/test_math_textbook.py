"""math-textbook 스킬 스크립트 시험 (표준 라이브러리만). 실행: python tests/test_math_textbook.py

붙잡아 두는 규칙:
- pdf_fonts: 본문·압축(FlateDecode) 객체 스트림의 /BaseFont 를 모두 찾고, 하위 집합 접두어·#20 이스케이프를 풂.
  KaTeX 허용 목록 밖(굵은 수식)·금지 글꼴(Times New Roman)이면 실패, PDF 가 아니면 끝 코드 2
- jsx_lint: BOM 없음·let/const·화살표·템플릿 문자열은 오류, 문자열·주석·정규식 안 글자는 문법 오류로 안 봄,
  수식 기호가 든 문자열은 주의, 안내 문장 부호(· — …)는 주의 아님
- 스킬 문서: SKILL.md 머리말 name 과 본문이 가리키는 references·scripts 파일이 실제로 있음
"""
import io
import os
import re
import sys
import tempfile
import zlib
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "skills", "math-textbook")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.dont_write_bytecode = True
import jsx_lint  # noqa: E402
import pdf_fonts  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TMP = tempfile.mkdtemp()
fails = 0


def ok(name, cond, detail=""):
    global fails
    print(("[OK ] " if cond else "[FAIL] ") + name + ("" if cond else f"  → {detail}"))
    if not cond:
        fails += 1


def make_pdf(path, plain_fonts, packed_fonts):
    """plain_fonts 는 본문 객체로, packed_fonts 는 FlateDecode 객체 스트림 안에 넣은 작은 PDF."""
    objs = [b"%PDF-1.7\n"]
    for i, f in enumerate(plain_fonts, 1):
        objs.append(b"%d 0 obj\n<< /Type /Font /Subtype /TrueType /BaseFont /" % i + f.encode("latin-1") + b" >>\nendobj\n")
    inner = b" ".join(b"<< /Type /Font /BaseFont /" + f.encode("latin-1") + b" >>" for f in packed_fonts)
    z = zlib.compress(inner)
    n = len(plain_fonts) + 1
    objs.append(b"%d 0 obj\n<< /Type /ObjStm /Filter /FlateDecode /Length %d >>\nstream\n" % (n, len(z)) + z + b"\nendstream\nendobj\n")
    objs.append(b"trailer\n<< >>\n%%EOF\n")
    with open(path, "wb") as fh:
        fh.write(b"".join(objs))
    return path


def run_main(mod, args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mod.main(args)
    return code, buf.getvalue()


# ---------------- pdf_fonts
pdf = make_pdf(os.path.join(TMP, "a.pdf"),
               ["ABCDEF+KaTeX_Main-Regular", "AppleSDGothicNeoR00", "Malgun#20Gothic"],
               ["QWERTY+KaTeX_Math-Italic", "KaTeX_Size1-Regular"])
names = pdf_fonts.font_names(pdf)
ok("본문 글꼴 찾음(하위 집합 접두어 뗌)", "KaTeX_Main-Regular" in names and "AppleSDGothicNeoR00" in names, names)
ok("압축 객체 스트림 안 글꼴도 찾음", "KaTeX_Math-Italic" in names and "KaTeX_Size1-Regular" in names, names)
ok("#20 이스케이프를 풂", "Malgun Gothic" in names, names)
ok("--subset 이면 접두어 유지", "ABCDEF+KaTeX_Main-Regular" in pdf_fonts.font_names(pdf, keep_subset=True))
allow = ["--family", "KaTeX_", "--allow", "KaTeX_Main-Regular", "KaTeX_Math-Italic", "KaTeX_Size1-Regular"]
code, _ = run_main(pdf_fonts, [pdf] + allow)
ok("허용 글꼴만이면 통과(0)", code == 0, code)

bad = make_pdf(os.path.join(TMP, "b.pdf"), ["KaTeX_Main-Regular", "KaTeX_Main-Bold", "TimesNewRomanPSMT"], ["KaTeX_Math-Italic"])
code, out = run_main(pdf_fonts, [bad] + allow)
ok("굵은 수식 글꼴이 섞이면 실패(1)", code == 1 and "KaTeX_Main-Bold" in out, out)
code, out = run_main(pdf_fonts, [bad, "--forbid", "Times New Roman"])
ok("금지 글꼴은 공백·대소문자 무시로 잡음", code == 1 and "TimesNewRomanPSMT" in out, out)

notpdf = os.path.join(TMP, "x.pdf")
with open(notpdf, "wb") as fh:
    fh.write(b"hello")
code, _ = run_main(pdf_fonts, [notpdf])
ok("PDF 가 아니면 끝 코드 2", code == 2, code)


# ---------------- jsx_lint
def jsx(name, text, bom=True):
    p = os.path.join(TMP, name)
    with open(p, "wb") as fh:
        fh.write((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return p


def kinds(path):
    return [(k, m) for k, _n, m in jsx_lint.lint_file(path)]


clean = jsx("clean.jsx", "var a = [1, 2];\n// let x = 1; => 주석은 무시\nvar s = 'const y = 2; a => b';\nvar r = /=>|`/g;\nvar d = 10 / 2 / 5;\n"
                         "var msg = '안내 · 쪽 — 끝 …';\nfunction f(x) { return x / 2; }\n")
ok("주석·문자열·정규식·나눗셈 안 글자는 오류 아님", not [k for k in kinds(clean) if k[0] == "오류"], kinds(clean))
ok("안내 문장 부호(· — …)는 주의 아님", not kinds(clean), kinds(clean))

nobom = jsx("nobom.jsx", "var a = 1;\n", bom=False)
ok("BOM 없으면 오류", any(k[0] == "오류" and "BOM" in k[1] for k in kinds(nobom)), kinds(nobom))

es6 = jsx("es6.jsx", "let a = 1;\nconst b = 2;\nvar f = (x) => x;\nvar t = `x${a}`;\n")
msgs = kinds(es6)
ok("let/const 오류", sum(1 for k, m in msgs if "let/const" in m) == 2, msgs)
ok("화살표 함수 오류", any("화살표" in m for _k, m in msgs), msgs)
ok("템플릿 문자열 오류", any("템플릿" in m for _k, m in msgs), msgs)

warn = jsx("warn.jsx", "var o = JSON.parse(s);\narr.forEach(function (x) {});\nvar m = '−①';\n")
w = kinds(warn)
ok("JSON·forEach 는 주의", any("JSON" in m for _k, m in w) and any("고차" in m for _k, m in w), w)
ok("문자열 속 수식 기호(−, ①)는 주의", any("U+2212" in m and "U+2460" in m for _k, m in w), w)
code, _ = run_main(jsx_lint, [TMP, "--quiet"])
ok("오류 있는 폴더는 끝 코드 1", code == 1, code)
code, _ = run_main(jsx_lint, [clean])
ok("깨끗한 파일은 끝 코드 0", code == 0, code)


# ---------------- 스킬 문서
with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
    md = fh.read()
ok("SKILL.md name = math-textbook", re.search(r"^name:\s*math-textbook\s*$", md, re.M) is not None)
refs = set(re.findall(r"\(references/([^)]+)\)", md))
ok("references 링크가 모두 있음", refs and all(os.path.isfile(os.path.join(SKILL, "references", r)) for r in refs), refs)
scripts = set(re.findall(r"`((?:pdf_fonts|jsx_lint)\.py|(?:pdf_render|indesign_run)\.ps1)", md))
ok("스크립트 표의 파일이 모두 있음", len(scripts) == 4 and all(os.path.isfile(os.path.join(SKILL, "scripts", s)) for s in scripts), scripts)
for s in ("pdf_render.ps1", "indesign_run.ps1"):
    with open(os.path.join(SKILL, "scripts", s), "rb") as fh:
        ok(f"{s} UTF-8 BOM (PowerShell 5.1 한글)", fh.read(3) == b"\xef\xbb\xbf")

print("\n전부 통과" if not fails else f"\n실패 {fails}건")
sys.exit(1 if fails else 0)
