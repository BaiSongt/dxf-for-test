"""三种基准零件的参数定义与精确 B-Rep 构建。"""
from dataclasses import dataclass
from math import pi

import cadquery as cq


@dataclass(frozen=True)
class PartSpec:
    part_id: str
    name: str
    level: int
    family: str
    parameters: dict[str, float]
    views: tuple[str, ...]
    dimensions: tuple[dict, ...]
    pmi: tuple[dict, ...]
    expected_volume: float


def specifications() -> tuple[PartSpec, ...]:
    return (
        PartSpec(
            "L01-001", "矩形薄板", 1, "plate",
            {"length": 60, "width": 40, "thickness": 3},
            ("top",),
            ({"id": "D01", "type": "linear", "value": 60, "feature": "outer_length"},
             {"id": "D02", "type": "linear", "value": 40, "feature": "outer_width"},
             {"id": "D03", "type": "thickness_note", "value": 3, "feature": "plate_thickness"}),
            ({"id": "P01", "type": "general_tolerance", "value": "未注线性尺寸公差 ±0.2 mm", "feature": "part"},),
            60 * 40 * 3,
        ),
        PartSpec(
            "L04-001", "三段阶梯轴", 4, "shaft",
            {"length_1": 40, "length_2": 50, "length_3": 30,
             "diameter_1": 40, "diameter_2": 30, "diameter_3": 20},
            ("front", "end"),
            ({"id": "D01", "type": "linear", "value": 120, "feature": "total_length"},
             {"id": "D02", "type": "linear", "value": 40, "feature": "segment_1"},
             {"id": "D03", "type": "linear", "value": 50, "feature": "segment_2"},
             {"id": "D04", "type": "diameter", "value": 40, "feature": "shaft_large"},
             {"id": "D05", "type": "diameter", "value": 30, "feature": "shaft_middle"},
             {"id": "D06", "type": "diameter", "value": 20, "feature": "shaft_small"}),
            ({"id": "P01", "type": "size_tolerance", "value": "Ø30 ±0.05", "feature": "shaft_middle"},
             {"id": "P02", "type": "datum", "value": "A", "feature": "shaft_large_axis"}),
            pi * (20**2 * 40 + 15**2 * 50 + 10**2 * 30),
        ),
        PartSpec(
            "L06-001", "带岛体的深腔安装板", 6, "pocket",
            {"length": 160, "width": 110, "height": 40,
             "pocket_length": 120, "pocket_width": 70, "pocket_depth": 25,
             "island_length": 36, "island_width": 24,
             "mounting_diameter": 8, "mounting_pitch_x": 138, "mounting_pitch_y": 88,
             "island_hole_diameter": 6, "island_hole_pitch": 18},
            ("top", "section_AA", "detail_B"),
            ({"id": "D01", "type": "linear", "value": 160, "feature": "overall_length"},
             {"id": "D02", "type": "linear", "value": 110, "feature": "overall_width"},
             {"id": "D03", "type": "depth", "value": 25, "feature": "pocket_floor"},
             {"id": "D04", "type": "hole", "value": 8, "quantity": 4, "feature": "mounting_holes"},
             {"id": "D05", "type": "hole", "value": 6, "quantity": 2, "feature": "island_holes"},
             {"id": "D06", "type": "linear", "value": 18, "feature": "island_hole_pitch"}),
            ({"id": "P01", "type": "datum", "value": "A", "feature": "bottom_face"},
             {"id": "P02", "type": "flatness", "value": 0.1, "feature": "bottom_face"},
             {"id": "P03", "type": "position", "value": 0.2, "reference": "A", "feature": "mounting_holes"}),
            (160 * 110 * 40 - 120 * 70 * 25 + 36 * 24 * 25
             - 4 * pi * 4**2 * 40 - 2 * pi * 3**2 * 40),
        ),
    )


def build_part(spec: PartSpec) -> cq.Shape:
    """按特征参数构建唯一三维实体，不针对视图另建假几何。"""
    p = spec.parameters
    if spec.family == "plate":
        shape = cq.Workplane("XY").box(p["length"], p["width"], p["thickness"],
                                       centered=(True, True, False)).val()
    elif spec.family == "shaft":
        segments = ((0, p["length_1"], p["diameter_1"]),
                    (p["length_1"], p["length_2"], p["diameter_2"]),
                    (p["length_1"] + p["length_2"], p["length_3"], p["diameter_3"]))
        solids = [cq.Solid.makeCylinder(d / 2, length, cq.Vector(x, 0, 0), cq.Vector(1, 0, 0))
                  for x, length, d in segments]
        shape = solids[0].fuse(*solids[1:]).clean()
    elif spec.family == "pocket":
        body = cq.Workplane("XY").box(p["length"], p["width"], p["height"],
                                      centered=(True, True, False)).val()
        depth = p["pocket_depth"]
        floor = p["height"] - depth
        cavity = cq.Workplane("XY").box(p["pocket_length"], p["pocket_width"], depth,
                                          centered=(True, True, False)).translate((0, 0, floor)).val()
        island = cq.Workplane("XY").box(p["island_length"], p["island_width"], depth,
                                          centered=(True, True, False)).translate((0, 0, floor)).val()
        shape = body.cut(cavity).fuse(island).clean()
        holes = []
        for x in (-p["mounting_pitch_x"] / 2, p["mounting_pitch_x"] / 2):
            for y in (-p["mounting_pitch_y"] / 2, p["mounting_pitch_y"] / 2):
                holes.append(cq.Solid.makeCylinder(p["mounting_diameter"] / 2, p["height"],
                                                    cq.Vector(x, y, 0)))
        for x in (-p["island_hole_pitch"] / 2, p["island_hole_pitch"] / 2):
            holes.append(cq.Solid.makeCylinder(p["island_hole_diameter"] / 2, p["height"],
                                                cq.Vector(x, 0, 0)))
        shape = shape.cut(*holes).clean()
    else:
        raise ValueError(f"不支持的零件族：{spec.family}")
    if not shape.isValid() or len(shape.Solids()) != 1:
        raise RuntimeError(f"实体构建失败：{spec.part_id}")
    return shape