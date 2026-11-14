"""디테일 보강 실행기: 설계 파일(.py) → 복사본 .bbmodel + 검사 + 라인업(앞·뒤) + 동작 자세 시트 + 보고표.

사용 (프로젝트 루트에서):
  python -I <스킬>/scripts/make_detail.py <설계.py> [--no-render] [--no-anims] [--gif] [--root 작업/모델링]
  --no-render : 수치·검사만 (1초 안팎) — 좌표를 고치며 반복할 때 먼저 쓴다
  --no-anims  : 라인업만, 동작 자세 시트 생략
  --gif       : blender-motion 의 make_motion 으로 동작 GIF 도 만든다 (사용자에게 보낼 때)
설계 파일 (templates/detail_spec_example.py 참고):
  SRC = "원본.bbmodel"                     # 읽기만 한다
  OUT = "작업/모델링/모델/<이름>.bbmodel"     # 없으면 이 경로. 이미 있으면 미리보기/<이름>/이전/v<N>.bbmodel 로 보관
  RESHADE = dict(val=0.6, contrast=0.17)   # 있으면 원래 큐브 텍스처를 먼저 다시 칠한다 (reshade.py 인자: mode, protect=[…] 등)
  SCALE = 1.0                              # MythicMobs model{scale=}
  THEME = "dark"                           # 있으면 기준.json 의 dark_theme_ranges 로 판정
  STD = "작업/모델링/기준.json"              # 아트 기준 파일 (없으면 기본 찾기)
  COMPARE = ["skeleton_warrior=해골 전사"]  # 라인업에 같이 세울 기준 모델 (ID 또는 경로, =이름표)
  LABEL = "사당의 망령"
  PPB = 150                                # 라인업 1블록 = px
  ANIMS = ["attack", "walk"]               # 자세 시트로 볼 기존 동작 (다섯 순간 × 3/4·옆)
  def build(kit): ...                      # kit.material / kit.cube / kit.mirror_x / kit.cubes() / kit.colors()
출력: OUT, <root>/미리보기/<이름>/ 에 라인업 v<N> PNG, 동작 자세 시트 PNG, 보고표.md
"""
import argparse, glob, importlib.util, os, re, shutil, subprocess, sys, tempfile

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
    keys = [("cubes", "큐브"), ("flipped", "뒤집힌 큐브"), ("render_bones", "렌더 뼈"), ("height_blk", "키(칸)"),
            ("cubes_per_blk", "큐브/키"), ("px_per_block", "px/블록"), ("colors95", "색95"), ("val", "명도"),
            ("contrast", "명암 폭"), ("noise", "노이즈"), ("edge_dark", "테두리"), ("top_light", "위밝음")]
    out = ["| 항목 | 원본 | 보강 |", "|---|---|---|"]
    for k, nm in keys:
        b = before["render_bones"] if k == "render_bones" else before["metrics"].get(k)
        a = after["render_bones"] if k == "render_bones" else after["metrics"].get(k)
        out.append(f"| {nm} | {b} | {a} |")
    return "\n".join(out)


