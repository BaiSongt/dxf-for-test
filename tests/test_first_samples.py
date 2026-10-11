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