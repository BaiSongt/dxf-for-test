"""带真实键槽回转体的三维/二维联动、剖切与可测量 PMI 回归测试。"""
from dataclasses import replace
from math import isclose, pi
import json

import cadquery as cq
import ezdxf
import pytest

from dxf_for_test.generator import generate_one
from dxf_for_test.models import build_part, specifications
from dxf_for_test.shaft_drawing import exact_transverse_section


def keyed_spec():
    return next(spec for spec in specifications() if spec.family == "shaft_keyed")


def test_keyed_shaft_is_one_valid_solid_with_two_real_slots():
    spec = keyed_spec()
    shape = build_part(spec)
    assert shape.isValid() and len(shape.Solids()) == 1
    assert isclose(shape.Volume(), 157004.54806467931, rel_tol=1e-7)
    for label, diameter in (("A", 40), ("B", 24)):
        x = spec.parameters[f"keyway_{label}_center"]
        depth = spec.parameters[f"keyway_{label}_depth"]
        radius = diameter / 2
        face = exact_transverse_section(shape, x)
        assert face.isValid()
        assert face.Area() < pi * radius ** 2
        assert len(face.outerWire().Edges()) >= 4
        # 槽底外方一点是去料空间，槽底内方一点仍然是实体。
        assert not shape.isInside(cq.Vector(x, -(radius - depth / 2), 0), 1e-5)
        assert shape.isInside(cq.Vector(x, -(radius - depth - 1), 0), 1e-5)


def test_keyway_parameters_alter_real_section_area():
    spec = keyed_spec()
    p = dict(spec.parameters)
    p["keyway_A_depth"] = 5.2
    deeper = replace(spec, parameters=p)
    original = build_part(spec)
    changed = build_part(deeper)
    assert changed.isValid() and changed.Volume() < original.Volume()
    x = p["keyway_A_center"]
    assert exact_transverse_section(changed, x).Area() < exact_transverse_section(original, x).Area()


def test_keyed_shaft_3d_2d_dimensions_sections_and_step_roundtrip(tmp_path):
    spec = keyed_spec()
    result = generate_one(spec, tmp_path, with_previews=False)
    folder = tmp_path / spec.part_id
    dxf = ezdxf.readfile(folder / "drawing.dxf")
    assert not dxf.audit().has_errors
    meta = json.loads((folder / "definition.json").read_text(encoding="utf-8"))
    validation = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
    assert validation["step_roundtrip_valid"] is True
    reimported = cq.importers.importStep(str(folder / "part.step")).val()
    assert reimported.isValid() and len(reimported.Solids()) == 1
    assert isclose(reimported.Volume(), meta["geometry"]["volume_mm3"], rel_tol=1e-8)
    assert result["views"] == ["front", "section_AA", "section_BB"]
    views = meta["drawing"]["views"]
    assert len(views) == 3
    for view, label in zip(views[1:], "AB"):
        x = spec.parameters[f"keyway_{label}_center"]
        assert view["source_cut_position_mm"] == x
        assert view["feature_id"] == f"keyway_{label}"
        assert view["source"] == "exact_brep_section"
        assert view["geometry_count"] >= 4 and view["hatch_faces"] == 1
        measured_area = exact_transverse_section(reimported, x).Area()
        assert isclose(view["section_area_mm2"], measured_area, rel_tol=1e-7)
    msp = dxf.modelspace()
    assert len(msp.query("HATCH")) == 2
    assert len(msp.query("ARC")) >= 2
    handles = meta["drawing"]["dimension_handles"]
    assert len(handles) == 12
    values = {k: round(dxf.entitydb[handle].get_measurement(), 4)
              for k, handle in handles.items()}
    expected = {"D01": 210, "D02": 55, "D03": 80,
                "D04": 40, "D05": 30, "D06": 24,
                "D07": 36, "D08": 42, "D09": 12, "D10": 4.5,
                "D11": 8, "D12": 3}
    assert values == expected
    for name in ("D09", "D11"):
        entity = dxf.entitydb[handles[name]]
        overrides = entity.get_acad_dstyle(dxf.dimstyles.get(entity.dxf.dimstyle))
        assert overrides["dimtol"] == 1
        assert isclose(overrides["dimtp"], 0.04)
        assert isclose(overrides["dimtm"], 0.04)
    assert {a["feature"] for a in meta["dimensions"]} >= {
        "keyway_A_width", "keyway_B_width", "keyway_A_depth", "keyway_B_depth"
    }
    assert meta["semantic_pmi_in_step"] is False


@pytest.mark.parametrize("field,value", [
    ("keyway_A_width", 0),
    ("keyway_A_depth", 22),
    ("keyway_A_length", 80),
    ("keyway_B_center", 205),
])
def test_reject_invalid_keyway_geometry(field, value):
    spec = keyed_spec()
    params = dict(spec.parameters)
    params[field] = value
    with pytest.raises(ValueError, match="键槽"):
        build_part(replace(spec, parameters=params))
