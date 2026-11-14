"""다른 스킬·프로젝트 파일 찾기 (mob-modeling 스크립트 공용).

- bbpose.py(뼈대 자세 계산)·make_motion.find_blender 는 blender-motion 스킬의 것을 쓴다.
  찾는 순서: 이 폴더 → 옆 스킬 폴더(../../blender-motion/scripts) → ~/.claude/skills/blender-motion/scripts
- 아트 기준 파일: --std 로 준 것 → 현재 폴더의 작업/모델링/기준.json → art_standard.json → 이 스킬의 templates/art_standard.json
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


def blender_motion_dir():
    for d in (HERE, os.path.join(SKILL, "..", "blender-motion", "scripts"),
              os.path.expanduser("~/.claude/skills/blender-motion/scripts")):
        if os.path.isfile(os.path.join(d, "bbpose.py")):
            return os.path.abspath(d)
    raise SystemExit("blender-motion 스킬(bbpose.py)을 찾지 못함 — 로컬 하네스 install.py 로 함께 설치하세요")


def bbpose():
    d = blender_motion_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    import bbpose as mod
    return mod


def find_blender():
    d = blender_motion_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    import make_motion
    return make_motion.find_blender()


def model_index():
    """프로젝트의 모델 ID → 파일 (작업/모션/점검_원자료.json 이 있으면). 없으면 빈 사전."""
    files = {}
    p = os.path.join("작업", "모션", "점검_원자료.json")
    if os.path.isfile(p):
        d = json.load(open(p, encoding="utf-8"))
        for dg in d.get("dungeons", []):
            for m in dg.get("mobs", []):
                if m.get("model") and m["model"] not in files:
                    files[m["model"]] = m.get("file")
    return files


def resolve(token, files=None):
    """'<모델ID 또는 경로>[@배율][=이름표]' → dict(path, scale, key, label).
    ID 는 점검_원자료.json → 작업/풀어본_자료/**/<ID>.bbmodel → 현재 폴더 아래 전체(원본/·.git 제외) 순으로 찾는다.
    이름표가 없으면 모델 ID (던전마다 몹 이름이 달라 자동으로 붙이지 않는다)."""
    import glob
    label = None
    if "=" in token:
        token, label = token.split("=", 1)
    scale = 1.0
    if "@" in token:
        token, s = token.rsplit("@", 1)
        scale = float(s)
    if os.path.isfile(token):
        path = token
        mid = os.path.splitext(os.path.basename(token))[0]
    else:
        mid = token
        path = (files if files is not None else model_index()).get(mid)
        if not path or not os.path.isfile(path):
            hits = sorted(glob.glob(os.path.join("작업", "풀어본_자료", "**", mid + ".bbmodel"), recursive=True))
            if not hits:
                hits = sorted(h for h in glob.glob(os.path.join("**", mid + ".bbmodel"), recursive=True)
                              if not h.replace("\\", "/").startswith(("원본/", ".git/")))
            if not hits:
                raise SystemExit(f"모델을 찾지 못함: {mid}")
            path = hits[0]
    return dict(path=os.path.abspath(path), scale=scale, key=mid, label=label or mid)


def std_path(explicit=None):
    for p in (explicit, os.path.join("작업", "모델링", "기준.json"), "art_standard.json",
              os.path.join(SKILL, "templates", "art_standard.json")):
        if p and os.path.isfile(p):
            return p
    return None


def load_std(explicit=None):
    p = std_path(explicit)
    return (json.load(open(p, encoding="utf-8")), p) if p else ({}, None)
