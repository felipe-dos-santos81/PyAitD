# SPDX-License-Identifier: GPL-2.0-only
"""Window + ModernGL renderer for camera background images."""
import math

import moderngl
import numpy as np
import pygame

_VSH = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    v_uv = in_uv;
}
"""

_FSH = """
#version 330
uniform sampler2D tex;
in vec2 v_uv;
out vec4 f_color;
void main() {
    f_color = texture(tex, v_uv);
}
"""

IMG_W, IMG_H = 320, 200


def fit_quad(img_w, img_h, win_w, win_h):
    scale = min(win_w / img_w, win_h / img_h)
    w = img_w * scale / win_w
    h = img_h * scale / win_h
    return (-w, -h, w, h)


class Renderer:
    def __init__(self, width=1280, height=800, title="maitd"):
        pygame.init()
        pygame.display.set_caption(title)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
        )
        self._screen = pygame.display.set_mode((width, height), pygame.OPENGL | pygame.DOUBLEBUF)
        self._ctx = moderngl.create_context()
        self._prog = self._ctx.program(vertex_shader=_VSH, fragment_shader=_FSH)
        self._tex = self._ctx.texture((IMG_W, IMG_H), 3)
        self._tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        x0, y0, x1, y1 = fit_quad(IMG_W, IMG_H, width, height)
        # y flipped: image row 0 is the top of the screen
        verts = np.array(
            [
                x0, y0, 0.0, 1.0,
                x1, y0, 1.0, 1.0,
                x1, y1, 1.0, 0.0,
                x0, y0, 0.0, 1.0,
                x1, y1, 1.0, 0.0,
                x0, y1, 0.0, 0.0,
            ],
            dtype="f4",
        )
        self._vbo = self._ctx.buffer(verts.tobytes())
        self._vao = self._ctx.vertex_array(self._prog, [(self._vbo, "2f 2f", "in_pos", "in_uv")])

    def present(self, image):
        self._tex.write(np.ascontiguousarray(image).astype("uint8").tobytes())
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._tex.use(location=0)
        self._vao.render()
        pygame.display.flip()

    def window_to_logical(self, pos):
        win_w, win_h = pygame.display.get_window_size()
        scale = min(win_w / 320, win_h / 200)
        view_w = 320 * scale
        view_h = 200 * scale
        left = (win_w - view_w) / 2
        top = (win_h - view_h) / 2
        x, y = pos
        if x < left or x >= left + view_w or y < top or y >= top + view_h:
            return None
        return int((x - left) / scale), int((y - top) / scale)

    def _compose_existing_scene(self, background, actor_results, masks, palette,
                                actor_rooms, actor_zvs):
        if not hasattr(self, "_actor_layer"):
            self._actor_layer = _ActorLayer(self._ctx, palette)
        self._actor_layer.draw(actor_results, actor_rooms, masks, actor_zvs=actor_zvs)
        layer = np.frombuffer(self._actor_layer._tex.read(), dtype=np.uint8).reshape(200, 320, 4)
        layer = layer[::-1]  # GL rows are bottom-up; background is top-down
        composite = np.empty((200, 320, 3), dtype=np.uint8)  # M1 texture is RGB
        np.copyto(composite, background)
        np.copyto(composite, layer[:, :, :3], where=layer[:, :, 3:4] != 0)
        self._ctx.screen.use()  # unbind the actor FBO: M1 quad renders to the window
        return composite

    def compose_scene(self, background, actor_results, masks, palette, actor_rooms,
                      actor_zvs):
        return self._compose_existing_scene(
            background, actor_results, masks, palette, actor_rooms, actor_zvs,
        )

    def close(self):
        self._vbo.release()
        self._tex.release()
        self._prog.release()
        self._ctx.release()
        pygame.quit()


# ---- actor layer (M2) ----

_ACTOR_VSH = """
#version 330
in vec3 in_pos;
in vec3 in_color;
out vec3 v_color;
void main() {
    gl_Position = vec4(in_pos, 1.0);
    v_color = in_color;
}
"""

_ACTOR_FSH = """
#version 330
in vec3 v_color;
out vec4 f_color;
void main() {
    f_color = vec4(v_color, 1.0);
}
"""


def _ndc(x, y):
    # 320x200 screen space -> NDC for the actor FBO (y flipped)
    return (x / 320.0 * 2.0 - 1.0, 1.0 - y / 200.0 * 2.0)


class _ActorLayer:
    def __init__(self, ctx, palette):
        self._ctx = ctx
        self._prog = ctx.program(vertex_shader=_ACTOR_VSH, fragment_shader=_ACTOR_FSH)
        self._tex = ctx.texture((320, 200), 4)
        self._depth = ctx.depth_renderbuffer((320, 200))
        self._fbo = ctx.framebuffer(
            color_attachments=[self._tex], depth_attachment=self._depth
        )
        self._palette = palette
        self._palette_f = palette.astype("f4") / 255.0

    def draw(self, results, actor_rooms, masks, actor_zvs=None):
        self._fbo.use()
        self._ctx.enable(moderngl.DEPTH_TEST)
        self._ctx.depth_func = "<="
        # Isolate each actor before masking so an erase cannot punch through
        # actors that were already drawn farther back in the scene.
        composite = np.zeros((200, 320, 4), dtype=np.uint8)
        if actor_zvs is None:
            actor_zvs = [None] * len(results)
        for result, room, zv in zip(results, actor_rooms, actor_zvs):
            self._fbo.clear(0.0, 0.0, 0.0, 0.0)
            for prim in result.primitives:
                color = self._palette_f[prim.color]
                verts = []
                mode = moderngl.TRIANGLES
                if prim.type == 1:  # poly -> triangle fan
                    for i in range(1, len(prim.points) - 1):
                        verts += self._vertex(prim.points[0], color)
                        verts += self._vertex(prim.points[i], color)
                        verts += self._vertex(prim.points[i + 1], color)
                elif prim.type == 0:  # line
                    mode = moderngl.LINES
                    for p in prim.points:
                        verts += self._vertex(p, color)
                elif prim.type == 3:  # sphere: 8-gon fan around center, radius size
                    cx, cy, cz = prim.points[0]
                    r = prim.size
                    for k in range(8):
                        a0 = k * math.pi / 4
                        a1 = (k + 1) * math.pi / 4
                        verts += self._vertex((cx, cy, cz), color)
                        verts += self._vertex((cx + r * math.cos(a0), cy + r * math.sin(a0), cz), color)
                        verts += self._vertex((cx + r * math.cos(a1), cy + r * math.sin(a1), cz), color)
                else:  # point / big point / zixel: 1-2 px quads
                    for p in prim.points:
                        s = 1.0 if prim.type in (2, 7) else 2.0
                        verts += self._point_quad(p, s, color)
                if verts:
                    buf = self._ctx.buffer(np.array(verts, dtype="f4").tobytes())
                    vao = self._ctx.vertex_array(self._prog, [(buf, "3f 3f", "in_pos", "in_color")])
                    vao.render(mode)
                    buf.release()
                    vao.release()
            data = np.frombuffer(self._tex.read(), dtype=np.uint8).reshape(200, 320, 4).copy()
            data = data[::-1]  # mask bitmaps are top-down; GL rows are bottom-up
            active_masks = [m for m in masks if _mask_applies_to_actor(m, room, zv)]
            for mask in active_masks:
                x1, y1 = max(mask.x1, 0), max(mask.y1, 0)
                x2, y2 = min(mask.x2, 319), min(mask.y2, 199)
                region = mask.bitmap[y1 : y2 + 1, x1 : x2 + 1]
                data[y1 : y2 + 1, x1 : x2 + 1][region == 255] = 0
            visible = data[:, :, 3] != 0
            composite[visible] = data[visible]
        self._tex.write(np.ascontiguousarray(composite[::-1]))
        self._ctx.disable(moderngl.DEPTH_TEST)

    @staticmethod
    def _vertex(p, color):
        x, y = _ndc(p[0], p[1])
        z = p[2] / 40960.0
        return [x, y, z, color[0], color[1], color[2]]

    def _point_quad(self, p, size, color):
        x, y, z = p
        out = []
        for dx, dy in ((0, 0), (size, 0), (size, size), (0, 0), (size, size), (0, size)):
            nx, ny = _ndc(x + dx, y + dy)
            out += [nx, ny, z / 40960.0, color[0], color[1], color[2]]
        return out


def _mask_applies_to_actor(mask, actor_room, zv):
    if zv is None or mask.viewed_room != actor_room:
        return False
    x1, x2 = int(zv[0] / 10), int(zv[1] / 10)
    z1, z2 = int(zv[4] / 10), int(zv[5] / 10)
    return any(
        x1 >= zone_x1 and z1 >= zone_z1 and x2 <= zone_x2 and z2 <= zone_z2
        for zone_x1, zone_z1, zone_x2, zone_z2 in mask.test_rects
    )
