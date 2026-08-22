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

    def close(self):
        self._vbo.release()
        self._tex.release()
        self._prog.release()
        self._ctx.release()
        pygame.quit()
