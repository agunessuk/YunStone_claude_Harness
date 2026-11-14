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


def std_path(explicit=None):
    for p in (explicit, os.path.join("작업", "모델링", "기준.json"), "art_standard.json",
              os.path.join(SKILL, "templates", "art_standard.json")):
        if p and os.path.isfile(p):
            return p
    return None


def load_std(explicit=None):
    p = std_path(explicit)
    return (json.load(open(p, encoding="utf-8")), p) if p else ({}, None)
