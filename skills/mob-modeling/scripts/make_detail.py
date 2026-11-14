"""디테일 보강 실행기: 설계 파일(.py) → 복사본 .bbmodel + 검사 + 라인업 렌더 + 기존 동작 확인 렌더 + 보고표.

사용 (프로젝트 루트에서):
  python -I <스킬>/scripts/make_detail.py <설계.py> [--no-render] [--no-anims] [--root 작업/모델링]
설계 파일 (templates/detail_spec_example.py 참고):
  SRC = "원본.bbmodel"                     # 읽기만 한다
  OUT = "작업/모델링/모델/<이름>.bbmodel"     # 없으면 이 경로
  RESHADE = dict(val=0.6, contrast=0.17)   # 있으면 원래 큐브 텍스처를 먼저 다시 칠한다 (reshade.py 옵션)
  SCALE = 1.0                              # MythicMobs model{scale=}
  COMPARE = ["skeleton_warrior"]           # 라인업에 같이 세울 기준 모델 (ID 또는 경로)
  LABEL = "사당의 망령"
  ANIMS = ["attack", "walk"]               # 부품이 기존 동작에서 이상 없는지 볼 동작
  def build(kit): ...                      # kit.material / kit.cube / kit.mirror_x
출력: OUT, <root>/미리보기/<이름>/ 에 라인업 PNG, 동작 확인 장면 PNG, 보고표.md
"""
import argparse, importlib.util, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import kitbash, lint, lineup, reshade, skilldeps  # noqa: E402


def load_spec(path):
    spec = importlib.util.spec_from_file_location("detail_spec", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k in ("SRC", "build"):
        if not hasattr(mod, k):
            raise SystemExit(f"설계 파일에 {k} 가 없음")
    return mod


def table(before, after):
    keys = [("cubes", "큐브"), ("render_bones", "렌더 뼈"), ("height_blk", "키(칸)"), ("cubes_per_blk", "큐브/키"),
            ("px_per_block", "px/블록"), ("colors95", "색95"), ("val", "명도"), ("contrast", "명암 폭"),
            ("noise", "노이즈"), ("edge_dark", "테두리"), ("top_light", "위밝음")]
    out = ["| 항목 | 원본 | 보강 |", "|---|---|---|"]
    for k, nm in keys:
        b = before["render_bones"] if k == "render_bones" else before["metrics"].get(k)
        a = after["render_bones"] if k == "render_bones" else after["metrics"].get(k)
        out.append(f"| {nm} | {b} | {a} |")
    return "\n".join(out)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--no-anims", action="store_true")
    ap.add_argument("--root", default=os.path.join("작업", "모델링"))
    a = ap.parse_args(argv)
    sp = load_spec(a.spec)
    src = sp.SRC
    name = os.path.splitext(os.path.basename(src))[0]
    out = getattr(sp, "OUT", None) or os.path.join(a.root, "모델", name + ".bbmodel")
    if os.path.abspath(out) == os.path.abspath(src):
        raise SystemExit("OUT 이 원본과 같음 — 원본은 고치지 않는다")
    scale = float(getattr(sp, "SCALE", 1.0))
    prev = os.path.join(a.root, "미리보기", name)
    os.makedirs(prev, exist_ok=True)

    kit = kitbash.Kit(src, seed=name)
    if getattr(sp, "RESHADE", None):
        tmp = os.path.join(tempfile.mkdtemp(), name + ".bbmodel")
        reshade.reshade(src, tmp, **sp.RESHADE)
        kit.replace_texture(tmp)
    sp.build(kit)
    kit.save(out)
    std, used = skilldeps.load_std(getattr(sp, "STD", None))
    before, after = lint.lint(src, scale, std), lint.lint(out, scale, std)
    print(f"저장: {out}  (새 큐브 {kit.count}개, 아트 기준: {used or '없음'})")

    lines = [f"# {getattr(sp, 'LABEL', name)} — 디테일 보강 결과", "",
             f"- 원본: `{src}` (읽기만 함)", f"- 결과: `{out}`", f"- 설계: `{a.spec}`",
             f"- 새 큐브 {kit.count}개, 부품 텍스처 {len(kit.tex)}장", "", "## 수치", "", table(before, after), "",
             "## 검사 (보강본)", ""]
    lines += [f"- 오류: {x}" for x in after["err"]] + [f"- 경고: {x}" for x in after["warn"]] or ["- 통과"]
    if not a.no_render:
        label = getattr(sp, "LABEL", name)
        toks = list(getattr(sp, "COMPARE", [])) + [f"{src}@{scale}={label} (원본)", f"{out}@{scale}={label} (보강)"]
        png = os.path.join(prev, f"{name}_라인업.png")
        lineup.main(["--out", png, "--title", f"{label} — 원본 → 보강 (같은 축척, 마인크래프트 조명)", "--stats",
                     "--ppb", str(getattr(sp, "PPB", 150))] + toks)
        lines += ["", "## 그림", "", f"- 라인업: `{png}`"]
        if not a.no_anims:
            mm = os.path.join(skilldeps.blender_motion_dir(), "make_motion.py")
            for anim in getattr(sp, "ANIMS", []):
                r = subprocess.run([sys.executable, "-I", mm, "--existing", out, anim, "--side", "--out", a.root],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                ok = r.returncode == 0
                lines.append(f"- 동작 확인 `{anim}`: " + (f"`{os.path.join(a.root, '미리보기', name, '검증_' + anim + '_장면.png')}`"
                                                       if ok else f"렌더 실패 ({r.stderr.strip()[-200:]})"))
    lines += ["", "## 확인 상태", "", "- 수치·렌더로 확인함. **인게임 미확인** (시험 서버에서 /meg reload 뒤 확인)", ""]
    rp = os.path.join(prev, "보고표.md")
    open(rp, "w", encoding="utf-8").write("\n".join(lines))
    print("보고표:", rp)


if __name__ == "__main__":
    main(sys.argv[1:])
