"""모든 스킬의 기본 형식 검사 + 2026-11 추가 스킬(설계 시안·표지·내부망 웹앱·드라이브·결제 중계·데스크톱 운영) 파일 검사.

실행: python tests/test_skill_files.py
- SKILL.md 앞머리(name·description)가 있고 name이 폴더 이름과 같은지
- SKILL.md 안의 상대 링크(references/…, templates/…)가 실제 파일인지
- 표지 틀: 문구 파일이 따옴표 꼴인지, HTML이 문구 파일을 읽는지, bat이 CRLF인지
- lan_check.ps1: UTF-8 BOM(PowerShell 5.1 한글), 설정을 바꾸는 명령(Set-/New-/Remove-)이 없는지
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(REPO, "skills")
NEW = ["design-drafts", "print-cover", "lan-web-app", "google-drive-link", "payment-relay", "claude-desktop-ops"]

fails = []


def check(cond, msg):
    print(("OK  " if cond else "X   ") + msg)
    if not cond:
        fails.append(msg)


def read(p, mode="r"):
    with open(p, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


for name in sorted(os.listdir(SKILLS)):
    md = os.path.join(SKILLS, name, "SKILL.md")
    if not os.path.isfile(md):
        continue
    text = read(md)
    m = re.match(r"^---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    check(bool(m), f"{name}: 앞머리(---) 있음")
    if not m:
        continue
    head = m.group(1)
    nm = re.search(r"^name:\s*(.+)$", head, re.M)
    ds = re.search(r"^description:\s*(.+)$", head, re.M)
    check(bool(nm) and nm.group(1).strip() == name, f"{name}: name이 폴더 이름과 같음")
    check(bool(ds) and len(ds.group(1).strip()) >= 40, f"{name}: description 있음")
    for link in re.findall(r"\]\(((?:references|templates|scripts)/[^)#]+)\)", text):
        check(os.path.isfile(os.path.join(SKILLS, name, link)), f"{name}: 링크 {link} 파일 있음")

for name in NEW:
    check(os.path.isfile(os.path.join(SKILLS, name, "SKILL.md")), f"새 스킬 {name} 있음")

# 표지 틀
tpl = os.path.join(SKILLS, "print-cover", "templates")
words = read(os.path.join(tpl, "표지문구.txt"))
for key in ["반", "제목", "범위", "학원명"]:
    check(re.search(rf'^{key}\s*=\s*".*"\s*$', words, re.M) is not None, f"표지문구.txt: {key} = \"…\" 꼴")
html = read(os.path.join(tpl, "표지.html"))
check('src="표지문구.txt"' in html, "표지.html: 문구 파일을 읽음")
check("@page" in html and 'id="front"' in html and 'id="back"' in html, "표지.html: 판형·앞·뒤 쪽 있음")
bat = read(os.path.join(tpl, "표지_PDF_만들기.bat"), "rb")
check(b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b""), "표지_PDF_만들기.bat: CRLF 줄바꿈")
check(b"--print-to-pdf" in bat and b"COVER_NOPAUSE" in bat, "표지_PDF_만들기.bat: headless PDF, 시험용 멈춤 끄기")

# 내부망 점검 스크립트
ps = read(os.path.join(SKILLS, "lan-web-app", "scripts", "lan_check.ps1"), "rb")
check(ps.startswith(b"\xef\xbb\xbf"), "lan_check.ps1: UTF-8 BOM")
code = "\n".join(l for l in ps.decode("utf-8-sig").splitlines() if not l.lstrip().startswith("#"))
check(re.search(r"\b(Set|New|Remove|Enable|Disable)-Net", code) is None, "lan_check.ps1: 설정을 바꾸는 명령 없음")

print()
if fails:
    print(f"실패 {len(fails)}개")
    sys.exit(1)
print("모두 통과")
