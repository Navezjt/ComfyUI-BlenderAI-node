import bpy
import blf
import gpu
import struct
import tempfile
from pathlib import Path
from functools import lru_cache
from mathutils import Vector
from .manager import TaskManager
from ..utils import _T
from ..Linker.linker import DrawRectangle, VecWorldToRegScale, UiScale

FONT_ID = 0


# def get_node_editor(area: bpy.types.Area) -> bpy.types.SpaceNodeEditor:
#     for sp in area.spaces:
#         if sp.type == "NODE_EDITOR":
#             return sp
#     return None
@lru_cache
def load_texture(data: bytes) -> gpu.types.GPUTexture:
    if not data:
        return
    # 解析二进制数据的前4个字节获取事件类型
    event_type = struct.unpack(">I", data[:4])[0]
    # 根据事件类型处理数据
    if event_type != 1:
        return
    # 处理图像类型
    image_type = struct.unpack(">I", data[4:8])[0]
    image_mime = ".png" if image_type == 2 else ".jpeg"
    img_path = Path(tempfile.gettempdir()).joinpath("rviewport").with_suffix(image_mime)
    img_path.write_bytes(data[8:])
    bl_img = bpy.data.images.load(img_path.as_posix())
    gpu_img = gpu.texture.from_image(bl_img)
    bpy.data.images.remove(bl_img)
    img_path.unlink()
    return gpu_img


def display_texture(texture: bytes, loc, size):
    """
    显示图片纹理
    """
    tex = load_texture(texture)
    if not tex:
        return
    loc = loc.copy()
    loc.y += 20
    pos = VecWorldToRegScale(loc)
    from gpu_extras.presets import draw_texture_2d
    w = size
    h = tex.height / tex.width * size
    draw_texture_2d(tex, pos, w, h)


def display_text(text, pos, size=50, color=(0, 0.7, 0.0, 1.0)):
    blf.color(FONT_ID, *color)
    blf.position(FONT_ID, pos[0], pos[1], 0)
    blf.size(FONT_ID, size)
    blf.draw(FONT_ID, text)


def draw_node_process(node: bpy.types.Node, process):
    loc = node.location.copy()
    loc.y += 2
    rect_start = Vector((loc.x, loc.y))
    rect_end = Vector((loc.x + node.width * process, loc.y + 4))
    pos1 = VecWorldToRegScale(rect_start)
    pos2 = VecWorldToRegScale(rect_end)
    DrawRectangle(pos1, pos2, Vector((0, 0.7, 0, .75)))


def calc_size(view2d, d):
    s = 0.1
    bs = d / s
    v1 = view2d.view_to_region(bs, bs, clip=False)
    v2 = view2d.view_to_region(0, 0, clip=False)
    size = (v1[0] - v2[0]) * s * UiScale()
    return size


def draw():
    node_editor = bpy.context.space_data
    view2d = bpy.context.region.view2d
    tree = node_editor.edit_tree
    if not tree or not view2d:
        return
    task = TaskManager.cur_task
    if not task or task.tree != tree:
        return
    vsize = 12
    size = calc_size(view2d, vsize)

    n = task.executing_node
    if not n:
        return
    head = f"[{n.name}] {_T('Executing')}"
    loc = n.location.copy()
    loc.y += 10
    pos = VecWorldToRegScale(loc)
    display_texture(task.binary_message, loc, calc_size(view2d, n.width))
    display_text(head, pos, size, (0, 1, 0.0, 1.0))
    if not task.process:
        return
    v = task.process["value"]
    m = task.process["max"]
    blf.size(FONT_ID, size)
    loc.x += blf.dimensions(FONT_ID, head)[0] / size * vsize
    pos = VecWorldToRegScale(loc)
    display_text(f" {v / m * 100:3.0f}% ", pos, size * 1.5, (1, 1, 0.0, 1.0))
    draw_node_process(n, v / m)


bpy.types.SpaceNodeEditor.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
