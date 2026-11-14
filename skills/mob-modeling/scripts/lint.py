"""모델 검사: ModelEngine R4 규칙 + 아트 기준 수치 (읽기 전용).

사용 (프로젝트 루트에서):
  python -I <스킬>/scripts/lint.py <모델.bbmodel>[@배율] ... [--std 기준.json] [--md 결과.md]
판정: 오류(서버에서 깨질 가능성이 큼) / 경고(기준 밖이거나 인게임 확인 필요) / 통과
근거: research_notes/마인크래프트 3D 몹 모델링 방식/engine_limits_performance.md (ME 공식 위키 2026-11 갱신본)
"""
import json, math, os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import bbtex  # noqa: E402
import metrics  # noqa: E402

ALLOWED = (0.0, 22.5, 45.0)
EMPTY_TAGS = re.compile(r"^(ih_|ir_|il_|l_|seg_|tl_|tlf_|mount)", re.I)     # 큐브가 없어야 하는 태그 뼈
HINT = {"l_": "리드 연결 지점", "ih_": "머리 아이템", "ir_": "주손 아이템", "il_": "보조손 아이템",
        "seg_": "체인 마디(R4.0.7+)", "tl_": "꼬리 체인(R4.0.7+)", "tlf_": "꼬리 체인", "mount": "탑승 지점"}


def pow2(n):
    return n > 0 and (n & (n - 1)) == 0


def lint(path, scale=1.0, std=None):
    bbpose = metrics._bbpose()
    M = bbpose.Model(path)
    m = M.m
    err, warn, info = [], [], []
    fmt = (m.get("meta") or {}).get("model_format")
    if fmt != "free":
        warn.append(f"형식 {fmt} (ModelEngine 문서는 Generic Model=free 기준)")
    if any(e.get("type") == "mesh" for e in m.get("elements", [])):
        err.append("메시 요소 있음 (ModelEngine 미지원)")
    # 텍스처
    texs = bbtex.textures(m)
    for t in texs:
        if t["img"] is None:
            err.append(f"텍스처 '{t['name']}' 가 파일 안에 없음")
            continue
        h1 = t["h"] // t["frames"]
        if not (pow2(t["w"]) and pow2(h1)):
            warn.append(f"텍스처 '{t['name']}' {t['w']}x{h1} 가 2의 거듭제곱 아님 (아틀라스 mipmap 저하)")
        if abs(t["sx"] - round(t["sx"])) > 1e-6 and abs(1 / t["sx"] - round(1 / t["sx"])) > 1e-6:
            warn.append(f"텍스처 '{t['name']}' 픽셀/UV 비율 {t['sx']:.3f} 이 정수배 아님")
    # 큐브 회전
    bad_rot = []
    for e in M.elements.values():
        r = e.get("rotation")
        if isinstance(r, dict):
            angs = [float(r.get("angle", 0))]
        elif isinstance(r, list):
            angs = [float(a) for a in r if abs(float(a)) > 1e-6]
        else:
            angs = []
        if len(angs) > 1 or any(min(abs(abs(a) - x) for x in ALLOWED) > 1e-3 for a in angs):
            bad_rot.append(e.get("name", "?"))
    if bad_rot:
        warn.append(f"큐브 회전 규칙 밖 {len(bad_rot)}개 (한 축·0/±22.5/±45 만): {', '.join(bad_rot[:6])}"
                    f"{' …' if len(bad_rot) > 6 else ''} — 인게임 확인 필요")
    # 태그 뼈·히트박스
    hit = None
    render_bones = 0
    for u in M.order:
        g = M.groups[u]
        nm = g["name"]
        if nm.lower() == "hitbox":
            hit = g
            continue
        if g["elements"]:
            render_bones += 1
        mt = EMPTY_TAGS.match(nm)
        if mt and g["elements"]:
            warn.append(f"뼈 '{nm}' 은 ModelEngine 태그({HINT.get(mt.group(1).lower(), mt.group(1))})인데 큐브 {len(g['elements'])}개 — "
                        f"큐브가 안 보이거나 태그 동작이 붙을 수 있음, 인게임 확인 필요")
    if hit is None:
        warn.append("hitbox 뼈 없음 (몹 크기 판정이 기본값)")
    else:
        if len(hit["elements"]) != 1:
            warn.append(f"hitbox 큐브 {len(hit['elements'])}개 (1개여야 함)")
        else:
            e = M.elements[hit["elements"][0]]
            sx = abs(e["to"][0] - e["from"][0]); sz = abs(e["to"][2] - e["from"][2])
            if abs(sx - sz) > 1e-6:
                info.append(f"hitbox 가로 {sx} ≠ 깊이 {sz} (넓은 쪽만 씀)")
        if hit["origin"][1] < 0:
            err.append("hitbox 기준점 Y < 0 (질식 피해)")
    # 동작
    bez = sorted({a["name"] for a in m.get("animations", []) for an in (a.get("animators") or {}).values()
                  for k in an.get("keyframes", []) if k.get("interpolation") == "bezier"})
    if bez:
        warn.append(f"Bezier 보간 동작 {len(bez)}개 (ModelEngine 은 linear 로 재생): {', '.join(bez[:5])}")
    # 크기·밀도·색 (metrics)
    r = metrics.measure(path, scale)
    def _frac(d):       # 두께 0.1 미만 판(겹침 방지용)은 빼고 본다
        return abs(d) >= 0.1 and abs(d - round(d)) > 1e-3
    frac = sum(1 for e in M.elements.values() if any(_frac(e["to"][i] - e["from"][i]) for i in range(3)))
    if M.elements and frac / len(M.elements) > 0.10:
        warn.append(f"소수 크기 큐브 {frac}/{len(M.elements)} (UV 를 편 뒤 통째 확대·축소한 흔적 → 밀도 불일치)")
    if std:
        for k in metrics.judge(r, std):
            warn.append(f"아트 기준 밖: {k}")
    info.append(f"큐브 {r['cubes']}, 렌더 뼈 {render_bones}, 키 {r['height_blk']}칸, {r.get('px_per_block')} px/블록, "
                f"색95 {r.get('colors95')}, 명도 {r.get('val')}, 명암 {r.get('contrast')}, 테두리 {r.get('edge_dark')}")
    return dict(file=os.path.basename(path), err=err, warn=warn, info=info, metrics=r, render_bones=render_bones)


def main(argv):
    std_path, md = None, None
    items, i = [], 0
    while i < len(argv):
        if argv[i] == "--std": std_path = argv[i + 1]; i += 2; continue
        if argv[i] == "--md": md = argv[i + 1]; i += 2; continue
        items.append(argv[i]); i += 1
    import skilldeps
    std, used = skilldeps.load_std(std_path)
    print(f"(아트 기준: {used or '없음'})")
    lines = []
    for it in items:
        p, _, s = it.partition("@")
        res = lint(p, float(s) if s else 1.0, std)
        verdict = "오류" if res["err"] else ("경고" if res["warn"] else "통과")
        lines.append(f"### {res['file']} — {verdict}")
        lines += [f"- 오류: {x}" for x in res["err"]] + [f"- 경고: {x}" for x in res["warn"]] + [f"- 정보: {x}" for x in res["info"]]
        lines.append("")
    out = "\n".join(lines)
    print(out)
    if md:
        open(md, "w", encoding="utf-8").write(out)


if __name__ == "__main__":
    main(sys.argv[1:])
