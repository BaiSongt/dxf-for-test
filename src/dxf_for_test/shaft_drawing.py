"""轴类制造图：同源 B-Rep 真实截面、特征尺寸与标注布局。"""
from __future__ import annotations

from math import atan2, ceil, degrees, pi

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Curve

from .drafting import _datum, _dim, _frame, _shaft_diameter_dim, _text
from .projection import draw_projected, projected_edges


def exact_transverse_section(shape: cq.Shape, x: float) -> cq.Face:
    """与 X 常量平面精确求交；不得手工重画假断面。"""
    plane = cq.Plane(origin=(x, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))
    result = cq.Workplane(plane).add(shape).section().val()
    faces = result.Faces()
    if len(faces) != 1 or not faces[0].isValid():
        raise ValueError(f"x={x} 剖面缺失或不唯一")
    return faces[0]


def _point_on_section(point, origin: tuple[float, float]):
    # 以 Z 为截面横坐标、-Y 为纵坐标，使朝向 -Y 的键槽显示在断面上端。
    return (origin[0] + point.z, origin[1] - point.y)


def _arc_angles_in_section(edge, center):
    start = _point_on_section(edge.startPoint(), (0, 0))
    end = _point_on_section(edge.endPoint(), (0, 0))
    sa = degrees(atan2(start[1] - center[1], start[0] - center[0])) % 360
    ea = degrees(atan2(end[1] - center[1], end[0] - center[0])) % 360
    mid = _point_on_section(edge.positionAt(0.5), (0, 0))
    ma = degrees(atan2(mid[1] - center[1], mid[0] - center[0])) % 360
    if (ma - sa) % 360 <= (ea - sa) % 360:
        return sa, ea
    return ea, sa


def add_exact_section(msp, shape: cq.Shape, x: float, origin: tuple[float, float]):
    """将 B-Rep 截面真实轮廓输出成直线、圆弧实体，并使用截面面域填充。"""
    face = exact_transverse_section(shape, x)
    edges = face.outerWire().Edges()
    # HATCH 的采样轮廓仅供填充；边界仍用原生解析 LINE/ARC 保持准确。
    path_points = []
    for edge in edges:
        samples = max(3, ceil(edge.Length() / 0.35))
        path_points.extend(_point_on_section(edge.positionAt(i / samples), origin)
                           for i in range(samples))
    hatch = msp.add_hatch(color=8, dxfattribs={"layer": "HATCH"})
    hatch.set_pattern_fill("ANSI31", scale=2.8)
    hatch.paths.add_polyline_path(path_points, is_closed=True)
    count = 0
    for edge in edges:
        start = _point_on_section(edge.startPoint(), origin)
        end = _point_on_section(edge.endPoint(), origin)
        if edge.geomType() == "LINE":
            msp.add_line(start, end, dxfattribs={"layer": "GEOMETRY"})
        elif edge.geomType() == "CIRCLE":
            circle = BRepAdaptor_Curve(edge.wrapped).Circle()
            center = (circle.Location().Z(), -circle.Location().Y())
            center_shifted = (origin[0] + center[0], origin[1] + center[1])
            rad = circle.Radius()
            if abs(edge.Length() - 2*pi*rad) < 1e-5:
                msp.add_circle(center_shifted, rad, dxfattribs={"layer": "GEOMETRY"})
            else:
                a, b = _arc_angles_in_section(edge, center)
                msp.add_arc(center_shifted, rad, start_angle=a, end_angle=b,
                            dxfattribs={"layer": "GEOMETRY"})
        else:
            # 切面为精确 B-Rep，非解析边在二维视图中离散保留，但记录类别供校验。
            points = [_point_on_section(edge.positionAt(i/96), origin) for i in range(97)]
            msp.add_lwpolyline(points, dxfattribs={"layer": "GEOMETRY"})
        count += 1
    msp.add_line((origin[0]-25, origin[1]), (origin[0]+25, origin[1]),
                 dxfattribs={"layer": "CENTER", "linetype": "CENTER2"})
    msp.add_line((origin[0], origin[1]-25), (origin[0], origin[1]+25),
                 dxfattribs={"layer": "CENTER", "linetype": "CENTER2"})
    return {"geometry_count": count, "hatch_faces": 1, "section_area_mm2": round(face.Area(), 7),
            "cut_plane": f"X={x:g}", "source": "exact_brep_section"}


