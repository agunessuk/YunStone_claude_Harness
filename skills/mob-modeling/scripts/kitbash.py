"""큐브 부품 덧붙이기 + 부품 텍스처 칠하기 (코드로 디테일 살리기).

보통은 make_detail.py 가 설계 파일(작업/모델링/설계/<모델>.py)의 build(kit) 를 불러 쓴다:
    def build(kit):
        kit.material("robe", "#c8d2d6", half=0.22)
        kit.cube("b", [-4, 10, -3], [4, 21, 3], "robe", kind="cloth", name="robe_torso", skip=["up"])
직접 쓸 때: kit = Kit(원본경로); build(kit); kit.save(출력경로)   (원본은 읽기만, 출력=원본이면 멈춤)

규칙 (아트 기준과 맞춤)
- 크기·위치는 정수(1 = 1/16 블록). 부품 텍스처 밀도 = 원본 모델 밀도(보통 1 px/유닛 = 16 px/블록) → 믹셀 없음.
- 회전은 ModelEngine 규칙: 한 축만, 0·±22.5·±45 도.
- 새 큐브는 기존 뼈에 붙인다(기존 동작이 그대로 움직인다). 뼈 이름·동작은 바꾸지 않는다.
- 부품 면은 먼저 원본 텍스처의 빈 곳(어떤 면도 쓰지 않고 투명한 곳)에 넣는다 → 텍스처 장수가 늘지 않는다.
  모자라면 새 텍스처(원본 UV 해상도 크기)를 한 장씩 더한다. 발광 층(_e)·애니메이션 텍스처에는 넣지 않는다.
- 칠하기: 재질별 색 계단(reshade.ramp) 위에 부품 종류별 무늬 + 1px 테두리 한 칸 어둡게 + 위 밝게 + 약한 얼룩.
  종류: plain(맨살·뼈·나무), cloth(천: 세로 주름·찢어진 밑단), metal(금속: 윗줄 반짝임·모서리 징),
        hair(머리카락: 세로 가닥·들쭉날쭉 끝), glow(빛: 테두리 없이 가운데 밝게), dark(구멍·그림자 속)
"""
import copy, math, os, sys, zlib, uuid as _uuid
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import bbtex  # noqa: E402
import reshade  # noqa: E402

ALLOWED_ROT = (0.0, 22.5, -22.5, 45.0, -45.0)
FACES = ("north", "east", "south", "west", "up", "down")


def _hex_lab(h):
    h = h.strip("#")
    rgb = np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    return reshade.to_oklab(rgb[None])[0]


def _face_px(fname, size):
    """면의 (가로, 세로) 픽셀 = 큐브 크기 (1 유닛 = 1 px). Blockbench 기본 UV 방향."""
    sx, sy, sz = size
    return {"north": (sx, sy), "south": (sx, sy), "east": (sz, sy), "west": (sz, sy),
            "up": (sx, sz), "down": (sx, sz)}[fname]


def _num(v):
    """정수로 떨어지면 정수로 (파일을 깔끔하게)."""
    return int(round(v)) if abs(v - round(v)) < 1e-9 else round(v, 4)


class Packer:
    """선반(shelf) 방식 사각형 배치."""
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.x = self.y = self.row_h = 0

    def alloc(self, w, h):
        if w > self.w or h > self.h:
            return None
        if self.x + w > self.w:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        if self.y + h > self.h:
            return None
        r = (self.x, self.y)
        self.x += w
        self.row_h = max(self.row_h, h)
        return r


