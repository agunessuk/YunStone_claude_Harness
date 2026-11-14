"""bbmodel 텍스처·면 도우미 (numpy + Pillow 만 씀 — Blender 안에서도, 밖에서도 돌아감).

- 텍스처 읽기: 파일 안에 든 PNG(data URI), 텍스처별 UV 크기(uv_width/height), 세로로 이어 붙인 애니메이션 프레임
- 면 → 텍스처 번호: 숫자 또는 uuid 문자열 둘 다
- 면 UV → 텍스처 픽셀 사각형 (조사 노트 our_models_audit 의 측정과 같은 반올림: 포함 좌표 x0..x1)
- 본체 큐브 고르기: ModelEngine 히트박스 뼈(hitbox, b_, ob_)와 효과용 뼈(vfx·particle·…)는 뺀다
"""
import base64, io, json, os, re
import numpy as np

FACE_AXES = {"north": (0, 1), "south": (0, 1), "east": (2, 1), "west": (2, 1), "up": (0, 2), "down": (0, 2)}
SIDE = ("north", "south", "east", "west")
VFX_BONE = re.compile(r"vfx|particle|(^|_)ray(\d|_|$)|portal|summon|circle|card|mirror|shard|glitch|aura|"
                      r"^fire_(left|right)$|^octagon$|^shadow$|projectile|^cut_", re.I)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(m, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent="\t")


def decode_png(src):
    from PIL import Image
    if not src or not src.startswith("data:image"):
        return None
    try:
        return np.array(Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))).convert("RGBA"))
    except Exception:
        return None


def encode_png(arr):
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.asarray(arr, dtype=np.uint8), "RGBA").save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def png_bytes(src):
    if not src or not src.startswith("data:image"):
        return None
    try:
        return base64.b64decode(src.split(",", 1)[1])
    except Exception:
        return None


def png_size(b):
    """PNG 헤더(IHDR)에서 (가로, 세로). Pillow 없는 곳(Blender 안)에서 쓴다."""
    if b and b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR":
        return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    return None


def textures(m, decode=True):
    """텍스처 목록: dict(idx, name, uuid, img(RGBA uint8 또는 None), png(원본 바이트), w, h, uv_w, uv_h, frames, sx, sy).
    sx·sy = UV 1단위가 텍스처 몇 픽셀인지 (첫 프레임 기준). decode=False 면 Pillow 없이 크기만 헤더에서 읽는다."""
    res = m.get("resolution") or {}
    rw, rh = res.get("width", 16), res.get("height", 16)
    out = []
    for i, t in enumerate(m.get("textures", [])):
        uv_w = float(t.get("uv_width") or rw)
        uv_h = float(t.get("uv_height") or rh)
        raw = png_bytes(t.get("source") or "")
        img = decode_png(t.get("source") or "") if decode else None
        size = png_size(raw)
        if img is not None:
            h, w = img.shape[:2]
        elif size:
            w, h = size
        else:
            w, h = int(t.get("width") or uv_w), int(t.get("height") or uv_h)
        frames = 1
        exp_h = w * uv_h / uv_w
        if h > exp_h * 1.01 and abs(h / exp_h - round(h / exp_h)) < 1e-6:
            frames = int(round(h / exp_h))
        out.append(dict(idx=i, name=t.get("name", ""), uuid=t.get("uuid"), img=img, png=raw if size else None, w=w, h=h,
                        uv_w=uv_w, uv_h=uv_h, frames=frames, sx=w / uv_w, sy=(h / frames) / uv_h))
    return out


def face_tex(face, texs):
    t = face.get("texture")
    if t is None or t is False:
        return None
    if isinstance(t, str):
        for x in texs:
            if x["uuid"] == t:
                return x["idx"]
        return None
    if isinstance(t, (int, float)) and 0 <= int(t) < len(texs):
        return int(t)
    return None


def face_rect(face, tex):
    """면 UV → 텍스처 픽셀 사각형 (x0, y0, x1, y1) 포함 좌표, 첫 프레임 기준. 뒤집힌 UV 는 정렬한다."""
    import math
    uv = face["uv"]
    x0 = math.floor(min(uv[0], uv[2]) * tex["sx"] + 1e-6)
    x1 = math.ceil(max(uv[0], uv[2]) * tex["sx"] - 1e-6) - 1
    y0 = math.floor(min(uv[1], uv[3]) * tex["sy"] + 1e-6)
    y1 = math.ceil(max(uv[1], uv[3]) * tex["sy"] - 1e-6) - 1
    return x0, y0, max(x1, x0), max(y1, y0)


def body_elements(model, show_vfx=False):
    """렌더·통계에 넣을 큐브 uuid 목록. model 은 bbpose.Model."""
    skip, vfx = set(), set()
    for u in model.order:
        g = model.groups[u]
        p = g["parent"]
        nm = g["name"].lower()
        if "hitbox" in nm or nm.startswith("b_") or nm.startswith("ob_") or p in skip:
            skip.add(u)
        elif VFX_BONE.search(nm) or p in vfx:
            vfx.add(u)
    out = []
    for eu, e in model.elements.items():
        if e.get("visibility") is False or (e.get("name") or "").lower() == "hitbox":
            continue
        gu = model.elem_group.get(eu)
        if gu in skip or (gu in vfx and not show_vfx):
            continue
        out.append(eu)
    return out


def luma(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
