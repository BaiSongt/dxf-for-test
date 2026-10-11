"""视图选择、工程尺寸、图框与二维 PMI 注释。"""
from pathlib import Path

import cadquery as cq
import ezdxf

from .models import PartSpec
from .projection import draw_projected, projected_edges, section_y_zero

LAYERS = {
    "GEOMETRY": 7,
    "HIDDEN": 8,
    "CENTER": 4,
    "DIMENSIONS": 2,
    "DATUM": 3,
    "GDNT": 6,
    "NOTES": 7,
    "HATCH": 8,
    "TITLEBLOCK": 8,
    "DETAIL": 5,
}


def _text(msp, content, x, y, height=3.2, layer="NOTES"):
    return msp.add_mtext(str(content), dxfattribs={"insert": (x, y), "char_height": height,
                                                  "layer": layer, "style": "CJK"})


def _dim(msp, p1, p2, base, angle=0, text="<>", override=None):
    options = {"dimtxt": 3, "dimasz": 2, "dimexe": 1.5, "dimexo": 1.5,
               "dimtad": 1, "dimdec": 0, "dimlfac": 1, "dimzin": 8}
    if override:
        options.update(override)
    dim = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=text,
                             dxfattribs={"layer": "DIMENSIONS"}, override=options)
    dim.render()
    return dim.dimension.dxf.handle


def _shaft_diameter_dim(
    msp,
    *,
    x_face: float,
    x_dimension: float,
    diameter: float,
    tolerance: float | None = None,
) -> str:
    """在轴的纵向投影上，以两条圆柱母线产生原生直径尺寸。

    - x_face 必须位于被测量的圆柱轴段内；尺寸点落在上下轮廓上。
    - x_dimension 控制竖向尺寸线，不使用斜向 leader 把文字拉到零件外。
    - 长短轴段可分别采取外置或轮廓内的竖向尺寸线，文字随 DIMENSION 排版。
    - 直径由真实投影跨度计算，避免把任意注释伪装成 PMI 尺寸。
    """
    radius = diameter / 2
    dim = msp.add_linear_dim(
        base=(x_dimension, 0),
        p1=(x_face, -radius),
        p2=(x_face, radius),
        angle=90,
        text="%%c<>",
        text_rotation=0 if tolerance is not None else None,
        dxfattribs={"layer": "DIMENSIONS"},
        override={
            "dimlfac": 1,
            "dimtxt": 3.3,
            "dimasz": 1.8,
            "dimdec": 0,
            "dimzin": 8,
            "dimtad": 1,
            "dimtih": 0,
            "dimtoh": 0,
            "dimse1": 1 if abs(x_face - x_dimension) < 0.01 else 0,
            "dimse2": 1 if abs(x_face - x_dimension) < 0.01 else 0,
            "dimexe": 1.5,
            "dimexo": 1.0,
        },
    )
    if tolerance is not None:
        dim.set_tolerance(upper=tolerance, lower=tolerance, hfactor=0.7, dec=2)
        dim.set_location((x_dimension, radius + 7), leader=False)
    dim.render()
    return dim.dimension.dxf.handle


def _frame(msp, name, bounds, scale="1:1"):
    x0, y0, x1, y1 = bounds
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                       dxfattribs={"layer": "TITLEBLOCK"})
    table_x = x1 - 155
    table_y = y0 + 7
    msp.add_lwpolyline([(table_x, table_y), (x1 - 7, table_y),
                        (x1 - 7, table_y + 33), (table_x, table_y + 33)], close=True,
                       dxfattribs={"layer": "TITLEBLOCK"})
    msp.add_line((table_x, table_y + 13), (x1 - 7, table_y + 13),
                 dxfattribs={"layer": "TITLEBLOCK"})
    _text(msp, name, table_x + 4, table_y + 30, 4.2)
    _text(msp, f"单位: mm    比例: {scale}    第一角法", table_x + 4, table_y + 10, 3)
    _text(msp, "示例数据 · 仅供测试使用", x0 + 9, y0 + 16, 3)


def _datum(msp, x, y, label="A", point=None):
    msp.add_lwpolyline([(x, y), (x + 11, y), (x + 11, y + 9), (x, y + 9)],
                       close=True, dxfattribs={"layer": "DATUM"})
    _text(msp, label, x + 3, y + 7.4, 5, "DATUM")
    if point:
        msp.add_line((x + 5.5, y), point, dxfattribs={"layer": "DATUM"})


