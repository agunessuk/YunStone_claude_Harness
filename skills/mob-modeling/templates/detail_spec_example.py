"""디테일 보강 설계 예시 — 사당의 망령 (LostAssets Wraith, 큐브 8 → 39). make_detail.py 가 읽는다.

복사 위치: 작업/모델링/설계/<모델ID>.py   실행: python -I <스킬>/scripts/make_detail.py 작업/모델링/설계/<모델ID>.py

설계 전에 할 것 (references/detail-design.md)
1. inspect: blender-motion 의 inspect_model.py 로 뼈 트리·큐브·동작 범위를 본다. 뼈가 서로 이어져 있는지(부모·자식)가 중요하다.
   이 모델은 머리 h_h, 몸 b, 팔 l_a·r_a, 다리 l_l·r_l 이 모두 루트 아래 형제 → 몸에 긴 천을 붙이면 다리가 뚫는다.
2. 동작 범위: 공격·등장에서 다리 x −61°~+27°, 머리 x −38°, 팔 x −71° → 치마는 반쪽씩 다리 뼈에, 등 망토는 허리까지.
3. 겹침: 앞 머리카락 판이 z=−3 에 있다 → 같은 자리에 면을 두면 깜박인다(z-fighting). 몸 앞쪽에는 부품을 두지 않는다.
4. 색: kit.colors() 로 원래 주요 색을 보고 재질 기준색을 거기서 고른다 (새 색을 지어내지 않는다).
좌표: Blockbench 단위(1 = 1/16 블록), 앞 = −Z, 위 = +Y. 모두 정수. 회전은 한 축 0·±22.5·±45 만.
"""

SRC = "작업/풀어본_자료/몬스터/LostAssets_MobsPack_08_DawnRiver/ModelEngine/blueprints/lostasset_mob8_Wraith.bbmodel"
# OUT = "작업/모델링/모델/lostasset_mob8_Wraith.bbmodel"     # 없으면 이 경로
RESHADE = dict(val=0.62, contrast=0.17)        # 원래 큐브 텍스처를 먼저 다시 칠함 (reshade.py, 원래 색 유지)
SCALE = 1.0                                    # MythicMobs model{scale=}
LABEL = "사당의 망령"
COMPARE = ["skeleton_warrior", "skeleton_archer"]   # 라인업에 같이 세울 기준 모델
ANIMS = ["attack", "walk"]                     # 부품이 기존 동작에서 이상 없는지 볼 동작


