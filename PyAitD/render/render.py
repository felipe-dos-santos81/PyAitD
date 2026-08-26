# SPDX-License-Identifier: GPL-2.0-only
"""Window + backend owner: picks GLBackend or falls back to SoftwareBackend,
composites the 320x200 UI canvas over the rendered scene, and presents."""
import logging
from dataclasses import replace

import moderngl
import numpy as np
import pygame

from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.render_soft import SoftwareBackend

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


def _quad_verts(x0, y0, x1, y1, flip_v):
    # y flipped: image row 0 is the top of the screen. A GL-rendered FBO
    # texture (the scene backend's `.texture`) is already bottom-up in GL's
    # convention, so it needs no V flip (flip_v=False); a texture built by
    # uploading a top-down numpy array (the UI canvas, or the software
    # backend's composited frame) does need one (flip_v=True).
    v0, v1 = (1.0, 0.0) if flip_v else (0.0, 1.0)
    return np.array(
        [
            x0, y0, 0.0, v0,
            x1, y0, 1.0, v0,
            x1, y1, 1.0, v1,
            x0, y0, 0.0, v0,
            x1, y1, 1.0, v1,
            x0, y1, 0.0, v1,
        ],
        dtype="f4",
    )


def _rgba(canvas):
    canvas = np.ascontiguousarray(canvas)
    if canvas.shape[2] == 4:
        return canvas
    out = np.empty((canvas.shape[0], canvas.shape[1], 4), np.uint8)
    out[:, :, :3] = canvas
    out[:, :, 3] = 255
    return out


def composite_ui(scene_rgb, ui_canvas):
    if ui_canvas.shape[2] == 3:
        return np.ascontiguousarray(ui_canvas)
    alpha = ui_canvas[:, :, 3:4].astype(np.float32) / 255.0
    out = scene_rgb.astype(np.float32) * (1 - alpha) + ui_canvas[:, :, :3].astype(np.float32) * alpha
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


class Renderer:
    def __init__(self, options=None, width=1280, height=800, title="PyAitD"):
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

        self._ui_tex = self._ctx.texture((IMG_W, IMG_H), 4)
        self._ui_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._scene_tex = self._ctx.texture((IMG_W, IMG_H), 3)  # software path upload
        self._scene_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        x0, y0, x1, y1 = fit_quad(IMG_W, IMG_H, width, height)
        # Two VAOs, opposite UV flips: the GL backend's texture is bottom-up
        # (framebuffer convention, so no V flip), the UI/software-path
        # texture is uploaded top-down (needs a V flip).
        self._vbo_scene = self._ctx.buffer(_quad_verts(x0, y0, x1, y1, flip_v=False).tobytes())
        self._vao_scene = self._ctx.vertex_array(
            self._prog, [(self._vbo_scene, "2f 2f", "in_pos", "in_uv")]
        )
        self._vbo_ui = self._ctx.buffer(_quad_verts(x0, y0, x1, y1, flip_v=True).tobytes())
        self._vao_ui = self._ctx.vertex_array(
            self._prog, [(self._vbo_ui, "2f 2f", "in_pos", "in_uv")]
        )

        self.fallback_notice = None
        self._thumbnail_cache = None
        self._select_backend(options or RenderOptions())

    def _select_backend(self, options):
        # A rebuilt backend starts undrawn: without this reset, a present()
        # landing before the next compose_scene() would show the previous
        # backend's stale thumbnail (the software path's cached-frame fallback
        # in present()).
        self._thumbnail_cache = None
        try:
            self.backend = GLBackend(self._ctx, options)
            self.options = options
        except Exception as exc:
            logging.getLogger("PyAitD.render.render").warning("GL backend unavailable: %s", exc)
            self.backend = SoftwareBackend()
            self.options = replace(options, scale=1)
            self.fallback_notice = "Enhanced rendering unavailable"

    def set_options(self, options):
        if options == self.options:
            return
        if isinstance(self.backend, GLBackend):
            self.backend.release()
        self._select_backend(options)

    def compose_scene(self, frame):
        """Draws `frame` into the active backend.

        Spec fallback: a backend that raises while drawing (not just while
        constructing -- see `_select_backend` above) releases its GL state,
        is swapped for a `SoftwareBackend` at scale 1, and gets one retry.
        A second failure (the fresh SoftwareBackend itself raising) is not
        caught here; there is no further backend left to fall back to.

        Does not compute a thumbnail: that's `scene_thumbnail()`'s job, on
        demand, since most frames (no modal open) never need one -- see the
        finding-1 benchmark in the fix report.
        """
        try:
            self.backend.draw(frame)
        except Exception as exc:
            logging.getLogger("PyAitD.render.render").warning(
                "%s.draw failed, falling back to software: %s",
                type(self.backend).__name__, exc,
            )
            if isinstance(self.backend, GLBackend):
                self.backend.release()
            self.backend = SoftwareBackend()
            self.options = replace(self.options, scale=1)
            self.fallback_notice = "Enhanced rendering unavailable"
            self.backend.draw(frame)
        self._thumbnail_cache = None

    def scene_thumbnail(self):
        """The composed scene as a (200,320,3) uint8 array, computed and
        cached lazily: only the presenters that actually paint it
        (render_inventory, render_game_over) and present()'s software path
        pay for it, and at most once per compose_scene()."""
        if self._thumbnail_cache is None:
            self._thumbnail_cache = self.backend.thumbnail()
        return self._thumbnail_cache

    def present(self, ui_canvas):
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, *pygame.display.get_window_size())
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        if isinstance(self.backend, GLBackend):
            self.backend.texture.use(location=0)
            self._vao_scene.render()  # scene at internal resolution, linear
            self._ui_tex.write(_rgba(ui_canvas).tobytes())
            self._ctx.enable(moderngl.BLEND)
            self._ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self._ui_tex.use(location=0)
            self._vao_ui.render()  # UI at 320x200, nearest, alpha
            self._ctx.disable(moderngl.BLEND)
        else:
            composed = composite_ui(self.scene_thumbnail(), ui_canvas)
            self._scene_tex.write(np.ascontiguousarray(composed).tobytes())
            self._scene_tex.use(location=0)
            self._vao_ui.render()
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

    def close(self):
        if isinstance(self.backend, GLBackend):
            self.backend.release()
        self._ui_tex.release()
        self._scene_tex.release()
        self._vao_scene.release()
        self._vbo_scene.release()
        self._vao_ui.release()
        self._vbo_ui.release()
        self._prog.release()
        self._ctx.release()
        pygame.quit()
