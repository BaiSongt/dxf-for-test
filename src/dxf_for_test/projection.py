"""基于 OCCT 精确 HLR 的正交视图与局部视图投影。"""
from math import atan2, degrees, pi

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

CAMERAS = {
    "top": ((0, 0, 1), (1, 0, 0)),
    "front": ((0, -1, 0), (1, 0, 0)),
    "end": ((-1, 0, 0), (0, -1, 0)),
}


def section_y_zero(shape: cq.Shape) -> cq.Shape:
    """以 Y=0 切开实体，保留 Y>=0 的一半供 A-A 剖面投影。"""
    bb = shape.BoundingBox()
    cutter = cq.Workplane("XY").box(bb.xlen + 100, bb.ylen + 100, bb.zlen + 100,
                                     centered=(True, False, False)).translate(
        ((bb.xmin + bb.xmax) / 2, -(bb.ylen + 100), bb.zmin - 50)).val()
    sectioned = shape.cut(cutter).clean()
    if not sectioned.isValid():
        raise ValueError("剖切后实体无效")
    return sectioned


def projected_edges(shape: cq.Shape, camera: str, visible: bool = True) -> list[cq.Edge]:
    normal, xdir = CAMERAS[camera]
    algo = HLRBRep_Algo()
    algo.Add(shape.wrapped)
    algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal), gp_Dir(*xdir))))
    algo.Update()
    algo.Hide()
    hlr = HLRBRep_HLRToShape(algo)
    compounds = [hlr.VCompound(), hlr.OutLineVCompound()] if visible else [hlr.HCompound()]
    edges = []
    for compound in compounds:
        if not compound.IsNull():
            edges.extend(cq.Shape.cast(compound).Edges())
    return edges


def _arc_angles(edge: cq.Edge, circle) -> tuple[float, float]:
    cx, cy = circle.Location().X(), circle.Location().Y()
    start = edge.startPoint()
    end = edge.endPoint()
    a = degrees(atan2(start.y - cy, start.x - cx)) % 360
    b = degrees(atan2(end.y - cy, end.x - cx)) % 360
    sweep = (b - a) % 360
    target = degrees(edge.Length() / circle.Radius())
    if abs(sweep - target) > abs((360 - sweep) - target):
        a, b = b, a
    return a, b


def edge_bounds(edge: cq.Edge) -> tuple[float, float, float, float]:
    points = [edge.positionAt(i / 24) for i in range(25)]
    return min(p.x for p in points), max(p.x for p in points), min(p.y for p in points), max(p.y for p in points)


def draw_projected(msp, edges: list[cq.Edge], origin: tuple[float, float],
                   scale: float = 1.0, layer: str = "GEOMETRY",
                   clip: tuple[float, float, float, float] | None = None) -> int:
    """只显示来自实际模型的投影曲线；局部详图按原模型窗口选取并放大。"""
    ox, oy = origin
    count = 0
    for edge in edges:
        if edge.Length() < 1e-6:
            continue
        if clip is not None:
            xmin, xmax, ymin, ymax = edge_bounds(edge)
            if xmin < clip[0] - 1e-6 or xmax > clip[1] + 1e-6 or ymin < clip[2] - 1e-6 or ymax > clip[3] + 1e-6:
                continue
        def xy(x, y):
            return (ox + scale * x, oy + scale * y)
        kind = edge.geomType()
        if kind == "LINE":
            a, b = edge.startPoint(), edge.endPoint()
            msp.add_line(xy(a.x, a.y), xy(b.x, b.y), dxfattribs={"layer": layer})
        elif kind == "CIRCLE":
            curve = BRepAdaptor_Curve(edge.wrapped)
            circle = curve.Circle()
            center = xy(circle.Location().X(), circle.Location().Y())
            radius = circle.Radius() * scale
            if abs(edge.Length() - 2 * pi * circle.Radius()) < 1e-5:
                msp.add_circle(center, radius, dxfattribs={"layer": layer})
            else:
                start, end = _arc_angles(edge, circle)
                msp.add_arc(center, radius, start_angle=start, end_angle=end,
                            dxfattribs={"layer": layer})
        else:
            # 对解析投影未覆盖的曲线暂用采样折线表示，并保留准确 STEP 主模型。
            vertices = [xy(*(edge.positionAt(i / 48).toTuple()[:2])) for i in range(49)]
            msp.add_lwpolyline(vertices, dxfattribs={"layer": layer})
        count += 1
    return count