def material_table(kit):
    rows = ["| 재질 | 계단 밝기 OKLab L | 계단 명도 V |", "|---|---|---|"]
    for nm, mt in kit.mats.items():
        rgb = reshade.from_oklab(mt["ramp"])
        L = mt["ramp"][:, 0]
        rows.append(f"| {nm} | {L.min():.2f}~{L.max():.2f} | {rgb.max(1).min():.2f}~{rgb.max(1).max():.2f} |")
    return "\n".join(rows)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--no-anims", action="store_true")
    ap.add_argument("--gif", action="store_true")
    ap.add_argument("--root", default=os.path.join("작업", "모델링"))
    a = ap.parse_args(argv)
    sp = load_spec(a.spec)
    src = sp.SRC
    name = os.path.splitext(os.path.basename(src))[0]
    out = getattr(sp, "OUT", None) or os.path.join(a.root, "모델", name + ".bbmodel")
    if os.path.abspath(out) == os.path.abspath(src):
        raise SystemExit("OUT 이 원본과 같음 — 원본은 고치지 않는다")
    scale = float(getattr(sp, "SCALE", 1.0))
    theme = getattr(sp, "THEME", None)
    label = getattr(sp, "LABEL", name)
    prev = os.path.join(a.root, "미리보기", name)
    os.makedirs(prev, exist_ok=True)

    # 고친 회차: 렌더해서 본 판만 이전/v<N>.bbmodel 로 보관한다 (--no-render 로 고쳐 본 중간 판은 남기지 않음)
    olddir = os.path.join(prev, "이전")
    vers = sorted(int(m.group(1)) for f in glob.glob(os.path.join(olddir, "v*.bbmodel"))
                  for m in [re.search(r"v(\d+)\.bbmodel$", f)] if m)
    last = os.path.join(olddir, f"v{vers[-1]}.bbmodel") if vers else None
    ver = (vers[-1] + 1) if vers else 1

    kit = kitbash.Kit(src, seed=name)
    if getattr(sp, "RESHADE", None):
        with tempfile.TemporaryDirectory() as td:          # 다시 칠한 텍스처만 가져오고 임시 파일은 지운다
            tmp = os.path.join(td, name + ".bbmodel")
            reshade.reshade(src, tmp, **sp.RESHADE)
            kit.replace_texture(tmp)
    sp.build(kit)
    kit.save(out)
    std, used = skilldeps.load_std(getattr(sp, "STD", None))
    before, after = lint.lint(src, scale, std, theme), lint.lint(out, scale, std, theme)
    print(f"저장: {out}  (새 큐브 {kit.count}개, 부품 밀도 {kit.density} px/유닛, 아트 기준: {used or '없음'}"
          f"{f', {theme} 테마' if theme else ''})")
    for x in after["err"] + after["warn"]:
        print("  -", x)

    lines = [f"# {label} — 디테일 보강 결과 (v{ver})", "",
             f"- 원본: `{src}` (읽기만 함)", f"- 결과: `{out}`" + (f" (직전에 렌더한 판: `{last}`)" if last else ""),
             f"- 설계: `{a.spec}`", f"- 새 큐브 {kit.count}개, 새 부품 텍스처 {len(kit.tex)}장 (나머지는 원본 텍스처 빈 곳)",
             f"- 판정 기준: `{used}`" + (f", **{theme} 테마 범위**" if theme else ""), "", "## 수치", "", table(before, after), "",
             "## 재질 (center 는 OKLab 밝기 L, 아트 기준의 명도는 HSV V)", "", material_table(kit), "", "## 검사 (보강본)", ""]
    lines += ([f"- 오류: {x}" for x in after["err"]] + [f"- 경고: {x}" for x in after["warn"]]) or ["- 통과"]
    if not a.no_render:
        files = skilldeps.model_index()
        specs = [skilldeps.resolve(t, files) for t in getattr(sp, "COMPARE", [])]
        specs.append(dict(path=os.path.abspath(src), scale=scale, key=name + "_원본", label=f"{label} (원본)"))
        if last and open(last, "rb").read() != open(out, "rb").read():
            specs.append(dict(path=os.path.abspath(last), scale=scale, key=name + "_직전", label=f"{label} (v{ver - 1})"))
        specs.append(dict(path=os.path.abspath(out), scale=scale, key=name + "_보강", label=f"{label} (v{ver})"))
        png = os.path.join(prev, f"{name}_라인업_v{ver}.png")
        lineup.render(specs, png, f"{label} — 원본 → 보강 v{ver} (같은 축척, 마인크래프트 조명, 아래 줄은 뒷모습)",
                      stats=True, ppb=getattr(sp, "PPB", 150), per_row=6, back=True)
        lines += ["", "## 그림", "", f"- 라인업 (앞·뒤): `{png}`"]
        os.makedirs(olddir, exist_ok=True)
        shutil.copy2(out, os.path.join(olddir, f"v{ver}.bbmodel"))        # 이번에 렌더해서 본 판 보관 → 다음 실행의 '직전 판'
        if not a.no_anims:
            M = kit_model(out)
            for anim in getattr(sp, "ANIMS", []):
                an = M.animations().get(anim)
                if not an:
                    lines.append(f"- 동작 `{anim}`: 모델에 없음")
                    continue
                L = float(an["length"])
                ts = [round(L * k / 4, 2) for k in range(5)]
                ps = [dict(path=os.path.abspath(out), scale=scale, key=f"{name}_{anim}_{i}", label=f"{anim} {t:.2f}초",
                           pose=[anim, t]) for i, t in enumerate(ts)]
                apng = os.path.join(prev, f"{name}_자세_{anim}_v{ver}.png")
                lineup.render(ps, apng, f"{label} — {anim} 다섯 순간 (위 3/4, 아래 옆)", ppb=getattr(sp, "PPB", 150),
                              per_row=5, player=False, views=[(28, ""), (90, "옆")])
                ok = os.path.isfile(apng)
                lines.append(f"- 동작 `{anim}` 자세 시트: " + (f"`{apng}`" if ok else "렌더 실패"))
                if a.gif:
                    mm = os.path.join(skilldeps.blender_motion_dir(), "make_motion.py")
                    r = subprocess.run([sys.executable, "-I", mm, "--existing", out, anim, "--side", "--out", a.root],
                                       capture_output=True, text=True, encoding="utf-8", errors="replace")
                    gif = os.path.join(a.root, "미리보기", name, f"검증_{anim}.gif")
                    lines.append(f"  - GIF: " + (f"`{gif}`" if os.path.isfile(gif) and r.returncode == 0
                                                 else f"실패 ({(r.stdout + r.stderr).strip()[-200:]})"))
    lines += ["", "## 확인 상태", "", "- 수치·렌더로 확인함. **인게임 미확인** (시험 서버에서 /meg reload 뒤 확인)", ""]
    rp = os.path.join(prev, "보고표.md")
    open(rp, "w", encoding="utf-8").write("\n".join(lines))
    print("보고표:", rp)


def kit_model(path):
    return skilldeps.bbpose().Model(path)


if __name__ == "__main__":
    main(sys.argv[1:])
