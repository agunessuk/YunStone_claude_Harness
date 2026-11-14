"""텍셀 밀도 맞추기: 모든 본체 면을 같은 픽셀 밀도(기본 1 px/유닛 = 인게임 16 px/블록)로 다시 깐다.

사용 (프로젝트 루트에서):
  python -I <스킬>/scripts/density_fix.py <원본.bbmodel> <출력.bbmodel> [--scale 1.0] [--target 16]
  --scale : MythicMobs model{scale=}. 인게임 밀도 = 파일 밀도 × 16 ÷ scale 이므로 목표 파일 밀도 = target × scale ÷ 16
  --target: 목표 인게임 px/블록 (기본 16)
하는 일
- 지금 밀도가 목표보다 **촘촘하면**(픽셀이 잘게 보임): 면마다 목표 크기(면 길이 × 목표 밀도, 반올림)로 줄여 새 텍스처에 다시 배치.
  줄일 때는 블록마다 "블록 평균에 가장 가까운 원래 픽셀 색"을 고른다 → 새 색을 만들지 않아 팔레트가 유지된다.
  잔디테일(1~2px 눈·문양)은 사라질 수 있다 → 렌더로 보고 사람이 손볼 목록에 올린다.
- 지금 밀도가 목표보다 **성기면**(픽셀이 굵게 보임): 정수배 최근접 확대만 한다(보이는 모양은 그대로, 격자만 촘촘해짐).
  그 위에 reshade.py 로 1px 테두리·명암을 얹으면 1텍셀 구조가 생긴다. 표면을 다시 그리는 일은 사람·GPT 몫.
- 결과 텍스처는 2의 거듭제곱 크기, 면 UV 는 1:1 픽셀. 원본은 읽기만 한다.
"""
import argparse, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import bbtex, metrics, skilldeps  # noqa: E402
from kitbash import Packer  # noqa: E402


def face_patch(img, frame_h, face, tex):
    """면 UV 가 덮는 픽셀 조각 (면에서 보이는 방향 그대로: 뒤집힌 UV 는 뒤집어 읽는다)."""
    u0, v0, u1, v1 = [float(x) for x in face["uv"]]
    x0, x1 = sorted((u0 * tex["sx"], u1 * tex["sx"]))
    y0, y1 = sorted((v0 * tex["sy"], v1 * tex["sy"]))
    xa, xb = int(math.floor(x0 + 1e-6)), max(int(math.ceil(x1 - 1e-6)), int(math.floor(x0 + 1e-6)) + 1)
    ya, yb = int(math.floor(y0 + 1e-6)), max(int(math.ceil(y1 - 1e-6)), int(math.floor(y0 + 1e-6)) + 1)
    p = img[ya:min(yb, frame_h), xa:xb]
    if u0 > u1:
        p = p[:, ::-1]
    if v0 > v1:
        p = p[::-1, :]
    return p


def shrink(p, h, w):
    """대표색 축소: 각 목표 픽셀 = 해당 원본 블록에서 블록 평균에 가장 가까운 실제 픽셀."""
    H, W = p.shape[:2]
    out = np.zeros((h, w, 4), np.uint8)
    ys = np.linspace(0, H, h + 1); xs = np.linspace(0, W, w + 1)
    for j in range(h):
        for i in range(w):
            blk = p[int(ys[j]):max(int(ys[j + 1]), int(ys[j]) + 1), int(xs[i]):max(int(xs[i + 1]), int(xs[i]) + 1)].reshape(-1, 4)
            vis = blk[blk[:, 3] >= 128]
            if len(vis) * 2 < len(blk):          # 절반 넘게 투명 → 투명
                continue
            m = vis[:, :3].astype(float).mean(0)
            out[j, i] = vis[np.argmin(((vis[:, :3] - m) ** 2).sum(1))]
    return out


def grow(p, k):
    return np.repeat(np.repeat(p, k, axis=0), k, axis=1)