def _fcf(msp, x, y, fields: tuple[str, ...], point=None):
    """第一阶段用结构化图形框格表达公差，语义内容另保存在 JSON。"""
    widths = [max(16, len(field) * 4) for field in fields]
    total = sum(widths)
    msp.add_lwpolyline([(x, y), (x + total, y), (x + total, y + 9), (x, y + 9)],
                       close=True, dxfattribs={"layer": "GDNT"})
    current = x
    for field, width in zip(fields, widths):
        if current != x:
            msp.add_line((current, y), (current, y + 9), dxfattribs={"layer": "GDNT"})
        _text(msp, field, current + 2, y + 7, 3.8, "GDNT")
        current += width
    if point:
        msp.add_leader([(x, y + 4.5), (x - 12, y + 4.5), point],
                       dxfattribs={"layer": "GDNT"})


def _hatch_cut_faces(msp, sectioned: cq.Shape, origin):
    """识别真实剖切面（Y=0），根据拓扑截面边界填入剖面线。"""
    ox, oy = origin
    num = 0
    for face in sectioned.Faces():
        b = face.BoundingBox()
        if face.geomType() != "PLANE" or max(abs(b.ymin), abs(b.ymax)) > 1e-6:
            continue
        verts = face.outerWire().Vertices()
        poly = [(ox + v.X, oy + v.Z) for v in verts]
        if len(poly) < 3:
            continue
        hatch = msp.add_hatch(color=8, dxfattribs={"layer": "HATCH"})
        hatch.set_pattern_fill("ANSI31", scale=5)
        hatch.paths.add_polyline_path(poly, is_closed=True)
        num += 1
    return num


