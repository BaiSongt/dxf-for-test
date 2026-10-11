"""三维实体、二维实体与视图配置的回归测试。"""
from math import isclose

import ezdxf
import pytest

from dxf_for_test.generator import generate_one
from dxf_for_test.models import build_part, specifications
from dxf_for_test.projection import projected_edges, section_y_zero


@pytest.mark.parametrize("spec", specifications(), ids=lambda s: s.part_id)
def test_geometry_is_valid(spec):
    solid = build_part(spec)
    assert solid.isValid()
    assert len(solid.Solids()) == 1
    assert isclose(solid.Volume(), spec.expected_volume, rel_tol=1e-7)


def test_views_are_derived_from_the_same_brep():
    plate, shaft, pocket = specifications()
    assert len(projected_edges(build_part(plate), "top")) == 4
    assert projected_edges(build_part(shaft), "end")
    pocket_shape = build_part(pocket)
    section = section_y_zero(pocket_shape)
    assert section.isValid()
    assert section.Volume() < pocket_shape.Volume()
    assert projected_edges(section, "front")


@pytest.mark.parametrize("spec", specifications(), ids=lambda s: s.part_id)
def test_end_to_end_generation(tmp_path, spec):
    result = generate_one(spec, tmp_path, with_previews=False)
    folder = tmp_path / spec.part_id
    assert (folder / "part.step").stat().st_size > 4000
    assert (folder / "definition.json").exists()
    assert (folder / "validation.json").exists()
    dxf = ezdxf.readfile(folder / "drawing.dxf")
    assert not dxf.audit().has_errors
    assert len(dxf.modelspace().query("DIMENSION")) >= 2
    assert result["views"] == list(spec.views)
    if spec.family == "pocket":
        assert len(dxf.modelspace().query("HATCH")) >= 1
        assert len(dxf.modelspace().query('CIRCLE[layer=="DETAIL"]')) >= 2

def test_all_dimensions_measure_in_millimeters(tmp_path):
    """防止 ezdxf 默认 DIMLFAC=100 将 120 mm 绘制成 12000。"""
    for spec in specifications():
        generate_one(spec, tmp_path, with_previews=False)
        doc = ezdxf.readfile(tmp_path / spec.part_id / "drawing.dxf")
        assert doc.header["$INSUNITS"] == 4
        assert doc.header["$DIMLFAC"] == 1
        for dim in doc.modelspace().query("DIMENSION"):
            override = dim.get_acad_dstyle(doc.dimstyles.get(dim.dxf.dimstyle))
            factor = override.get("dimlfac", doc.dimstyles.get(dim.dxf.dimstyle).dxf.get("dimlfac", 1))
            assert factor in (1, 0.5)  # 2:1 的局部详图测量修正


def test_shaft_diameters_are_real_semantic_dimensions(tmp_path):
    """回转体三个直径都有原生尺寸实体、公差和真实几何测量值。"""
    import json
    spec = next(s for s in specifications() if s.family == "shaft")
    generate_one(spec, tmp_path, with_previews=False)
    folder = tmp_path / spec.part_id
    doc = ezdxf.readfile(folder / "drawing.dxf")
    msp = doc.modelspace()
    dims = msp.query("DIMENSION")
    assert len(dims) == 6
    by_diameter = {}
    for dim in dims:
        if dim.dxf.text.startswith("%%c"):
            assert (dim.dxf.dimtype & 7) == 0
            val = dim.get_measurement()
            by_diameter[val] = dim
            graphical_text = "".join(e.dxf.text for e in doc.blocks[dim.dxf.geometry].query("MTEXT"))
            assert f"%%c{int(val)}" in graphical_text
            assert dim.get_acad_dstyle(doc.dimstyles.get(dim.dxf.dimstyle))["dimlfac"] == 1
    assert set(by_diameter) == {20.0, 30.0, 40.0}
    tolerance = by_diameter[30.0].get_acad_dstyle(doc.dimstyles.get(by_diameter[30.0].dxf.dimstyle))
    assert tolerance["dimtol"] == 1
    assert isclose(tolerance["dimtp"], 0.05)
    assert isclose(tolerance["dimtm"], 0.05)
    assert not any("Ø30" in (e.dxf.text or "") for e in msp.query('MTEXT[layer=="DIMENSIONS"]'))
    assert len(msp.query('LINE[layer=="CENTER"]')) >= 3
    definition = json.loads((folder / "definition.json").read_text(encoding="utf-8"))
    handles = definition["drawing"]["dimension_handles"]
    assert set(handles) == {f"D0{i}" for i in range(1, 7)}
    assert {round(doc.entitydb[handles[f"D0{i}"]].get_measurement(), 4) for i in (4, 5, 6)} == {20, 30, 40}


def test_shaft_dimensions_follow_turning_drawing_layout(tmp_path):
    """轴类尺寸按功能分区：长度在下方分层、直径归属轴段且无漂浮引线。"""
    spec = next(s for s in specifications() if s.family == "shaft")
    generate_one(spec, tmp_path, with_previews=False)
    doc = ezdxf.readfile(tmp_path / spec.part_id / "drawing.dxf")
    drawing = __import__("json").loads(
        (tmp_path / spec.part_id / "definition.json").read_text(encoding="utf-8")
    )["drawing"]
    dims = {key: doc.entitydb[handle]
            for key, handle in drawing["dimension_handles"].items()}

    # 轴向长度放在负 Y 一侧，并保持局部尺寸靠近、总体尺寸在外层。
    assert dims["D01"].dxf.defpoint.y < dims["D02"].dxf.defpoint.y
    assert dims["D01"].dxf.defpoint.y < dims["D03"].dxf.defpoint.y
    assert dims["D02"].dxf.defpoint.y < -20
    assert dims["D03"].dxf.defpoint.y < -20
    # 两条外侧直径尺寸线不得穿过零件轮廓，圆柱中间尺寸的文字放在轮廓上方。
    assert dims["D04"].dxf.defpoint.x < -65
    assert dims["D06"].dxf.defpoint.x > 55
    assert dims["D05"].dxf.text_midpoint.y > 15
    assert all(dim.dxf.text.startswith("%%c") for dim in (dims["D04"], dims["D05"], dims["D06"]))
    assert len(doc.modelspace().query("LEADER")) == 0
    # 没有键槽与内部台阶的纯回转轴不应虚构断面图。
    assert not doc.modelspace().query("HATCH")
    assert all(view["kind"] == "orthographic" for view in drawing["views"])
