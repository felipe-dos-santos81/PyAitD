# SPDX-License-Identifier: GPL-2.0-only
"""Window + ModernGL renderer for camera background images."""
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

    def present_scene(self, background, actor_results, masks, palette, actor_rooms):
        if not hasattr(self, "_actor_layer"):
            self._actor_layer = _ActorLayer(self._ctx, palette)
        self._actor_layer.draw(actor_results, actor_rooms, masks)
        rgba = np.zeros((200, 320, 4), dtype=np.uint8)
        rgba[:, :, :3] = background
        rgba[:, :, 3] = 255
        layer = np.frombuffer(self._actor_layer._tex.read(), dtype=np.uint8).reshape(200, 320, 4).copy()
        alpha = layer[:, :, 3:4].astype("f4") / 255.0
        composite = (layer[:, :, :3].astype("f4") * alpha + rgba[:, :, :3].astype("f4") * (1.0 - alpha)).astype(np.uint8)
        self._ctx.screen.use()  # unbind the actor FBO: M1 quad renders to the window
        self.present(np.ascontiguousarray(composite[:, :, :3]))  # M1 texture is RGB (3 channels)

    def close(self):
        self._vbo.release()
        self._tex.release()
        self._prog.release()
        self._ctx.release()
        pygame.quit()


# ---- actor layer (M2) ----

_ACTOR_VSH = """
#version 330
in vec2 in_pos;
in vec3 in_color;
out vec3 v_color;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
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
        self._fbo = ctx.framebuffer(color_attachments=[self._tex])
        self._palette = palette

    def draw(self, results, actor_rooms, masks):
        self._fbo.use()
        self._fbo.clear(0.0, 0.0, 0.0, 0.0)
        groups = {}
        for result, room in zip(results, actor_rooms):
            groups.setdefault(room, []).append(result)
        for room, room_results in groups.items():
            for result in room_results:
                for prim in result.primitives:
                    color = self._palette[prim.color].astype("f4") / 255.0
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
                        cx, cy = prim.points[0][0], prim.points[0][1]
                        r = prim.size
                        import math
                        for k in range(8):
                            a0 = k * math.pi / 4
                            a1 = (k + 1) * math.pi / 4
                            verts += self._vertex((cx, cy), color)
                            verts += self._vertex((cx + r * math.cos(a0), cy + r * math.sin(a0)), color)
                            verts += self._vertex((cx + r * math.cos(a1), cy + r * math.sin(a1)), color)
                    else:  # point / big point / zixel: 1-2 px quads
                        for p in prim.points:
                            s = 1.0 if prim.type in (2, 7) else 2.0
                            verts += self._point_quad(p, s, color)
                    if verts:
                        buf = self._ctx.buffer(np.array(verts, dtype="f4").tobytes())
                        vao = self._ctx.vertex_array(self._prog, [(buf, "2f 3f", "in_pos", "in_color")])
                        vao.render(mode)
                        buf.release()
                        vao.release()
            # FITD: a viewed room's masks occlude actors in OTHER rooms only
            # (ponytail: FBO-wide erase also clears earlier overlapping actors)
            other_masks = [m for m in masks if m.viewed_room != room]
            if other_masks:
                data = np.frombuffer(self._tex.read(), dtype=np.uint8).reshape(200, 320, 4)
                for mask in other_masks:
                    x1, y1 = max(mask.x1, 0), max(mask.y1, 0)
                    x2, y2 = min(mask.x2, 319), min(mask.y2, 199)
                    region = mask.bitmap[y1 : y2 + 1, x1 : x2 + 1]
                    data[y1 : y2 + 1, x1 : x2 + 1][region == 255] = 0
                self._tex.write(np.ascontiguousarray(data))

    @staticmethod
    def _vertex(p, color):
        x, y = _ndc(p[0], p[1])
        return [x, y, color[0], color[1], color[2]]

    def _point_quad(self, p, size, color):
        x, y = p[0], p[1]
        out = []
        for dx, dy in ((0, 0), (size, 0), (size, size), (0, 0), (size, size), (0, size)):
            nx, ny = _ndc(x + dx, y + dy)
            out += [nx, ny, color[0], color[1], color[2]]
        return out