def build(kit):
    # 재질: 원래 색 계단과 맞춘다 (다시 칠한 몸 중심 L 0.68, 폭 ±0.25)
    kit.material("robe", "#9aa6a9", half=0.25, center=0.68)
    kit.material("shade", "#5f6e74", half=0.20, center=0.50)     # 두건·베일 (몸보다 어둡게 → 얼굴이 돋보임)
    kit.material("iron", "#5b5654", half=0.20, center=0.46)
    kit.material("frame", "#3e4148", half=0.16, center=0.38)
    kit.material("flame", "#4fd8f0", half=0.20, center=0.80)     # 포인트 색은 하나만 (혼불)

    # 머리: 두건 껍데기 (얼굴 쪽 north 와 아래는 열림) + 차양 + 옆 테 + 뒤로 처진 끝 + 베일
    kit.cube("h_h", [-5, 20, -5], [5, 31, 6], "shade", "cloth", "hood_shell", skip=["north", "down"],
             opts=dict(hem_depth=1, folds=0.6))
    kit.cube("h_h", [-5, 29, -6], [5, 31, -5], "shade", "cloth", "hood_brim", opts=dict(hem=False, folds=0))
    kit.cube("h_h", [-6, 20, -6], [-5, 31, 1], "shade", "cloth", "hood_edge_r", opts=dict(hem_depth=1, folds=0))
    kit.mirror_x("h_h", [-6, 20, -6], [-5, 31, 1], "shade", "cloth", "hood_edge_l", opts=dict(hem_depth=1, folds=0))
    kit.cube("h_h", [-3, 27, 5], [3, 31, 9], "shade", "cloth", "hood_tail", rot=("x", -22.5), opts=dict(hem=False))
    kit.cube("h_h", [-4, 15, 6], [4, 22, 7], "shade", "cloth", "veil_back", opts=dict(hem_depth=3))

    # 몸: 등 망토 (허리까지)
    kit.cube("b", [-4, 11, 3], [4, 21, 4], "robe", "cloth", "cape", opts=dict(hem_depth=2))

    # 팔: 위는 좁은 소매, 아래는 넓게 퍼진 소매 + 소매 끝 띠
    for bone, side in (("l_a", 1), ("r_a", -1)):
        c = kit.cube if side > 0 else kit.mirror_x
        c(bone, [2, 15, -3], [7, 21, 3], "robe", "cloth", f"sleeve_up_{bone}", skip=["down"], opts=dict(hem=False))
        c(bone, [1, 8, -4], [8, 15, 4], "robe", "cloth", f"sleeve_flare_{bone}", skip=["down"], opts=dict(hem_depth=2))
        c(bone, [1, 14, -4], [8, 15, 4], "shade", "cloth", f"sleeve_trim_{bone}", skip=["down"], opts=dict(hem=False, folds=0))
    kit.mirror_x("r_a", [4, 5, 0], [5, 8, 1], "iron", "metal", "chain1_r_a")
    kit.mirror_x("r_a", [4, 2, 0], [5, 5, 1], "iron", "metal", "chain2_r_a", rot=("y", 45))

    # 등불 (+X 손): 틀은 metal, 불은 glow (테두리 없이 가운데 밝게)
    kit.cube("l_a", [4, 5, -1], [5, 8, 0], "iron", "metal", "lantern_chain")
    kit.cube("l_a", [2, 4, -2], [7, 5, 1], "frame", "metal", "lantern_top")
    kit.cube("l_a", [3, 0, -2], [6, 4, 1], "flame", "glow", "lantern_flame")
    kit.cube("l_a", [2, -1, -2], [7, 0, 1], "frame", "metal", "lantern_bottom")
    for x, z in ((2, -2), (6, -2), (2, 0), (6, 0)):
        kit.cube("l_a", [x, 0, z], [x + 1, 4, z + 1], "frame", "metal", f"lantern_bar_{x}_{z}")

    # 다리: 찢어진 치마 반쪽씩 (안쪽 면 skip → 두 반쪽이 맞닿는 x=0 에서 깜박임 없음) + 허리 감개 + 늘어진 천
    kit.cube("l_l", [0, 1, -3], [4, 11, 3], "robe", "cloth", "skirt_l", skip=["west"], opts=dict(hem_depth=3))
    kit.mirror_x("r_l", [0, 1, -3], [4, 11, 3], "robe", "cloth", "skirt_r", skip=["west"], opts=dict(hem_depth=3))
    kit.cube("l_l", [0, 9, -4], [4, 11, 4], "shade", "cloth", "waist_wrap_l", skip=["west", "down"], opts=dict(hem=False, folds=0))
    kit.mirror_x("r_l", [0, 9, -4], [4, 11, 4], "shade", "cloth", "waist_wrap_r", skip=["west", "down"], opts=dict(hem=False, folds=0))
    kit.cube("l_l", [1, -2, -4], [4, 9, -4], "shade", "cloth", "strip_front_l", opts=dict(hem_depth=3))   # 두께 0 판
    kit.mirror_x("r_l", [1, -1, -4], [3, 9, -4], "shade", "cloth", "strip_front_r", opts=dict(hem_depth=3))
    kit.cube("l_l", [0, -1, 4], [3, 9, 4], "shade", "cloth", "strip_back_l", opts=dict(hem_depth=2))
    kit.mirror_x("r_l", [1, -2, 4], [4, 9, 4], "shade", "cloth", "strip_back_r", opts=dict(hem_depth=2))
