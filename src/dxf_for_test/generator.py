"""生成首轮 3 套 STEP/DXF/JSON/PNG 并执行确定性数据检查。"""
import argparse
import hashlib
import json
from math import isclose
from pathlib import Path

import cadquery as cq
import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from .models import build_part, specifications
from .drawing import build_drawing


def save_preview_dxf(path: Path, preview: Path) -> None:
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, ColorPolicy, BackgroundPolicy
    doc = ezdxf.readfile(path)
    fig = plt.figure(figsize=(14, 9), dpi=145)
    ax = fig.add_axes((.025, .025, .95, .95))
    ax.set_aspect("equal")
    ax.set_axis_off()
    cfg = Configuration(color_policy=ColorPolicy.BLACK, background_policy=BackgroundPolicy.WHITE)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    fig.savefig(preview, dpi=145, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def save_preview_3d(shape: cq.Shape, preview: Path) -> None:
    points, triangles = shape.tessellate(0.8, 0.3)
    coords = [p.toTuple() for p in points]
    polys = [[coords[i] for i in tri] for tri in triangles]
    fig = plt.figure(figsize=(8, 7), dpi=130)
    ax = fig.add_subplot(111, projection="3d")
    mesh = Poly3DCollection(polys, linewidths=0, edgecolors="none",
                            facecolors=(.70, .80, .89, 1))
    ax.add_collection3d(mesh)
    bb = shape.BoundingBox()
    ranges = (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)
    ax.set(xlim=(ranges[0], ranges[1]), ylim=(ranges[2], ranges[3]),
           zlim=(ranges[4], ranges[5]))
    ax.set_box_aspect((max(bb.xlen, 1), max(bb.ylen, 1), max(bb.zlen, 1)), zoom=.85)
    ax.view_init(elev=26, azim=-57)
    ax.set_axis_off()
    fig.savefig(preview, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_one(spec, output: Path, with_previews=True) -> dict:
    folder = output / spec.part_id
    folder.mkdir(parents=True, exist_ok=True)
    solid = build_part(spec)
    if not isclose(solid.Volume(), spec.expected_volume, rel_tol=1e-7, abs_tol=1e-6):
        raise ValueError(f"体积不匹配：{spec.part_id}")
    step_path = folder / "part.step"
    dxf_path = folder / "drawing.dxf"
    cq.exporters.export(solid, str(step_path), exportType="STEP")
    drawing = build_drawing(spec, solid, dxf_path)
    reread = ezdxf.readfile(dxf_path)
    errors = reread.audit()
    if errors.has_errors:
        raise RuntimeError(f"DXF 重新读取失败：{spec.part_id}")
    if drawing["dimension_entities"] < 2:
        raise RuntimeError(f"缺少原生尺寸实体：{spec.part_id}")
    if len(drawing["views"]) != len(spec.views):
        raise RuntimeError(f"视图配置不符：{spec.part_id}")
    if with_previews:
        save_preview_dxf(dxf_path, folder / "preview_drawing.png")
        save_preview_3d(solid, folder / "preview_3d.png")
    definition = {"schema_version": 1, "part_id": spec.part_id, "name": spec.name,
                  "level": spec.level, "family": spec.family, "units": "mm",
                  "parameters": spec.parameters, "model_source": "cadquery_brep",
                  "geometry": {"solids": len(solid.Solids()), "faces": len(solid.Faces()),
                               "volume_mm3": round(solid.Volume(), 7),
                               "bounding_box": {
                                   "xmin": solid.BoundingBox().xmin, "xmax": solid.BoundingBox().xmax,
                                   "ymin": solid.BoundingBox().ymin, "ymax": solid.BoundingBox().ymax,
                                   "zmin": solid.BoundingBox().zmin, "zmax": solid.BoundingBox().zmax}},
                  "dimensions": spec.dimensions, "pmi": spec.pmi,
                  "drawing": drawing,
                  "semantic_pmi_in_step": False,
                  "warning": "当前 STEP 仅包含三维精确几何；二维 PMI 语义见本文件和 DXF 图形标注。"}
    (folder / "definition.json").write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")
    validation = {"part_id": spec.part_id, "solid_valid": solid.isValid(),
                  "expected_volume_mm3": round(spec.expected_volume, 7),
                  "actual_volume_mm3": round(solid.Volume(), 7),
                  "volume_check": True, "dxf_audit_errors": len(errors.errors),
                  "views": [v["id"] for v in drawing["views"]],
                  "native_dimensions": drawing["dimension_entities"],
                  "sha256": {name: sha256(folder / name) for name in ("part.step", "drawing.dxf")}}
    (folder / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"part_id": spec.part_id, "path": str(folder), "views": validation["views"],
            "volume_mm3": validation["actual_volume_mm3"], "native_dimensions": validation["native_dimensions"]}


def main():
    parser = argparse.ArgumentParser(description="生成首轮三种 DXF+STEP 基准零件")
    parser.add_argument("--output", default="samples", help="输出目录")
    parser.add_argument("--no-preview", action="store_true", help="跳过 PNG 预览")
    args = parser.parse_args()
    output = Path(args.output)
    result = [generate_one(spec, output, not args.no_preview) for spec in specifications()]
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()