"""工程图可复用的 DXF 尺寸、文本、基准与图框绘制原语。"""

def _text(msp, content, x, y, height=3.2, layer="NOTES"):
    return msp.add_mtext(str(content), dxfattribs={"insert": (x, y), "char_height": height,
                                                  "layer": layer, "style": "CJK"})


def _dim(msp, p1, p2, base, angle=0, text="<>", override=None, location=None, leader=False,
         tolerance=None):
    options = {"dimtxt": 3, "dimasz": 2, "dimexe": 1.5, "dimexo": 1.5,
               "dimtad": 1, "dimdec": 0, "dimlfac": 1, "dimzin": 8}
    if override:
        options.update(override)
    dim = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=text,
                             dxfattribs={"layer": "DIMENSIONS"}, override=options)
    if tolerance is not None:
        dim.set_tolerance(upper=tolerance, lower=tolerance, hfactor=0.75, dec=2)
    if location is not None:
        dim.set_location(location, leader=leader)
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