def build_drawing(spec: PartSpec, solid: cq.Shape, target: Path) -> dict:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    # ezdxf 预置样式默认 DIMLFAC=100，mm 模型必须以 1:1 测量。
    doc.header["$DIMLFAC"] = 1
    doc.dimstyles.get("EZDXF").dxf.dimlfac = 1
    doc.styles.new("CJK", dxfattribs={"font": "NotoSansCJK-Regular.ttc"})
    for name, color in LAYERS.items():
        doc.layers.new(name, dxfattribs={"color": color})
    msp = doc.modelspace()
    views = []
    dim_handles = {}
    if spec.family == "plate":
        count = draw_projected(msp, projected_edges(solid, "top"), (0, 0))
        views.append({"id": "top", "kind": "orthographic", "scale": 1,
                      "origin": [0, 0], "geometry_count": count})
        _dim(msp, (-30, -20), (30, -20), (0, -34))
        _dim(msp, (-30, -20), (-30, 20), (-47, 0), angle=90)
        _text(msp, "板厚 t = 3 mm", 20, 51)
        _text(msp, "未注线性尺寸公差 ±0.2 mm", -76, -46)
        _frame(msp, f"{spec.part_id}  {spec.name}", (-100, -84, 180, 105))
    elif spec.family == "shaft":
        p = spec.parameters
        x0 = -65
        x1 = x0 + p["length_1"]
        x2 = x1 + p["length_2"]
        x3 = x2 + p["length_3"]
        d1, d2, d3 = (p[f"diameter_{i}"] for i in (1, 2, 3))
        count = draw_projected(msp, projected_edges(solid, "front"), (x0, 0))
        views.append({"id": "front", "kind": "orthographic", "scale": 1,
                      "origin": [x0, 0], "geometry_count": count})
        # 对于当前没有键槽的简单阶梯轴，端视图足以核对投影，禁止虚构断面。
        end_center = (132, 2)
        end_count = draw_projected(msp, projected_edges(solid, "end"), end_center)
        views.append({"id": "end", "kind": "orthographic", "scale": 1,
                      "origin": list(end_center), "geometry_count": end_count})
        # 参考真实轴类图：轴向尺寸集中在主视图下方，以近轮廓到远轮廓分层排列。
        dim_handles["D02"] = _dim(msp, (x0, -d1 / 2), (x1, -d1 / 2),
                                   ((x0 + x1) / 2, -35))
        dim_handles["D03"] = _dim(msp, (x1, -d2 / 2), (x2, -d2 / 2),
                                   ((x1 + x2) / 2, -35))
        dim_handles["D01"] = _dim(msp, (x0, -d1 / 2), (x3, -d3 / 2),
                                   ((x0 + x3) / 2, -56))
        # 直径尺寸在纵向视图各自的圆柱段上定义；端部移出外轮廓，避免交叉引线。
        dim_handles["D04"] = _shaft_diameter_dim(
            msp, x_face=x0 + 7, x_dimension=x0 - 14, diameter=d1)
        dim_handles["D05"] = _shaft_diameter_dim(
            msp, x_face=(x1 + x2) / 2, x_dimension=(x1 + x2) / 2,
            diameter=d2, tolerance=0.05)
        dim_handles["D06"] = _shaft_diameter_dim(
            msp, x_face=x3 - 5, x_dimension=x3 + 13, diameter=d3)
        # 长点画线表示回转中心；端视图仅画必要的中心十字。
        msp.add_line((x0 - 8, 0), (x3 + 8, 0),
                     dxfattribs={"layer": "CENTER", "linetype": "CENTER2"})
        ex, ey = end_center
        msp.add_line((ex - d1 / 2 - 5, ey), (ex + d1 / 2 + 5, ey),
                     dxfattribs={"layer": "CENTER", "linetype": "CENTER2"})
        msp.add_line((ex, ey - d1 / 2 - 5), (ex, ey + d1 / 2 + 5),
                     dxfattribs={"layer": "CENTER", "linetype": "CENTER2"})
        _text(msp, "主视图", -20, -74, 3)
        _text(msp, "端视图", 118, -34, 3)
        # 基准 A 关联指定直径要素；不把任意未定位的字母视为真实 PMI。
        _datum(msp, -48, 28, point=(-48, 20))
        _text(msp, "A: Ø40 基准圆柱面所导出轴线", -88, -85, 3)
        _text(msp, "1. 未注线性尺寸公差 ±0.20 mm", -88, -92, 3)
        _text(msp, "2. 去除毛刺和锐边", -88, -99, 3)
        _frame(msp, f"{spec.part_id}  {spec.name}", (-110, -132, 242, 91))
    elif spec.family == "pocket":
        count = draw_projected(msp, projected_edges(solid, "top"), (0, 22))
        views.append({"id": "top", "kind": "orthographic", "scale": 1,
                      "origin": [0, 22], "geometry_count": count})
        sectioned = section_y_zero(solid)
        section_origin = (0, -170)
        # 剖面先绘制 HATCH，以免挡住原生 HLR 投影边界。
        hatches = _hatch_cut_faces(msp, sectioned, section_origin)
        section_count = draw_projected(msp, projected_edges(sectioned, "front"), section_origin)
        views.append({"id": "section_AA", "kind": "section", "cut_plane": "Y=0",
                      "scale": 1, "origin": list(section_origin),
                      "geometry_count": section_count, "hatch_faces": hatches})
        clip = (-24, 24, -16, 16)
        detail_origin = (295, 35)
        detail_count = draw_projected(msp, projected_edges(solid, "top"),
                                      detail_origin, scale=2, clip=clip, layer="DETAIL")
        views.append({"id": "detail_B", "kind": "detail", "source_view": "top",
                      "source_region": list(clip), "scale": 2,
                      "origin": list(detail_origin), "geometry_count": detail_count})
        _dim(msp, (-80, -33), (80, -33), (0, -58))
        _dim(msp, (-80, -33), (-80, 77), (-102, 22), angle=90)
        _dim(msp, (-60, 57), (60, 57), (0, 104))
        _dim(msp, (80, -170), (80, -130), (108, -150), angle=90)
        _dim(msp, (48, -155), (48, -130), (66, -142), angle=90)
        # 局部尺寸换算系数为 1/2，故标注保持真实数值。
        _dim(msp, (277, 35), (313, 35), (295, 70),
             override={"dimlfac": .5, "dimdec": 0})
        _text(msp, "俯视图", -16, -77)
        _text(msp, "剖视 A-A", -25, -190)
        _text(msp, "局部详图 B (2:1)", 255, 96)
        _text(msp, "2×Ø6 通孔", 257, -15, 3.8)
        _text(msp, "4×Ø8 通孔", 92, 107, 3.8)
        _text(msp, "腔深 25", 73, -113, 3.4)
        msp.add_circle((0, 22), 25, dxfattribs={"layer": "DETAIL"})
        _text(msp, "B", 25, 52, 4, "DETAIL")
        msp.add_line((-92, 22), (92, 22), dxfattribs={"layer": "CENTER"})
        _text(msp, "A", -105, 29, 5, "CENTER")
        _text(msp, "A", 95, 29, 5, "CENTER")
        _datum(msp, -133, -200, point=(-70, -170))
        _fcf(msp, 135, -152, ("FLAT", "0.10"), point=(60, -170))
        _fcf(msp, 135, -176, ("POS", "Ø0.20", "A"), point=(70, -130))
        _text(msp, "GD&T: FLAT=平面度；POS=位置度", 124, -202, 3)
        _frame(msp, f"{spec.part_id}  {spec.name}", (-145, -250, 440, 145))
    else:
        raise ValueError(spec.family)
    target.parent.mkdir(parents=True, exist_ok=True)
    # DXF 审计为硬门槛，文件输出后还将进行重新读取校验。
    errors = doc.audit()
    if errors.has_errors:
        raise RuntimeError(f"DXF 内部校验失败：{len(errors.errors)}")
    doc.saveas(target)
    return {"views": views, "dimension_entities": len(msp.query("DIMENSION")),
            "dimension_handles": dim_handles,
            "pmi_rendering": "editable_2d_graphical_annotations",
            "dxf_version": "AC1032"}