def draw_keyed_shaft(msp, spec, solid):
    """为双键槽阶梯轴选择主视图与两个真实断面，生成可解析尺寸实体。"""
    p = spec.parameters
    x0 = -104.0
    l1, l2, l3 = (p[f"length_{i}"] for i in range(1,4))
    d1, d2, d3 = (p[f"diameter_{i}"] for i in range(1,4))
    x1, x2, x3 = x0+l1, x0+l1+l2, x0+l1+l2+l3
    o_main = (x0, -12)
    views = []
    dimensions = {}
    count = draw_projected(msp, projected_edges(solid, "front"), o_main)
    views.append({"id":"front", "kind":"orthographic", "scale":1,
                  "origin":list(o_main), "geometry_count":count})
    msp.add_line((x0-9,-12),(x3+9,-12),
                 dxfattribs={"layer":"CENTER", "linetype":"CENTER2"})
    for label, sx, c in (("A",p["keyway_A_center"],(-47,93)),
                         ("B",p["keyway_B_center"],(67,93))):
        meta = add_exact_section(msp, solid, sx, c)
        views.append({"id":f"section_{label}{label}", "kind":"section", "scale":1,
                      "origin":list(c), "feature_id": f"keyway_{label}",
                      "source_cut_position_mm": sx, **meta})
        _text(msp, f"{label}-{label} 断面", c[0]-19, c[1]-36, 3.4)
        # 在主视图上标出真实剖切位置；位置对应三维坐标 X=sx。
        xl = x0+sx
        msp.add_line((xl,-42),(xl,22),dxfattribs={"layer":"CENTER","linetype":"CENTER2"})
        _text(msp,label,xl-3,25,3,"CENTER")
        _text(msp,label,xl-3,-42,3,"CENTER")
        radius = (d1 if label == "A" else d3)/2
        w = p[f"keyway_{label}_width"]
        dep = p[f"keyway_{label}_depth"]
        floor_y = c[1]+radius-dep
        top_y = c[1]+radius
        # 槽宽和槽深取自实际零件设计参数，尺寸测量点落在断面槽壁及槽底。
        dimensions["D09" if label=="A" else "D11"] = _dim(
            msp,(c[0]-w/2,floor_y),(c[0]+w/2,floor_y),
            (c[0],c[1]+radius+16),override={"dimdec":0}, tolerance=0.04)
        dimensions["D10" if label=="A" else "D12"] = _dim(
            msp,(c[0],floor_y),(c[0],top_y),
            (c[0]+radius+17,c[1]+radius-dep/2),angle=90,
            override={"dimdec":1,"dimzin":8,"dimtix":0},
            location=(c[0]+radius+29,c[1]+radius+7), leader=True)
    # 主视图轴向尺寸集中在下方，槽长按两个圆头的极限位置标注。
    dimensions["D02"] = _dim(msp,(x0,-32),(x1,-32),((x0+x1)/2,-64))
    dimensions["D03"] = _dim(msp,(x1,-27),(x2,-27),((x1+x2)/2,-64))
    dimensions["D01"] = _dim(msp,(x0,-32),(x3,-24),((x0+x3)/2,-88))
    for label,did,dim_y in (("A","D07",48),("B","D08",45)):
        xc = x0+p[f"keyway_{label}_center"]
        length=p[f"keyway_{label}_length"]
        z=(d1 if label=="A" else d3)/2
        dimensions[did] = _dim(msp,(xc-length/2,-12+z),(xc+length/2,-12+z),
                                (xc,dim_y))
    # 外侧直径归属真实轴段，缩短尺寸线和槽线交叉长度。
    dimensions["D04"] = _shaft_diameter_dim(msp,x_face=x0+6,x_dimension=x0-13,diameter=d1)
    dimensions["D05"] = _shaft_diameter_dim(msp,x_face=x1+26,x_dimension=x1+26,
                                              diameter=d2,tolerance=0.05)
    dimensions["D06"] = _shaft_diameter_dim(msp,x_face=x3-6,x_dimension=x3+15,diameter=d3)
    _datum(msp,-96,30,point=(-93,8))
    _text(msp,"A: ⌀40 基准圆柱面所导出轴线",-105,-105,3)
    _text(msp,"1. 键槽 A/B 槽宽公差 ±0.04；锐边倒钝",-105,-114,3)
    _text(msp,"2. 此图为算法测试样例，配合精度须按实际设计校核",-105,-123,3)
    _text(msp,"主视图",-8,-103,3.4)
    _frame(msp,f"{spec.part_id}  {spec.name}",(-135,-162,270,150))
    return views, dimensions