def fix(src, dst, scale=1.0, target=16.0, verbose=True):
    bbpose = skilldeps.bbpose()
    M = bbpose.Model(src)
    m = M.m
    texs = bbtex.textures(m)
    cur = metrics.measure(src, scale)
    want = target * scale / 16.0                      # 목표 파일 밀도 (px/유닛)
    have = cur["px_per_unit"]
    if not have:
        raise SystemExit("밀도를 잴 수 없음 (텍스처·UV 없음)")
    ratio = want / have
    mode = "shrink" if ratio < 0.9 else ("grow" if ratio > 1.1 else "keep")
    if mode == "keep":
        if verbose:
            print(f"이미 목표 범위 ({cur['px_per_block']} px/블록) — 바꾸지 않음")
        bbtex.save(m, dst)
        return dst
    if mode == "grow":
        k = max(2, int(round(ratio)))
        for i, t in enumerate(texs):
            if t["img"] is None:
                continue
            m["textures"][i]["source"] = bbtex.encode_png(grow(t["img"], k))
            for key in ("width", "height"):
                if key in m["textures"][i]:
                    m["textures"][i][key] = int(m["textures"][i][key]) * k
        bbtex.save(m, dst)
        if verbose:
            print(f"성긴 밀도 {cur['px_per_block']} px/블록 → 텍스처만 {k}배 최근접 확대 (보이는 모양 그대로). "
                  f"이제 reshade.py 로 1px 구조를 얹거나 사람이 다시 그린다")
        return dst
    # shrink: 면마다 새 크기로 다시 배치
    jobs = []
    for eu in bbtex.body_elements(M, show_vfx=True):
        e = M.elements[eu]
        sz = np.abs(np.array(e["to"], float) - np.array(e["from"], float))
        for fname, f in (e.get("faces") or {}).items():
            if fname not in bbtex.FACE_AXES or not f.get("uv"):
                continue
            ti = bbtex.face_tex(f, texs)
            if ti is None or texs[ti]["img"] is None:
                continue
            au, av = bbtex.FACE_AXES[fname]
            gw, gh = sz[au], sz[av]
            if int(f.get("rotation", 0) or 0) % 180 == 90:
                gw, gh = gh, gw
            w, h = max(1, int(round(gw * want))), max(1, int(round(gh * want)))
            key = (ti, tuple(f["uv"]), w, h)
            jobs.append((f, ti, key, w, h))
    # 텍스처마다 따로 다시 깐다 (이름·순서 그대로 → 발광 층 _e 같은 구분이 유지된다)
    total = 0
    for ti in sorted({j[1] for j in jobs}):
        mine = [j for j in jobs if j[1] == ti]
        keys = sorted({j[2] for j in mine}, key=lambda k: (-k[3], -k[2]))
        size = 16
        while True:          # 2의 거듭제곱 정사각 텍스처에 다 들어갈 때까지 키운다
            pk, place, ok = Packer(size, size), {}, True
            for key in keys:
                r = pk.alloc(key[2], key[3])
                if r is None:
                    ok = False
                    break
                place[key] = r
            if ok:
                break
            size *= 2
        t = texs[ti]
        fh = t["img"].shape[0] // t["frames"]
        atlas = np.zeros((size, size, 4), np.uint8)
        done = set()
        for (f, _ti, key, w, h) in mine:
            if key not in done:
                p = face_patch(t["img"], fh, f, t)
                if p.size:
                    x, y = place[key]
                    atlas[y:y + h, x:x + w] = shrink(p, h, w)
                done.add(key)
            x, y = place[key]
            f["uv"] = [x, y, x + w, y + h]
        total += len(done)
        tj = m["textures"][ti]
        tj.update({"width": size, "height": size, "uv_width": size, "uv_height": size, "source": bbtex.encode_png(atlas)})
        if t["frames"] > 1 and verbose:
            print(f"주의: 텍스처 '{t['name']}' 는 애니메이션 프레임 {t['frames']}장 → 첫 프레임만 옮김")
    for e in m.get("elements", []):
        e["box_uv"] = False
    m.setdefault("meta", {})["box_uv"] = False
    bbtex.save(m, dst)
    after = metrics.measure(dst, scale)
    if verbose:
        print(f"촘촘한 밀도 {cur['px_per_block']} → {after['px_per_block']} px/블록, 면 {total}개 다시 배치, "
              f"텍스처 {', '.join(after['textures'])}, 색95 {cur.get('colors95')} → {after.get('colors95')}")
    return dst


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--target", type=float, default=16.0)
    a = ap.parse_args(argv)
    if os.path.abspath(a.src) == os.path.abspath(a.dst):
        raise SystemExit("원본에 덮어쓰지 않는다")
    fix(a.src, a.dst, a.scale, a.target)


if __name__ == "__main__":
    main(sys.argv[1:])