class Kit:
    def __init__(self, src, seed="kit"):
        self.src = src
        self.m = bbtex.load(src)
        self.seed = seed
        res = self.m.get("resolution") or {}
        self.res = (int(res.get("width", 16)), int(res.get("height", 16)))
        self.mats = {}
        self.jobs = []           # (텍스처 번호, x, y, w, h, 면이름, 재질, 종류, 옵션, 큐브 크기)
        self.tex = []            # 새 부품 텍스처 [(번호, Packer, RGBA 배열)]
        self.count = 0
        self.groups = {}
        self._index_groups()
        self._canvas = None      # 원본 텍스처 {번호: [RGBA, 빈칸 지도, sx, sy, 바뀜]} (처음 배치할 때 만든다)
        self.density = self._density()

    def _density(self):
        """원본 모델 밀도(px/유닛)를 0.5·1·2·4 중 가까운 값으로. 많이 벗어나면 density_fix 먼저 하라고 알린다."""
        import metrics
        try:
            d = metrics.measure(self.src)["px_per_unit"] or 1.0
        except Exception:
            return 1.0
        best = min((0.5, 1.0, 2.0, 4.0), key=lambda c: abs(math.log(d / c)))
        if abs(d / best - 1) > 0.1:
            print(f"주의: 원본 밀도 {d:.3f} px/유닛 — 부품은 {best} 로 맞춘다. density_fix.py 로 밀도를 먼저 맞추길 권함")
        return best

    def _ensure_canvas(self):
        if self._canvas is not None:
            return
        self._canvas = {}
        texs = bbtex.textures(self.m)
        occ = {t["idx"]: np.zeros((t["h"] // t["frames"], t["w"]), bool) for t in texs if t["img"] is not None}
        for e in self.m.get("elements", []):
            for f in (e.get("faces") or {}).values():
                if not f.get("uv"):
                    continue
                ti = bbtex.face_tex(f, texs)
                if ti is None or ti not in occ:
                    continue
                x0, y0, x1, y1 = bbtex.face_rect(f, texs[ti])
                occ[ti][max(0, y0):y1 + 1, max(0, x0):x1 + 1] = True
        for t in texs:
            if t["img"] is None or t["frames"] > 1 or t["name"].lower().replace(".png", "").endswith("_e"):
                continue
            img = t["img"].copy()
            o = occ[t["idx"]]
            o |= img[: o.shape[0], :, 3] > 0
            self._canvas[t["idx"]] = [img, o, t["sx"], t["sy"], False]

    @staticmethod
    def _free_spot(occ, w, h):
        H, W = occ.shape
        if w > W or h > H:
            return None
        sat = np.pad(occ.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        tot = sat[h:, w:] - sat[:-h, w:] - sat[h:, :-w] + sat[:-h, :-w]      # 칸마다 그 자리 w×h 안에 차 있는 픽셀 수
        ys, xs = np.nonzero(tot == 0)
        if not len(ys):
            return None
        return int(xs[0]), int(ys[0])

    def cubes(self, bone=None):
        """기존(원본) 큐브 목록 [(뼈, 이름, from, to, 회전, 뒤집힘)] — 겹칠 자리를 피해 설계할 때 본다."""
        import metrics
        bb = metrics._bbpose().Model(self.src)
        out = []
        for eu, e in bb.elements.items():
            g = bb.groups.get(bb.elem_group.get(eu), {}).get("name")
            if bone and g != bone:
                continue
            out.append((g, e.get("name"), e["from"], e["to"], e.get("rotation"), bbtex.is_flipped(e)))
        return out

    # ── 뼈 찾기 (4.x 안쪽 객체, 5.0 groups 배열 둘 다) ──
    def _index_groups(self):
        side = {g["uuid"]: g for g in self.m.get("groups", []) if isinstance(g, dict) and "uuid" in g}

        def walk(node):
            if isinstance(node, dict):
                nm = node.get("name") or side.get(node.get("uuid"), {}).get("name")
                if nm:
                    self.groups.setdefault(nm, node)
                for c in node.get("children", []):
                    walk(c)
        for n in self.m.get("outliner", []):
            walk(n)

    def bone_origin(self, bone):
        node = self.groups[bone]
        side = {g["uuid"]: g for g in self.m.get("groups", []) if isinstance(g, dict) and "uuid" in g}
        return list(node.get("origin") or side.get(node.get("uuid"), {}).get("origin") or [0, 0, 0])

    def colors(self, n=8, original=True):
        """주요 색 n 개 (픽셀 수 순) → 새 부품 재질을 원래 색에서 고를 때 쓴다. [(hex, 비율, OKLab L, HSV 명도 V)]
        original=True 면 원본 파일 색, False 면 지금(다시 칠한 뒤) 색. 재질의 center 는 OKLab L 이다."""
        src = bbtex.load(self.src) if original else self.m
        pix = [t["img"][t["img"][..., 3] >= 128][:, :3] for t in bbtex.textures(src) if t["img"] is not None]
        if not pix:
            return []
        P = np.concatenate(pix)
        codes, cnt = np.unique(P, axis=0, return_counts=True)
        o = np.argsort(-cnt)[:n]
        lab = reshade.to_oklab(codes[o] / 255.0)
        return [("#%02x%02x%02x" % tuple(codes[i]), round(cnt[i] / cnt.sum(), 3), round(float(lab[j][0]), 3),
                 round(float(codes[i].max()) / 255, 3)) for j, i in enumerate(o)]

    def material(self, name, hexcolor, half=0.22, steps=6, center=None):
        lab = _hex_lab(hexcolor)
        c = lab[0] if center is None else center
        self.mats[name] = dict(ramp=reshade.ramp(lab, c, half, steps), steps=steps)

    def _new_texture(self):
        w, h = int(self.res[0] * self.density), int(self.res[1] * self.density)      # px (uv 크기 = 원본 해상도)
        idx = len(self.m["textures"])
        name = f"{os.path.splitext(os.path.basename(self.src))[0]}_detail{len(self.tex) + 1}.png"
        t = {"path": "", "name": name, "folder": "", "namespace": "", "id": str(idx), "width": w, "height": h,
             "uv_width": self.res[0], "uv_height": self.res[1], "particle": False, "use_as_default": False, "layers_enabled": False,
             "sync_to_project": "", "render_mode": "default", "render_sides": "auto", "frame_time": 1,
             "frame_order_type": "loop", "frame_order": "", "frame_interpolate": False, "visible": True,
             "internal": True, "saved": False, "uuid": self._uid("tex", idx), "relative_path": "", "source": ""}
        self.m["textures"].append(t)
        self.tex.append([idx, Packer(w, h), np.zeros((h, w, 4), np.uint8)])
        return self.tex[-1]

    def _uid(self, *parts):
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, "/".join(str(p) for p in (self.seed,) + parts)))

    def _alloc(self, w, h):
        """w×h 픽셀 자리 → (텍스처 번호, x, y, sx, sy). 원본 텍스처 빈 곳 → 새 부품 텍스처 순."""
        self._ensure_canvas()
        for ti, c in self._canvas.items():
            r = self._free_spot(c[1], w, h)
            if r:
                x, y = r
                c[1][y:y + h, x:x + w] = True
                c[4] = True
                return ti, x, y, c[2], c[3]
        for t in self.tex:
            r = t[1].alloc(w, h)
            if r:
                return t[0], r[0], r[1], self.density, self.density
        t = self._new_texture()
        r = t[1].alloc(w, h)
        if not r:
            raise ValueError(f"면이 너무 큼 {w}x{h} (텍스처 {self.res})")
        return t[0], r[0], r[1], self.density, self.density

    def cube(self, bone, frm, to, mat, kind="plain", name=None, skip=(), rot=None, origin=None, opts=None):
        """bone 에 큐브 하나. frm/to 정수 좌표. skip: 텍스처를 주지 않을 면(안 보이는 면). rot: (축, 각도)."""
        frm, to = [float(v) for v in frm], [float(v) for v in to]
        size = [to[i] - frm[i] for i in range(3)]
        for v in frm + to:
            if abs(v - round(v)) > 1e-6:
                raise ValueError(f"정수 좌표만 (믹셀 방지): {name} {frm} {to}")
        if min(size) < 0:
            raise ValueError(f"from > to: {name}")
        if mat not in self.mats:
            raise KeyError(f"재질 없음: {mat}")
        rotation = [0.0, 0.0, 0.0]
        if rot:
            ax, ang = rot
            if float(ang) not in ALLOWED_ROT:
                raise ValueError(f"ModelEngine 회전은 0·±22.5·±45 만: {name} {ang}")
            rotation["xyz".index(ax)] = float(ang)
        if bone not in self.groups:
            raise KeyError(f"뼈 없음: {bone} (있는 뼈: {', '.join(self.groups)})")
        self.count += 1
        eu = self._uid("elem", self.count, name)
        faces = {}
        for f in FACES:
            fw, fh = _face_px(f, size)
            if f in skip or fw < 1e-6 or fh < 1e-6:
                faces[f] = {"uv": [0, 0, 0, 0], "texture": None}
                continue
            pw, ph = max(1, int(round(fw * self.density))), max(1, int(round(fh * self.density)))
            ti, x, y, sx, sy = self._alloc(pw, ph)
            faces[f] = {"uv": [_num(x / sx), _num(y / sy), _num((x + pw) / sx), _num((y + ph) / sy)], "texture": ti}
            self.jobs.append((ti, x, y, pw, ph, f, mat, kind, dict(opts or {}), size, self.count))
        e = {"name": name or f"{kind}_{self.count}", "box_uv": False, "rescale": False, "locked": False,
             "render_order": "default", "allow_mirror_modeling": True, "from": frm, "to": to, "autouv": 0,
             "color": self.count % 8, "origin": list(origin) if origin else [(frm[i] + to[i]) / 2 for i in range(3)],
             "faces": faces, "type": "cube", "uuid": eu}
        if any(rotation):
            e["rotation"] = rotation
        self.m["elements"].append(e)
        self.groups[bone].setdefault("children", []).append(eu)
        return eu

    def mirror_x(self, bone, frm, to, mat, kind="plain", name=None, skip=(), rot=None, origin=None, opts=None):
        """x 를 뒤집은 짝 (좌우 대칭 부품). east/west 를 바꾸고 z 축 회전 부호를 뒤집는다."""
        f2, t2 = [-to[0], frm[1], frm[2]], [-frm[0], to[1], to[2]]
        sk = [{"east": "west", "west": "east"}.get(s, s) for s in skip]
        r2 = None
        if rot:
            ax, ang = rot
            r2 = (ax, -ang if ax in ("y", "z") else ang)
        o2 = [-origin[0], origin[1], origin[2]] if origin else None
        return self.cube(bone, f2, t2, mat, kind, name, sk, r2, o2, opts)

    # ── 칠하기 ──
    def paint(self):
        rng_base = zlib.crc32(str(self.seed).encode("utf-8")) % 9973      # 실행마다 같은 무늬 (hash() 는 실행마다 다름)
        self._ensure_canvas()
        for (ti, x, y, w, h, fname, mat, kind, opts, size, cid) in self.jobs:
            img = self._canvas[ti][0] if ti in self._canvas else next(t[2] for t in self.tex if t[0] == ti)
            ramp = self.mats[mat]["ramp"]
            steps = len(ramp)
            st = 1.0 / (steps - 1)
            yy, xx = np.mgrid[0:h, 0:w]
            s = np.zeros((h, w))
            side = fname in ("north", "south", "east", "west")
            seed = rng_base + cid * 31 + FACES.index(fname) * 7
            n1 = reshade.hash_noise(h, w, seed)
            n2 = np.kron(reshade.hash_noise((h + 1) // 2, (w + 1) // 2, seed + 3), np.ones((2, 2)))[:h, :w]
            alpha = np.full((h, w), 255, np.uint8)
            big = w >= 4 and h >= 4
            border = np.zeros((h, w), bool)
            if big:
                border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
            if side and h > 1:
                s += (0.5 - yy / (h - 1)) * opts.get("grad", 0.16)
            if fname == "up":
                s += 0.5 * st
            if fname == "down":
                s -= 0.8 * st
            if w >= 5 and h >= 5 and kind not in ("glow",):
                d = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy))
                s += np.clip((d - 1) / 3, 0, 1) * opts.get("center", 0.08)
            noise = opts.get("noise", 0.06)
            s += (0.4 * n1 + 0.6 * n2) * noise / 2
            if kind == "cloth":
                if side and w >= 3:
                    # 주름: 불규칙 간격(3~5px)의 어두운 줄 + 바로 옆 밝은 줄, 밑으로 갈수록 진하게
                    col = np.zeros(w)
                    r = reshade.hash_noise(1, 64, seed + 17)[0]
                    c, j = int((r[0] + 1) * 1.5), 1
                    while c < w:
                        col[c] -= 1.0
                        if c + 1 < w:
                            col[c + 1] += 0.6
                        c += 3 + int((r[j % 64] + 1) * 1.0)
                        j += 1
                    depth_k = 0.6 + 0.6 * (yy / max(h - 1, 1))
                    s += col[None, :] * depth_k * st * opts.get("folds", 1.0)
                    if opts.get("hem", True) and h >= 3:
                        cut = (reshade.hash_noise(1, w, seed + 11)[0] + 1) / 2
                        depth = np.floor(cut * (opts.get("hem_depth", 2) + 1)).astype(int)
                        for c in range(w):
                            if depth[c] > 0:
                                alpha[h - depth[c]:, c] = 0
                        edge_row = np.zeros((h, w), bool)
                        for c in range(w):
                            r = h - depth[c] - 1
                            if 0 <= r < h:
                                edge_row[r, c] = True
                        border |= edge_row
            elif kind == "metal":
                if big or h >= 2:
                    s[0, :] += 1.2 * st
                    s[-1, :] -= 0.8 * st
                if w >= 5 and h >= 5 and opts.get("rivets", True):
                    for (ry, rx) in ((1, 1), (1, w - 2), (h - 2, 1), (h - 2, w - 2)):
                        s[ry, rx] += 2.0 * st
            elif kind == "hair":
                strand = reshade.hash_noise(1, w, seed + 5)[0]
                s += strand[None, :] * 1.2 * st
                if side and opts.get("hem", True):
                    cut = (reshade.hash_noise(1, w, seed + 13)[0] + 1) / 2
                    depth = np.floor(cut * (opts.get("hem_depth", 3) + 1)).astype(int)
                    for c in range(w):
                        if depth[c] > 0:
                            alpha[h - depth[c]:, c] = 0
            elif kind == "glow":
                # 빛: 가장자리는 진한 색, 가운데로 갈수록 거의 흰색 (테두리 어둡게 안 함)
                d = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy))
                s = -0.15 + np.clip(d / max(1.0, min(w, h) / 2 - 0.5), 0, 1) * 0.65
                border[:] = False
            elif kind == "dark":
                s -= 1.5 * st
            if kind not in ("glow",):
                s -= border * opts.get("edge", 1.0) * st
            s += opts.get("shift", 0.0) * st
            k = np.clip(np.round((s + 0.5) * (steps - 1)), 0, steps - 1).astype(int)
            rgb = np.round(reshade.from_oklab(ramp[k]) * 255).astype(np.uint8)
            img[y:y + h, x:x + w, :3] = rgb
            img[y:y + h, x:x + w, 3] = alpha
        for idx, _, arr in self.tex:
            self.m["textures"][idx]["source"] = bbtex.encode_png(arr)
        for idx, c in self._canvas.items():
            if c[4]:                                     # 빈 곳에 부품을 넣은 원본 텍스처
                self.m["textures"][idx]["source"] = bbtex.encode_png(c[0])

    def replace_texture(self, path_with_textures):
        """원본 큐브의 텍스처를 다른 파일(예: reshade 결과)의 것으로 바꾼다 (같은 모델에서 나온 파일)."""
        if self._canvas:
            raise RuntimeError("replace_texture 는 부품을 넣기 전에 불러야 한다")
        other = bbtex.load(path_with_textures)
        for i, t in enumerate(other.get("textures", [])):
            if i < len(self.m["textures"]):
                self.m["textures"][i]["source"] = t.get("source", self.m["textures"][i].get("source"))

    def save(self, out):
        if os.path.abspath(out) == os.path.abspath(self.src):
            raise SystemExit("원본에 덮어쓰지 않는다")
        self.paint()
        bbtex.save(self.m, out)
        return out
