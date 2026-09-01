# SPDX-License-Identifier: GPL-2.0-only
"""ModernGL backend: renders a FrameDescription at an integer multiple of
320x200 with per-actor depth, GPU mask-texture erasure and optional shading.

Owns all ModernGL state for the enhanced renderer: this module needs no
window, no pygame display -- it renders into an FBO on whatever context it
is handed (see the `gl_ctx` fixture in tests/conftest.py, and task 8's
Renderer, which owns the actual window/context lifecycle).

A note on the mask implementation: the plan that seeded this task called for
a hardware stencil buffer, but ModernGL's public API (as of the version
pinned by this repo) exposes no combined depth+stencil framebuffer
attachment. Masks are implemented instead as a per-actor R8 "mask texture":
each actor's applicable mask polygons are rasterised at the *internal*
target resolution into a small offscreen FBO, and the actor fragment shader
discards any fragment the mask marks as covered. This is equivalent to a
stencil test for this use case (same polygons, same resolution, reset per
actor) and stays within ModernGL's documented API.
"""
import math

import moderngl
import numpy as np

from PyAitD.engine.space.cos_table import sin_cos
from PyAitD.render.geometry import icosphere
from PyAitD.render.glsl import (
    BG_VSH as _BG_VSH,
    BG_FSH as _BG_FSH,
    ACTOR_VSH as _ACTOR_VSH,
    ACTOR_FSH as _ACTOR_FSH,
    TESS_VSH as _TESS_VSH,
    SCREEN_VSH as _SCREEN_VSH,
    STENCIL_VSH as _STENCIL_VSH,
    STENCIL_FSH as _STENCIL_FSH,
    GBUFFER_FSH as _GBUFFER_FSH,
    SSAO_FSH as _SSAO_FSH,
    SSAO_BLUR_FSH as _SSAO_BLUR_FSH,
    SHADOW_GEOM_VSH as _SHADOW_GEOM_VSH,
    SHADOW_FSH as _SHADOW_FSH,
    SHADOW_CAST_FSH as _SHADOW_CAST_FSH,
    SHADOW_BLUR_FSH as _SHADOW_BLUR_FSH,
    COMPOSITE_FSH as _COMPOSITE_FSH,
)
from PyAitD.render.lighting import (_clamp_downward, light_view_matrix, project_to_plane,
                                    shading_terms, shadow_opacity, SHADOW_MAP_SIZE)
from PyAitD.render.materials import PALETTE_SIZE, PRESETS
from PyAitD.render.plate import dither_arrives_smoothed, softness
from PyAitD.render.render_options import INTEGRATION_STRENGTHS
from PyAitD.render.refine import subpatch
from PyAitD.render.render_options import SMOOTHING_LEVELS
from PyAitD.render.ssao import SSAO_BIAS, SSAO_RADIUS, hemisphere_kernel, noise_rotations
from PyAitD.engine.space.world import SCREEN_CENTER_X, SCREEN_CENTER_Y

W, H = 320, 200

LIGHT_DIR = (-0.3, -0.5, -0.8)
NEAR, FAR = 50.0, 40960.0

_SENTINEL_X = -10000.0
_DEPTH_A = (FAR + NEAR) / (FAR - NEAR)
_DEPTH_B = -2 * FAR * NEAR / (FAR - NEAR)

_SHADING_INDEX = {"flat": 0, "lambert": 1, "smooth": 2}

CONTACT_HEIGHT = 150.0   # FITD units over which the contact term fades, roughly shin height

_SSAO_KERNEL_CAP = 64    # matches SSAO_FSH's `uniform vec3 kernel[64]`

# The ground shadow's penumbra. A light source of angular radius
# SOURCE_ANGLE throws a penumbra `drop * tan(SOURCE_ANGLE)` wide at a point
# whose caster is `drop` units above the plane -- 6 degrees is an indoor
# lamp a few metres off; the sun would be a quarter of one. R_MAX_PER_SCALE
# is the widest radius the blur honours, in pixels per unit of render
# scale, and what the cast shader normalises its radius by.
SOURCE_ANGLE = 6.0
TAN_SOURCE = math.tan(math.radians(SOURCE_ANGLE))
R_MAX_PER_SCALE = 4

# The composite's tap budget: a 9x9 window at the widest. sigma tops out at
# 0.35 * 8 = 2.8 at scale 8 over a classic plate, where +-4 covers 1.4
# sigma; the weights are renormalised by what was actually gathered, so the
# truncation costs sharpness at the tail, never brightness.
MAX_BLUR_RADIUS = 4

# The shadow-map receiver: a vertex is pushed NORMAL_OFFSET world units
# along its normal before it is looked up, and the comparison is biased
# by SHADOW_BIAS_UNITS (scaled by slope) so a surface never shadows itself
# at its own depth. Bodies are 100-400 units across; both are well under a
# limb's thickness.
NORMAL_OFFSET = 6.0
SHADOW_BIAS_UNITS = 4.0
# Clip [-1, 1] -> texture [0, 1] on every axis, folded into light_vp so the
# fragment shader's textureProj reads the map directly.
_SHADOW_BIAS = np.array([[0.5, 0.0, 0.0, 0.5],
                         [0.0, 0.5, 0.0, 0.5],
                         [0.0, 0.0, 0.5, 0.5],
                         [0.0, 0.0, 0.0, 1.0]])


def _set_uniform(prog, name, value):
    """Set `name` if the linker kept it. A program whose stages never read a
    uniform loses it, and ModernGL raises KeyError for a name the program
    lacks -- so every caller that writes one name across programs built
    from different shader pairs goes through here.

    The guard is insurance, not a description of today: measured on this
    driver, no live call site loses a name. `_tess_shadow_prog` (_TESS_VSH
    + _STENCIL_FSH) is the one that could -- its fragment stage reads no
    varying at all, so a linker is free to drop the whole penumbra chain
    and with it `r_max` -- and it happens to keep it here. (`_screen_prog`
    does drop `light_vp` and `normal_offset`, its vertex stage writing
    v_shadow as a constant, but those two names reach it through no path:
    `_set_frame_uniforms` is called only with `_actor_prog` and
    `_tess_prog`.) Write through here whenever the same name is set across
    programs built from different shader pairs."""
    try:
        uniform = prog[name]
    except KeyError:
        return
    if isinstance(value, np.ndarray):
        uniform.write(value.tobytes())
    else:
        uniform.value = value


def _world_box(actor):
    """The eight corners of the box around everything this actor draws --
    posed vertices and sphere extents, in world space. Not the collision
    `zv`: FITD's box stops short of outstretched limbs, and a fragment
    outside the shadow map's box would compare against its edge texel."""
    geometry = actor.geometry
    position = np.asarray(actor.position, np.float64)
    points = [geometry.vertices.astype(np.float64) + position]
    for centre_idx, radius, _color in geometry.spheres:
        centre = geometry.vertices[centre_idx].astype(np.float64) + position
        points.append(centre[None, :] - radius)
        points.append(centre[None, :] + radius)
    pts = np.concatenate(points, axis=0)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return [(float(x), float(y), float(z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


# One instance per source triangle for the tessellating programs: per
# corner k, (pos.xyz, ao), (normal.xyz, straight of edge k -> k+1),
# (rgb, palette index), rest.xyz, uv.xy -- 17 floats, 51 per triangle,
# fifteen packed attributes plus the per-vertex barycentric: 16 of the 16
# slots GL 3.3 guarantees, which is all of them. A further per-corner
# attribute does not fit and must pack into an existing one instead
# (tests/test_render_gl.py pins this).
INSTANCE_FLOATS = 51
_INSTANCE_ATTRIBUTES = ("4f", "4f", "4f", "3f", "2f") * 3
_INSTANCE_NAMES = ("in_p0", "in_n0", "in_c0", "in_r0", "in_uv0",
                   "in_p1", "in_n1", "in_c1", "in_r1", "in_uv1",
                   "in_p2", "in_n2", "in_c2", "in_r2", "in_uv2")


def instance_layout(prog):
    """(format, names) that bind an INSTANCE_FLOATS-wide buffer to `prog`.
    A linker may drop an attribute a program never ends up reading (a
    shadow program discards colour, a transform-feedback test captures two
    varyings), and ModernGL refuses to bind a name the program lacks: a
    dropped attribute becomes padding of the same width, so the buffer's
    stride never changes."""
    present = set(prog)
    tokens, names = [], []
    for name, fmt in zip(_INSTANCE_NAMES, _INSTANCE_ATTRIBUTES):
        if name in present:
            tokens.append(fmt)
            names.append(name)
        else:
            tokens.append(f"{fmt[0]}x4")
    return " ".join(tokens) + "/i", tuple(names)


def rotation_matrix(state):
    """3x3 rotation matching scene.CameraView.camera_space's Y, then X, then
    Z rotation chain (same cos_table.sin_cos formulas, same composition order)."""
    m = np.eye(3)
    if state._use_y:
        s, c = sin_cos(state._use_y)
        m = np.array([[s, 0, -c], [0, 1, 0], [c, 0, s]]) @ m
    if state._use_x:
        s, c = sin_cos(state._use_x)
        m = np.array([[1, 0, 0], [0, s, -c], [0, c, s]]) @ m
    if state._use_z:
        s, c = sin_cos(state._use_z)
        m = np.array([[s, -c, 0], [c, s, 0], [0, 0, 1]]) @ m
    return m


def _view_factors(state):
    """The (rotate, translate) pair, float64 and unrounded, that both
    `camera_matrix` and `view_matrix` are built from.

    One copy of the camera's rotation-and-translation convention, because
    there is no test that can catch the two drifting apart from downstream:
    `view_matrix`'s only consumer is the bump's `dFdx(v_view)`/`dFdy(v_view)`,
    and `k = abs(det) / length(cross(sx, sy))` is invariant to a uniform
    scale on `v_view` while the distance fade reads `fwidth(nc)` rather than
    `v_view` at all -- so a transposed rotation or a scale error would tilt
    or deepen relief with every existing assertion still passing.
    `test_view_matrix_is_camera_matrixs_view_half` pins the relationship
    from the outside as well."""
    translate = np.eye(4)
    translate[:3, 3] = (-state.x, -state.y, -state.z)
    rotate = np.eye(4)
    rotate[:3, :3] = rotation_matrix(state)
    return rotate, translate


def projection_matrix(state):
    """`camera_matrix`'s projection half: the clip-space projection times the
    `depth = z + focal1` shift, before the world -> camera transform.

    Split out so a test can recombine the two halves; `camera_matrix` still
    evaluates exactly `((proj @ shift) @ rotate) @ translate`, which is what
    left-associativity always gave it, so the golden cannot move."""
    proj = np.array([
        [state.focal2 / SCREEN_CENTER_X, 0, 0, 0],
        [0, -state.focal3 / SCREEN_CENTER_Y, 0, 0],
        [0, 0, _DEPTH_A, _DEPTH_B],
        [0, 0, 1.0, 0],
    ])
    shift = np.eye(4)
    shift[2, 3] = state.focal1  # depth = z + focal1 becomes the clip w
    return proj @ shift


def camera_matrix(view, scale):
    """(4,4) float32 view-projection matrix: world-homogeneous @ m.T gives
    clip space (row-vector convention, matching the parity test).

    `scale` is accepted for interface symmetry with the rest of this module
    (and to leave room for a future per-scale tweak) but is not used here:
    NDC is resolution independent, and the internal target's actual pixel
    resolution is applied later by the GL viewport, not by this matrix.
    """
    state = view.state
    rotate, translate = _view_factors(state)
    m = projection_matrix(state) @ rotate @ translate
    return m.astype(np.float32)


def view_matrix(view):
    """(4,4) float32 world -> camera space: `camera_matrix`'s `rotate @
    translate` half, without the projection.

    The fragment shader needs a camera-space *position* to take screen-space
    derivatives of (Mikkelsen's bump needs dP/dx and dP/dy, not a direction),
    and `rot` is rotation only -- it cannot carry the camera's translation.
    Built from the same `_view_factors` as `camera_matrix`, so the two cannot
    disagree about the convention; they are still separate functions because
    the shader wants the view half alone."""
    rotate, translate = _view_factors(view.state)
    return (rotate @ translate).astype(np.float32)


def _to_ndc(sx, sy, depth):
    ndc_x = sx / SCREEN_CENTER_X - 1.0
    ndc_y = 1.0 - sy / SCREEN_CENTER_Y
    ndc_z = _DEPTH_A + _DEPTH_B / depth
    return ndc_x, ndc_y, ndc_z


def _quad_corners(sx, sy, depth, dx, dy):
    # A screen-space quad anchored so (dx, dy) offsets are applied
    # symmetrically for a line segment (perpendicular half-width) or
    # top-left for a point (matching the legacy _point_quad convention).
    c0 = _to_ndc(sx - dx, sy - dy, depth)
    c1 = _to_ndc(sx + dx, sy + dy, depth)
    return c0, c1


def _plane_y(actor):
    """The world y of the ground plane under `actor`: the larger of its
    bounding box's two y bounds, which -- world y grows downward -- is its
    lowest point, the feet. The contact darkening in the scene shader and
    the plane a shadow is projected onto must be the same plane or the
    shadow detaches from the darkening at the feet, so both read it here."""
    return float(max(actor.zv[2], actor.zv[3]))


class GLBackend:
    def __init__(self, ctx, options):
        self._ctx = ctx
        self._options = options
        self.size = (W * options.scale, H * options.scale)
        # Every attribute release() might touch is set to None up front, so
        # a construction failure partway through the allocations below can
        # still be cleaned up by release() (which already tolerates None):
        # without this, an exception here would leak whatever GL objects
        # had already been allocated -- _select_backend's except clause has
        # no live GLBackend reference to release() them through.
        self.texture = None
        self._depth = None
        self._fbo = None
        self.samples = 0
        self._ms_color = None
        self._ms_depth = None
        self._ms_fbo = None
        self._target = None
        self._plate_tex = None
        self._plate_fbo = None
        self._actor_tex = None
        self._actor_fbo = None
        self._composite_prog = None
        self._composite_vao = None
        self._mask_tex = None
        self._mask_fbo = None
        self._shadow_tex = None
        self._shadow_fbo = None
        self._shadow_blur_tex = None
        self._shadow_blur_fbo = None
        self._cast_prog = None
        self._cast_layout = None
        self._blur_prog = None
        self._blur_quad_vao = None
        self._shadow_prog = None
        self._shadow_geom_prog = None
        self._shadow_quad = None
        self._shadow_quad_vao = None
        self._bg_prog = None
        self._actor_prog = None
        self._screen_prog = None
        self._stencil_prog = None
        self._quad = None
        self._quad_vao = None
        self._thumb_tex = None
        self._thumb_fbo = None
        self._thumb_quad = None
        self._thumb_quad_vao = None
        self._bg_tex = None
        self._bg_key = None
        self._bg_src = None
        self._body_tex_cache = {}
        self._sphere = None
        self._material_tex = None
        self._material_key = None
        self._shadow_map = None
        self._shadow_map_fbo = None
        self._tess_prog = None
        self._tess_shadow_prog = None
        self._gbuf_size = None
        self._gbuf_tex = None
        self._gbuf_depth = None
        self._gbuf_fbo = None
        self._gbuf_prog = None
        self._gbuf_layout = None
        self._ssao_tex = None
        self._ssao_fbo = None
        self._ssao_blur_tex = None
        self._ssao_blur_fbo = None
        self._ssao_noise_tex = None
        self._ssao_prog = None
        self._ssao_vao = None
        self._ssao_blur_prog = None
        self._ssao_blur_vao = None
        self._subpatch_bufs = {}
        self._tess_layout = self._tess_shadow_layout = None
        self._released = False
        try:
            self.texture = ctx.texture(self.size, 4)
            self.texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._depth = ctx.depth_renderbuffer(self.size)
            self._fbo = ctx.framebuffer(color_attachments=[self.texture], depth_attachment=self._depth)

            self._mask_tex = ctx.texture(self.size, 1)
            self._mask_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._mask_tex.repeat_x = False
            self._mask_tex.repeat_y = False
            self._mask_fbo = ctx.framebuffer(color_attachments=[self._mask_tex])

            # Two channels: R is coverage, G the penumbra radius the gathered
            # cast writes (a fraction of R_MAX); the hard path writes 1.0 to
            # both and reads only R. The blur ping-pongs between this and
            # _shadow_blur_tex, horizontal then vertical, ending back here.
            self._shadow_tex = ctx.texture(self.size, 2)
            self._shadow_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._shadow_tex.repeat_x = False
            self._shadow_tex.repeat_y = False
            self._shadow_fbo = ctx.framebuffer(color_attachments=[self._shadow_tex])
            self._shadow_blur_tex = ctx.texture(self.size, 2)
            self._shadow_blur_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._shadow_blur_tex.repeat_x = False
            self._shadow_blur_tex.repeat_y = False
            self._shadow_blur_fbo = ctx.framebuffer(color_attachments=[self._shadow_blur_tex])
            self._shadow_geom_prog = ctx.program(
                vertex_shader=_SHADOW_GEOM_VSH, fragment_shader=_STENCIL_FSH)
            self._shadow_prog = ctx.program(
                vertex_shader=_STENCIL_VSH, fragment_shader=_SHADOW_FSH)
            # A full-target triangle pair in NDC. `_quad` cannot be reused:
            # it carries interleaved UVs the shadow composite has no
            # attribute for.
            shadow_quad = np.array([
                -1, -1,  1, -1,  1, 1,
                -1, -1,  1,  1, -1, 1,
            ], dtype="f4")
            self._shadow_quad = ctx.buffer(shadow_quad.tobytes())
            self._shadow_quad_vao = ctx.vertex_array(
                self._shadow_prog, [(self._shadow_quad, "2f", "in_pos")])
            self._blur_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=_SHADOW_BLUR_FSH)
            self._blur_quad_vao = ctx.vertex_array(
                self._blur_prog, [(self._shadow_quad, "2f", "in_pos")])

            self._bg_prog = ctx.program(vertex_shader=_BG_VSH, fragment_shader=_BG_FSH)
            self._actor_prog = ctx.program(vertex_shader=_ACTOR_VSH, fragment_shader=_ACTOR_FSH)
            self._screen_prog = ctx.program(vertex_shader=_SCREEN_VSH, fragment_shader=_ACTOR_FSH)
            self._screen_prog["shading"].value = 0  # lines/points are never shaded
            self._screen_prog["lighting"].value = 0
            self._stencil_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=_STENCIL_FSH)

            # 256 palette indices x 3 rows of 4 float parameters; uploaded
            # whenever an actor hands over a table object we have not seen.
            self._material_tex = ctx.texture((PALETTE_SIZE, 3), 4, dtype="f4")
            self._material_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

            # The light-view depth map every actor is rendered into under
            # shadows=soft. compare_func turns sampling into a depth test the
            # hardware bilinearly filters (2x2 PCF); LINEAR is what makes
            # that filtering happen. Depth-only: no colour attachment.
            self._shadow_map = ctx.depth_texture((SHADOW_MAP_SIZE, SHADOW_MAP_SIZE))
            self._shadow_map.compare_func = "<="
            self._shadow_map.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._shadow_map.repeat_x = False
            self._shadow_map.repeat_y = False
            self._shadow_map_fbo = ctx.framebuffer(depth_attachment=self._shadow_map)
            for prog in (self._actor_prog, self._screen_prog):
                _set_uniform(prog, "shadow_map", 4)
                _set_uniform(prog, "self_shadow", 0)

            quad = np.array([
                -1, -1, 0, 1,
                 1, -1, 1, 1,
                 1,  1, 1, 0,
                -1, -1, 0, 1,
                 1,  1, 1, 0,
                -1,  1, 0, 0,
            ], dtype="f4")
            self._quad = ctx.buffer(quad.tobytes())
            self._quad_vao = ctx.vertex_array(self._bg_prog, [(self._quad, "2f 2f", "in_pos", "in_uv")])

            # thumbnail()'s GPU box-average downsample target: a fixed
            # 320x200 RGB FBO the internal target is blitted into.
            self._thumb_tex = ctx.texture((W, H), 3)
            self._thumb_fbo = ctx.framebuffer(color_attachments=[self._thumb_tex])
            # A separate quad with an *identity* UV mapping (no V flip):
            # `._quad`/`._quad_vao` above are for `_draw_background`, which
            # samples a CPU-uploaded, top-down source texture and needs a
            # flip to land right-side-up in NDC. `.texture` here is a
            # GL-rendered FBO texture instead (bottom-up, like `read_rgb`
            # flips *from*) -- blitting it into another GL-native FBO
            # (`_thumb_fbo`) with no flip keeps both buffers in the same
            # bottom-up convention, exactly like render.py's `_vao_scene`
            # (flip_v=False) versus `_vao_ui` (flip_v=True).
            thumb_quad = np.array([
                -1, -1, 0, 0,
                 1, -1, 1, 0,
                 1,  1, 1, 1,
                -1, -1, 0, 0,
                 1,  1, 1, 1,
                -1,  1, 0, 1,
            ], dtype="f4")
            self._thumb_quad = ctx.buffer(thumb_quad.tobytes())
            self._thumb_quad_vao = ctx.vertex_array(
                self._bg_prog, [(self._thumb_quad, "2f 2f", "in_pos", "in_uv")])

            # `_draw_frame` renders exclusively through `self._target`, never
            # `self._fbo`, directly. `self._fbo` itself is still named
            # directly only where it is genuinely the single-sampled result
            # -- allocation above, `release()`, and the resolve target below.

            # A driver that supports fewer samples than asked gets what it
            # has rather than an exception: msaa is a quality knob, not a
            # requirement, and _select_backend would otherwise drop the
            # whole GL path to software over it.
            self.samples = min(options.msaa, ctx.max_samples) if options.msaa else 0
            if self.samples:
                self._ms_color = ctx.renderbuffer(self.size, 4, samples=self.samples)
                self._ms_depth = ctx.depth_renderbuffer(self.size, samples=self.samples)
                self._ms_fbo = ctx.framebuffer(
                    color_attachments=[self._ms_color], depth_attachment=self._ms_depth)
            self._target = self._ms_fbo or self._fbo

            # The two halves a non-zero integration splits the frame into. Both
            # are the target's own size and format, so a resolve into either
            # is the same copy_framebuffer the single-target path already
            # does. _actor_fbo shares `_depth` with `_fbo` rather than
            # allocating a second one: the two are never both the render
            # target, and the composite that writes through `_fbo` runs with
            # the depth test disabled.
            self._plate_tex = ctx.texture(self.size, 4)
            self._plate_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._plate_tex.repeat_x = False
            self._plate_tex.repeat_y = False
            self._plate_fbo = ctx.framebuffer(color_attachments=[self._plate_tex])
            self._actor_tex = ctx.texture(self.size, 4)
            self._actor_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._actor_tex.repeat_x = False
            self._actor_tex.repeat_y = False
            self._actor_fbo = ctx.framebuffer(
                color_attachments=[self._actor_tex], depth_attachment=self._depth)
            self._composite_prog = ctx.program(
                vertex_shader=_STENCIL_VSH, fragment_shader=_COMPOSITE_FSH)
            _set_uniform(self._composite_prog, "plate_tex", 5)
            _set_uniform(self._composite_prog, "actor_tex", 6)
            self._composite_vao = ctx.vertex_array(
                self._composite_prog, [(self._shadow_quad, "2f", "in_pos")])

            # The tessellating programs and their sub-patch buffers exist
            # whatever `smoothing` says: the option is a per-frame choice
            # (Renderer.set_options rebuilds the backend anyway), and
            # compiling at construction is how every other program fails
            # over to the software backend when a driver rejects it.
            self._tess_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_ACTOR_FSH)
            _set_uniform(self._tess_prog, "shadow_map", 4)
            _set_uniform(self._tess_prog, "self_shadow", 0)
            self._tess_shadow_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_STENCIL_FSH)
            # Seeded on the shadow program, not _tess_prog: _tess_prog always
            # writes project=0 itself (_draw_actor_tessellated), so travel is
            # never read there. _tess_shadow_prog is the one that will set
            # project=1 (task 6); an unseeded uniform defaults to (0,0,0) and
            # divides by zero (travel.y) if that write is ever missed.
            self._tess_shadow_prog["travel"].value = (0.0, 1.0, 0.0)
            # And the penumbra divisor the cast branch added to that same
            # branch: _tess_shadow_prog runs it with project=1 as well, and
            # an unseeded r_max is 0, so v_penumbra would evaluate 0.0 / 0.0
            # -- unspecified per the GLSL spec -- on every vertex. Nothing
            # reads it there today (_STENCIL_FSH declares no v_penumbra), so
            # a linker is free to drop the uniform outright -- which is
            # exactly what _set_uniform exists to absorb.
            _set_uniform(self._tess_shadow_prog, "r_max", 1.0)
            self._tess_layout = instance_layout(self._tess_prog)
            self._tess_shadow_layout = instance_layout(self._tess_shadow_prog)
            # The gathered cast: _TESS_VSH in project mode, writing coverage
            # and penumbra radius. Seeded like _tess_shadow_prog so an unset
            # travel can never divide by zero.
            self._cast_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_SHADOW_CAST_FSH)
            self._cast_prog["travel"].value = (0.0, 1.0, 0.0)
            self._cast_layout = instance_layout(self._cast_prog)

            # The SSAO prepass: every actor once, into its own half-resolution
            # normal+depth buffer. Half resolution because SSAO is a
            # low-frequency term and the blur in _blur_ssao bounds the
            # haloing that costs -- the spec names this trade explicitly as
            # a limitation.
            self._gbuf_size = (max(1, self.size[0] // 2), max(1, self.size[1] // 2))
            self._gbuf_tex = ctx.texture(self._gbuf_size, 4, dtype="f2")
            # NEAREST, not the LINEAR Task 3 shipped this as (no test
            # exercised `texture()` sampling of it, only `.read()` of the
            # raw texels, so nothing pinned the choice): SSAO_FSH samples
            # neighbouring pixels' depth to decide whether they occlude the
            # centre one, and ssao_reference does that with a plain integer
            # index, never a blend. LINEAR here silently bilinear-filters
            # depth *across* whatever silhouette the two samples straddle,
            # producing a value neither surface actually has -- measured
            # against test_the_ssao_pass_matches_the_numpy_twin's adversarial
            # per-pixel-random G-buffer: LINEAR put the twin comparison's max
            # difference at 0.576 (a wall away from the pinned 4/255);
            # NEAREST brings it to 0.064, matching (to within GPU-vs-numpy
            # floating point noise the twin's own algorithm is not immune to
            # -- see the task-4 report) the same discrete indexing the twin
            # performs.
            self._gbuf_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._gbuf_tex.repeat_x = self._gbuf_tex.repeat_y = False
            self._gbuf_depth = ctx.depth_renderbuffer(self._gbuf_size)
            self._gbuf_fbo = ctx.framebuffer(color_attachments=[self._gbuf_tex],
                                             depth_attachment=self._gbuf_depth)
            # Cleared at construction too, not only per-pass in
            # _render_gbuffer: a caller that reads `._gbuf_tex` before the
            # first draw() (or under occlusion="off", which never runs the
            # pass at all) must see the same "nothing drawn" alpha-0.0 the
            # texture's undefined initial GPU memory would not guarantee.
            self._gbuf_fbo.clear(0.0, 0.0, 0.0, 0.0)
            self._gbuf_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_GBUFFER_FSH)
            # Seeded like _tess_shadow_prog and _cast_prog: this program
            # always runs with project=0 (_render_gbuffer sets it every
            # pass), so travel.y is never actually divided by, but an
            # unseeded uniform is insurance against that changing later.
            _set_uniform(self._gbuf_prog, "travel", (0.0, 1.0, 0.0))
            self._gbuf_layout = instance_layout(self._gbuf_prog)

            # The two SSAO passes: half-resolution R8 ping-pong, over the
            # G-buffer the block above builds. _ssao_tex is what the actor
            # programs sample; _blur_ssao's ping-pong swap keeps that name
            # pointed at whichever texture holds the latest blurred result.
            self._ssao_tex = ctx.texture(self._gbuf_size, 1)
            self._ssao_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._ssao_tex.repeat_x = self._ssao_tex.repeat_y = False
            self._ssao_fbo = ctx.framebuffer(color_attachments=[self._ssao_tex])
            self._ssao_blur_tex = ctx.texture(self._gbuf_size, 1)
            self._ssao_blur_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._ssao_blur_tex.repeat_x = self._ssao_blur_tex.repeat_y = False
            self._ssao_blur_fbo = ctx.framebuffer(color_attachments=[self._ssao_blur_tex])
            rot = noise_rotations()
            self._ssao_noise_tex = ctx.texture((rot.shape[1], rot.shape[0]), 2, dtype="f2")
            self._ssao_noise_tex.write(np.ascontiguousarray(rot.astype(np.float16)).tobytes())
            self._ssao_noise_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            # The one texture in this backend that should tile: the noise
            # rotation repeats over the whole screen, which is exactly what
            # makes `gl_FragCoord.xy / 4.0` in SSAO_FSH sample it correctly.
            self._ssao_noise_tex.repeat_x = self._ssao_noise_tex.repeat_y = True
            self._ssao_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=_SSAO_FSH)
            self._ssao_vao = ctx.vertex_array(self._ssao_prog, [(self._shadow_quad, "2f", "in_pos")])
            self._ssao_blur_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=_SSAO_BLUR_FSH)
            self._ssao_blur_vao = ctx.vertex_array(self._ssao_blur_prog,
                                                   [(self._shadow_quad, "2f", "in_pos")])
            kernel = hemisphere_kernel()
            # ModernGL's uniform writer rejects a length that does not match
            # the shader's declared array size exactly (measured: "invalid
            # uniform size" writing SSAO_KERNEL_SIZE=16 vec3s into
            # SSAO_FSH's kernel[64]) -- unlike a plain glUniform3fv call,
            # which accepts a shorter count. Padded to _SSAO_KERNEL_CAP with
            # zeros to satisfy that, harmlessly: the shader loop only reads
            # the first kernel_count entries.
            padded_kernel = np.zeros((_SSAO_KERNEL_CAP, 3), dtype=np.float32)
            padded_kernel[: len(kernel)] = kernel
            _set_uniform(self._ssao_prog, "kernel", tuple(map(tuple, padded_kernel)))
            _set_uniform(self._ssao_prog, "kernel_count", len(kernel))
            _set_uniform(self._ssao_prog, "radius", SSAO_RADIUS)
            _set_uniform(self._ssao_prog, "bias", SSAO_BIAS)

            # Every level, 0 included: subpatch(0) is the flat triangle with
            # exact corners, so the soft-shadow passes can draw every actor
            # through the instanced programs whatever `smoothing` says.
            for level in SMOOTHING_LEVELS:
                self._subpatch_bufs[level] = ctx.buffer(np.ascontiguousarray(subpatch(level), dtype="f4").tobytes())

            self._sphere = icosphere(1)
        except Exception:
            self.release()
            raise

    def release(self):
        # `self._target` is intentionally absent: it aliases `self._ms_fbo`,
        # `self._fbo`, `self._plate_fbo` or `self._actor_fbo` depending on
        # the integration level and the frame phase, and each of those is
        # released below under its own name. Releasing it a second time
        # through `self._target` would be a double-release of the same GL
        # object.
        for resource in (
            self._quad_vao, self._quad,
            self._thumb_quad_vao, self._thumb_quad,
            self._stencil_prog, self._screen_prog, self._actor_prog, self._bg_prog,
            self._material_tex,
            self._shadow_map_fbo, self._shadow_map,
            self._tess_prog, self._tess_shadow_prog, *self._subpatch_bufs.values(),
            self._gbuf_prog, self._gbuf_fbo, self._gbuf_tex, self._gbuf_depth,
            self._ssao_prog, self._ssao_fbo, self._ssao_tex,
            self._ssao_blur_prog, self._ssao_blur_fbo, self._ssao_blur_tex, self._ssao_noise_tex,
            # All five VAOs are built on `_shadow_quad`, so all five come
            # before it: every other pair in this tuple frees the VAO ahead of its
            # buffer, and deleting a buffer does not unbind it from a VAO
            # that is not current. (_ssao_tex/_ssao_blur_tex may have swapped
            # GL objects an odd number of times via _blur_ssao's ping-pong --
            # harmless here, since both attribute names are released either
            # way, whichever underlying object each currently points at.)
            self._shadow_quad_vao, self._blur_quad_vao, self._composite_vao,
            self._ssao_vao, self._ssao_blur_vao, self._shadow_quad,
            self._blur_prog, self._cast_prog,
            self._shadow_prog, self._shadow_geom_prog,
            self._shadow_fbo, self._shadow_tex,
            self._shadow_blur_fbo, self._shadow_blur_tex,
            self._composite_prog, self._plate_fbo, self._plate_tex, self._actor_fbo, self._actor_tex,
            self._mask_fbo, self._mask_tex,
            self._thumb_fbo, self._thumb_tex,
            self._ms_fbo, self._ms_color, self._ms_depth,
            self._fbo, self._depth, self.texture,
            self._bg_tex,
        ):
            if resource is not None:
                resource.release()
        for tex, _pixels in self._body_tex_cache.values():
            tex.release()
        self._bg_tex = None
        self._bg_key = None
        self._material_key = None
        self._bg_src = None
        self._body_tex_cache = {}
        self._released = True

    # ---- per-frame drawing ----

    def draw(self, frame):
        """Renders `frame` into `.texture`.

        Postcondition: the context's viewport, depth_func, blend state and
        previously-bound framebuffer are restored before returning
        (best-effort for depth_func and blend_func, which ModernGL exposes
        write-only, with no way to read back what a caller had set before
        `draw()` ran: each is reset to its own default -- depth_func to
        "<", blend_func to moderngl.DEFAULT_BLENDING -- and BLEND itself is
        disabled, matching a fresh context's state), so a caller sharing
        this `ctx` -- task 8's Renderer -- is not left with our internal
        FBO, scratch viewport or shadow-compositing blend state bound.
        """
        if self._released:
            # render.Renderer.compose_scene's draw-failure fallback releases
            # a GLBackend and swaps in a SoftwareBackend; a caller still
            # holding the old, now-released GLBackend must get a clear error
            # here rather than an opaque moderngl.InvalidObject failure deep
            # inside a GL call.
            raise RuntimeError("GLBackend.draw() called after release()")
        prev_viewport = self._ctx.viewport
        prev_fbo = self._ctx.fbo
        try:
            self._draw_frame(frame)
        finally:
            self._ctx.viewport = prev_viewport
            self._ctx.depth_func = "<"  # ModernGL's own default
            self._ctx.disable(moderngl.BLEND)
            self._ctx.blend_func = moderngl.DEFAULT_BLENDING  # ModernGL's own default
            self._ctx.blend_equation = moderngl.FUNC_ADD  # the gathered cast blends with MAX
            # Best-effort: prev_fbo can have been release()'d by another
            # backend sharing this ctx between when we captured it and now
            # (moderngl.InvalidObject`d, not cleared) -- restoring a dead
            # framebuffer isn't recoverable, so just leave ours bound.
            if prev_fbo is not None and not isinstance(prev_fbo.mglo, moderngl.InvalidObject):
                prev_fbo.use()

    def _draw_frame(self, frame):
        scene_lit = self._options.lighting == "scene"
        soft = scene_lit and self._options.shadows == "soft"
        level = self._options.smoothing
        # Under lighting="scene" only: `fixed` runs the single-target path
        # byte for byte whatever `integration` says.
        integrate = scene_lit and self._options.integration > 0
        self._target = (self._ms_fbo or self._plate_fbo) if integrate \
            else (self._ms_fbo or self._fbo)
        self._target.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.disable(moderngl.BLEND)
        self._target.color_mask = (True, True, True, True)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)

        self._draw_background(frame.background)

        mvp = camera_matrix(frame.camera, self._options.scale)
        view_m = view_matrix(frame.camera)
        for prog in (self._actor_prog, self._tess_prog, self._tess_shadow_prog, self._cast_prog,
                     self._gbuf_prog):
            _set_uniform(prog, "view", np.ascontiguousarray(view_m.T))
        rot = rotation_matrix(frame.camera.state).astype("f4")
        travel = None
        if scene_lit:
            # rotation_matrix maps world -> camera and is orthonormal, so
            # its transpose maps back. `direction` points toward the light;
            # light travels the other way. Computed only here so the
            # byte-for-byte `fixed` escape hatch never touches frame.light.
            travel = -(rot.astype(np.float64).T
                       @ np.asarray(frame.light.direction, np.float64))
            self._material_tex.use(location=3)

        palette = frame.palette.astype("f4") / 255.0
        mask_by_id = {mask.id: mask for mask in frame.masks}

        # One instance buffer per actor for the whole frame, built before
        # the loop: the soft-shadow passes read every actor's before any
        # body is drawn, so they cannot be built per actor. Under hard
        # shadows at level 0 nothing is built, as before. Released in the
        # `finally` so a raise anywhere below cannot leak one.
        instances = [None] * len(frame.actors)
        try:
            if level or soft:
                for i, actor in enumerate(frame.actors):
                    data = self._instance_data(actor.geometry, np.asarray(actor.position, np.float64), palette)
                    if len(data):
                        instances[i] = (self._ctx.buffer(data.tobytes()), len(data))

            ssao_on = scene_lit and self._options.occlusion == "ssao"
            if ssao_on:
                self._render_gbuffer(frame, instances, level)
                self._render_ssao(frame)
                self._blur_ssao()
            # Bound and set unconditionally, like the shadow map below
            # whatever `shadows` says: a sampler left unbound reads
            # undefined data if a driver ever mispredicts the branch, and
            # `occlusion_on` is what makes the value irrelevant rather than
            # the binding.
            self._ssao_tex.use(location=7)
            for prog in (self._actor_prog, self._tess_prog, self._screen_prog):
                _set_uniform(prog, "ssao_tex", 7)
                _set_uniform(prog, "occlusion_on", 1 if ssao_on else 0)

            shadow = None
            if soft:
                shadow = self._render_shadow_map(frame, instances, travel, level)
            # After _render_shadow_map, never before: for the length of that
            # pass _shadow_map is _shadow_map_fbo's depth attachment, and
            # binding a texture to a unit while it is the current
            # framebuffer's attachment is the shape of a feedback loop.
            # Harmless as written -- the program that pass runs declares no
            # sampler, so nothing ever reads it -- but it is the kind of
            # binding a GL debug layer flags, and there is no reason to make
            # it. Bound whatever `shadows` says: every actor program declares
            # the sampler, and a sampler bound to no texture is undefined
            # even on the branch that never reads it.
            self._shadow_map.use(location=4)
            self._set_frame_uniforms(self._actor_prog, frame, mvp, rot, scene_lit, shadow)
            if level:
                self._set_frame_uniforms(self._tess_prog, frame, mvp, rot, scene_lit, shadow)
            self._screen_prog["target_size"].value = self.size

            if soft:
                self._gather_shadows(frame, instances, mask_by_id, travel, mvp, rot, level)
            elif integrate and scene_lit:
                # The hard casts have to reach the *plate* layer, so under
                # `on` they all run here, before any body, instead of
                # interleaved in the loop below. _composite_shadow blends
                # (DST_COLOR, ZERO): on a transparent actor layer it would
                # scale (0,0,0,0) by a factor -- producing nothing -- while
                # darkening every body already drawn. Running them here also
                # retires, for this path only, the ordering caveat in
                # _composite_shadow's docstring.
                for actor, inst in zip(frame.actors, instances):
                    self._cast_hard_shadow(actor, inst, mask_by_id, frame, travel, mvp, level)

            if integrate:
                self._resolve_into(self._plate_fbo)
                self._target = self._ms_fbo or self._actor_fbo
                self._target.use()
                self._ctx.viewport = (0, 0, *self.size)
                self._ctx.disable(moderngl.DEPTH_TEST)
                self._ctx.disable(moderngl.BLEND)
                self._target.color_mask = (True, True, True, True)
                # Transparent, not opaque black: the actor shader writes
                # alpha 1, so what survives the resolve is coverage.
                self._ctx.clear(0.0, 0.0, 0.0, 0.0)

            for actor, inst in zip(frame.actors, instances):
                masks = [mask_by_id[i] for i in actor.mask_ids if i in mask_by_id]
                self._rasterize_masks(masks)  # switches to the mask FBO and disables depth test

                if scene_lit and not soft and not integrate:
                    self._cast_hard_shadow(actor, inst, mask_by_id, frame, travel, mvp, level)

                self._target.use()
                self._ctx.viewport = (0, 0, *self.size)
                self._ctx.enable(moderngl.DEPTH_TEST)
                self._ctx.depth_func = "<="
                # A fresh depth buffer per actor: within one actor's own
                # primitives, depth decides what's in front; across actors,
                # later draws simply paint over earlier ones (painter's order).
                self._target.color_mask = (False, False, False, False)
                self._target.clear(depth=1.0)
                self._target.color_mask = (True, True, True, True)
                # Framebuffer.clear() leaves moderngl's colour-mask state
                # desynced from the GL binding point: re-`use()` the target so
                # the restored mask actually takes effect before the next
                # render.
                self._target.use()

                self._mask_tex.use(location=1)
                self._actor_prog["mask_tex"].value = 1
                self._screen_prog["mask_tex"].value = 1
                if level:
                    self._tess_prog["mask_tex"].value = 1

                if scene_lit:
                    self._actor_prog["plane_y"].value = _plane_y(actor)
                    if level:
                        self._tess_prog["plane_y"].value = _plane_y(actor)
                    self._upload_materials(actor.materials)
                if level:
                    self._draw_actor_tessellated(actor, frame, palette, inst, level)
                else:
                    self._draw_actor(actor, frame, palette)
                self._ctx.disable(moderngl.DEPTH_TEST)
        finally:
            for inst in instances:
                if inst is not None:
                    inst[0].release()

        if integrate:
            self._resolve_into(self._actor_fbo)
            self._composite(frame)
        elif self._ms_fbo is not None:
            # Resolves the multisample buffer down into `.texture`, which is
            # what read_rgb, thumbnail and Renderer all read.
            self._ctx.copy_framebuffer(self._fbo, self._ms_fbo)

    def _set_frame_uniforms(self, prog, frame, mvp, rot, scene_lit, shadow=None):
        """Everything an actor program needs once per frame. Shared by
        _actor_prog and _tess_prog so the two can never disagree about the
        light; the values are exactly what _draw_frame set inline before.
        `shadow` is _render_shadow_map's (light_vp, depth_bias) under
        shadows=soft, else None -- which leaves self_shadow at 0 and the
        classic expression untouched."""
        prog["mvp"].write(mvp.T.tobytes())
        prog["rot"].write(rot.T.tobytes())
        prog["shading"].value = _SHADING_INDEX[self._options.shading]
        if scene_lit:
            key_tint, fill_tint = shading_terms(frame.light)
            prog["lighting"].value = 1
            prog["light"].value = tuple(float(v) for v in frame.light.direction)
            prog["key_tint"].value = tuple(float(v) for v in key_tint)
            prog["fill_tint"].value = tuple(float(v) for v in fill_tint)
            preset = PRESETS[self._options.realism]
            prog["preset_a"].value = (preset.spec, preset.rim, preset.ao)
            prog["preset_b"].value = (preset.contact, preset.detail, preset.hemisphere)
            _set_uniform(prog, "preset_c", (preset.bump, preset.sss, preset.emissive))
            prog["contact_height"].value = CONTACT_HEIGHT
            prog["material_tex"].value = 3
        else:
            prog["lighting"].value = 0
            prog["light"].value = LIGHT_DIR
            prog["key_tint"].value = (0.0, 0.0, 0.0)
            prog["fill_tint"].value = (0.0, 0.0, 0.0)
            prog["preset_a"].value = (0.0, 0.0, 0.0)
            prog["preset_b"].value = (0.0, 0.0, 0.0)
            _set_uniform(prog, "preset_c", (0.0, 0.0, 0.0))
        if shadow is not None:
            light_vp, depth_bias = shadow
            _set_uniform(prog, "self_shadow", 1)
            _set_uniform(prog, "light_vp", light_vp)
            _set_uniform(prog, "depth_bias", depth_bias)
            _set_uniform(prog, "normal_offset", NORMAL_OFFSET)
        else:
            _set_uniform(prog, "self_shadow", 0)
        prog["target_size"].value = self.size

    def _instance_data(self, geometry, position, palette):
        """(M', INSTANCE_FLOATS) float32, one row per triangle -- the body's
        triangles then the expanded sphere triangles -- in _INSTANCE_ATTRIBUTES'
        layout. The same numbers _triangle_data gathers, one triangle per row."""
        rows = []
        if len(geometry.tris):
            idx = geometry.tris
            pos = geometry.vertices[idx].astype(np.float64) + position          # (M,3,3)
            ao = geometry.ao[idx][:, :, None]                                   # (M,3,1)
            normal = geometry.corner_normals.astype(np.float64)                 # (M,3,3)
            straight = geometry.straight[:, :, None]                            # (M,3,1)
            col = np.repeat(palette[geometry.tri_colors][:, None, :], 3, axis=1)   # (M,3,3)
            index = np.repeat(geometry.tri_colors.astype("f4")[:, None, None], 3, axis=1)   # (M,3,1)
            rest = geometry.rest[idx]                                           # (M,3,3)
            uv = (np.zeros((len(idx), 3, 2), "f4") if geometry.uv is None
                  else geometry.uv.astype("f4"))                                # (M,3,2)
            rows.append(np.concatenate([pos, ao, normal, straight, col, index, rest, uv], axis=2).reshape(len(idx), INSTANCE_FLOATS))
        if geometry.spheres:
            sphere_verts, sphere_tris = self._sphere   # cached, lru_cache-shared: never mutated
            unit = sphere_verts[sphere_tris].astype(np.float64)                 # (80,3,3) fancy-indexed copy
            m = len(unit)
            for centre_idx, radius, color in geometry.spheres:
                centre = geometry.vertices[centre_idx].astype(np.float64) + position
                pos = unit * radius + centre
                # rest = the sphere's own surface about its rest centre, so
                # grain is fixed to the ball; ao = open; the unit vectors
                # are exact sphere normals, which is what lets PN round an
                # 80-triangle icosphere into a sphere; no edge is a crease
                rest = unit * radius + geometry.rest[centre_idx]
                rows.append(np.concatenate([
                    pos, np.ones((m, 3, 1)), unit, np.zeros((m, 3, 1)),
                    np.tile(palette[color], (m, 3, 1)), np.full((m, 3, 1), float(color)), rest,
                    np.full((m, 3, 2), -1.0),   # spheres share this buffer and stay untextured
                ], axis=2).reshape(m, INSTANCE_FLOATS))
        if not rows:
            return np.zeros((0, INSTANCE_FLOATS), dtype="f4")
        return np.ascontiguousarray(np.concatenate(rows, axis=0), dtype="f4")

    def _render_instanced(self, prog, layout, buf, count, level):
        fmt, names = layout
        vao = self._ctx.vertex_array(prog, [
            (self._subpatch_bufs[level], "3f", "in_bary"),
            (buf, fmt, *names),
        ])
        vao.render(moderngl.TRIANGLES, vertices=3 * 4 ** level, instances=count)
        vao.release()

    def _draw_actor_tessellated(self, actor, frame, palette, instances, level):
        if instances is not None:
            self._tess_prog["project"].value = 0
            geometry = actor.geometry
            texture = self._body_texture(actor.texture)
            # geometry.uv is None both when the body is genuinely unpainted
            # and when BodyGeometry.__post_init__ dropped a mismatched
            # sidecar back to None (a stale triangulation hash, or a paint
            # copied from another body number) -- either way there are no
            # real per-corner UVs to sample, so treat it exactly like
            # "unpainted" rather than sampling every corner at (0, 0).
            textured = (texture is not None and geometry.uv is not None
                        and self._options.realism != "classic")
            if textured:
                # unit 5: shared with the composite's plate texture
                # (_plate_tex.use(location=5) below); each pass rebinds it
                # before sampling, so the two never collide within a frame
                texture.use(5)
            _set_uniform(self._tess_prog, "body_albedo", 5)
            _set_uniform(self._tess_prog, "has_body_texture", 1 if textured else 0)
            self._render_instanced(self._tess_prog, self._tess_layout, instances[0], instances[1], level)
        position = np.asarray(actor.position, dtype=np.float64)
        self._draw_lines(actor, frame, palette, position)
        self._draw_points(actor, frame, palette, position)

    def _draw_background(self, asset):
        pixels = asset.pixels
        src_h, src_w = pixels.shape[:2]
        key = (id(pixels), pixels.shape)
        if key != self._bg_key:
            if self._bg_tex is not None:
                self._bg_tex.release()
            data = np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()
            self._bg_tex = self._ctx.texture((src_w, src_h), 3, data)
            self._bg_tex.repeat_x = False
            self._bg_tex.repeat_y = False
            self._bg_key = key
            # Keep the source array alive for as long as its id() is the
            # cache key: without this reference, `pixels` could be freed
            # and a same-shaped array could land at the same address,
            # making a stale key match and serving last frame's texture.
            self._bg_src = pixels

        filter_name = self._options.background_filter
        if filter_name == "nearest":
            self._bg_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            mode = 0
        elif filter_name == "xbr" and (src_h, src_w) == (H, W):
            self._bg_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            mode = 2
        else:
            self._bg_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            mode = 0

        self._bg_tex.use(location=0)
        self._bg_prog["tex"].value = 0
        self._bg_prog["mode"].value = mode
        self._bg_prog["src_size"].value = (float(src_w), float(src_h))
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._quad_vao.render(moderngl.TRIANGLES)

    def _body_texture(self, asset):
        """The GL texture for a body's albedo atlas, memoised on the source
        array's identity the way the background is. Mipmapped and
        anisotropically filtered: an actor's atlas is minified hard at
        distance, and without mips the chart gutters alias into each
        other."""
        if asset is None:
            return None
        pixels = asset.pixels
        key = (id(pixels), pixels.shape)
        cached = self._body_tex_cache.get(key)
        if cached is None:
            data = np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()
            tex = self._ctx.texture((pixels.shape[1], pixels.shape[0]), 3, data)
            tex.build_mipmaps()
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            tex.anisotropy = min(8.0, self._ctx.max_anisotropy)
            tex.repeat_x = tex.repeat_y = False
            # keep the source array alive for as long as its id() is the key
            self._body_tex_cache[key] = (tex, pixels)
            cached = self._body_tex_cache[key]
        return cached[0]

    def _rasterize_masks(self, masks):
        # Each polygon is drawn as a real triangle list (GL_TRIANGLES),
        # not a GL_TRIANGLE_FAN from vertex 0: a fan only fills a polygon
        # correctly when it is star-shaped from that vertex, and real
        # mask polygons are frequently concave. The ear-clipping
        # triangulation itself lives in mask_geometry.py (pure, cached
        # once per MaskDraw at load time via MaskDraw.triangles) -- this
        # loop only gathers the precomputed triangle vertices and uploads
        # them, so the per-frame buffer/VAO creation cadence (one per
        # polygon per mask per actor) is unchanged from before this fix.
        self._mask_fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._mask_fbo.clear(0.0, 0.0, 0.0, 0.0)
        for mask in masks:
            for poly, tris in zip(mask.polygons, mask.triangles):
                if len(tris) == 0:
                    continue
                tri_pts = poly[tris.reshape(-1)]
                verts = np.empty((len(tri_pts), 2), dtype="f4")
                verts[:, 0] = tri_pts[:, 0].astype("f4") / SCREEN_CENTER_X - 1.0
                verts[:, 1] = 1.0 - tri_pts[:, 1].astype("f4") / SCREEN_CENTER_Y
                buf = self._ctx.buffer(verts.tobytes())
                vao = self._ctx.vertex_array(self._stencil_prog, [(buf, "2f", "in_pos")])
                vao.render(moderngl.TRIANGLES)
                vao.release()
                buf.release()

    def _rasterize_shadow(self, actor, travel, mvp):
        """This actor's triangles, flattened onto the ground plane beneath it,
        into the coverage texture. Coverage is all this path writes: the
        texture has been RG since the gathered cast arrived, but _SHADOW_FSH
        reads only .r unless `soft`, and the G channel (the soft path's
        penumbra radius) is left at whatever the clear put there. Returns
        whether anything was actually rasterised, so the caller can skip
        compositing an empty coverage texture entirely.

        The plane is the actor's own zv lower bound -- world y grows
        downward, so the feet are the larger of the two y bounds. It travels
        with the actor, which is why a shadow never detaches in mid-air; see
        the spec's Limitations."""
        self._shadow_fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_fbo.clear(0.0, 0.0, 0.0, 0.0)
        geometry = actor.geometry
        if not len(geometry.tris):
            # This guard's own return value is what keeps a triangle-less
            # actor from compositing at all (see the call site's `if
            # scene_lit and self._rasterize_shadow(...)`), so a stale
            # texture reaching this actor's own composite is not the risk
            # here. The clear above still has a real job: it resets the one
            # shared texture between any two *casting* actors -- without
            # it, a later actor with a smaller silhouette would inherit
            # coverage left over from an earlier, larger one at the pixels
            # its own triangles don't reach.
            return False
        plane_y = _plane_y(actor)
        world = geometry.vertices.astype(np.float64) + np.asarray(actor.position, np.float64)
        flat = project_to_plane(world, travel, plane_y)
        verts = flat[geometry.tris.reshape(-1)].astype("f4")
        self._shadow_geom_prog["mvp"].write(mvp.T.astype("f4").tobytes())
        buf = self._ctx.buffer(np.ascontiguousarray(verts).tobytes())
        vao = self._ctx.vertex_array(self._shadow_geom_prog, [(buf, "3f", "in_pos")])
        vao.render(moderngl.TRIANGLES)
        vao.release()
        buf.release()
        return True

    def _rasterize_shadow_tessellated(self, instances, travel, mvp, plane_y, level):
        """_rasterize_shadow's twin for the tessellated path: the same
        instance buffer the actor is about to be drawn from, evaluated by
        _TESS_VSH in its `project` mode, so the coverage silhouette is
        exactly as round as the actor. `travel` is tipped onto the MIN_UP
        cone here, as project_to_plane does on the CPU, and handed to the
        shader already clamped. Sphere primitives are in the instance
        stream, so unlike the CPU path they cast shadows too."""
        self._shadow_fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_fbo.clear(0.0, 0.0, 0.0, 0.0)
        if instances is None:
            return False
        prog = self._tess_shadow_prog
        prog["mvp"].write(mvp.T.astype("f4").tobytes())
        prog["project"].value = 1
        prog["travel"].value = tuple(float(v) for v in _clamp_downward(travel))
        prog["plane_y"].value = plane_y
        self._render_instanced(prog, self._tess_shadow_layout, instances[0], instances[1], level)
        return True

    def _r_max(self):
        """The widest penumbra radius the blur honours, in target pixels."""
        return R_MAX_PER_SCALE * self._options.scale

    def _gather_shadows(self, frame, instances, mask_by_id, travel, mvp, rot, level):
        """Every actor's ground shadow into one coverage texture -- each cast
        erased by that actor's own masks -- softened by the per-pixel
        penumbra radius and multiplied onto the plate once, before any body
        is drawn. A nearer actor's shadow can no longer paint over a farther
        body, and overlapping casts take the MAX, so they darken once."""
        self._shadow_fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_fbo.clear(0.0, 0.0, 0.0, 0.0)
        prog = self._cast_prog
        prog["mvp"].write(mvp.T.astype("f4").tobytes())
        prog["project"].value = 1
        prog["travel"].value = tuple(float(v) for v in _clamp_downward(travel))
        # rot maps world -> camera, so its first row is the world vector
        # that lands on camera +x: the axis the penumbra width is measured along
        prog["right"].value = tuple(float(v) for v in rot[0])
        prog["tan_source"].value = TAN_SOURCE
        prog["r_max"].value = float(self._r_max())
        prog["target_size"].value = self.size
        prog["mask_tex"].value = 1
        cast = False
        for actor, inst in zip(frame.actors, instances):
            if inst is None:
                continue
            self._rasterize_masks([mask_by_id[i] for i in actor.mask_ids if i in mask_by_id])
            self._shadow_fbo.use()
            self._ctx.viewport = (0, 0, *self.size)
            self._mask_tex.use(location=1)
            prog["plane_y"].value = _plane_y(actor)
            self._ctx.enable(moderngl.BLEND)
            self._ctx.blend_func = moderngl.ONE, moderngl.ONE
            self._ctx.blend_equation = moderngl.MAX
            self._render_instanced(prog, self._cast_layout, inst[0], inst[1], level)
            self._ctx.blend_equation = moderngl.FUNC_ADD
            self._ctx.disable(moderngl.BLEND)
            cast = True
        if cast:
            self._soften_shadows()
            self._composite_shadow(frame.light, soft=True)

    def _soften_shadows(self):
        """Two passes of the radius-driven blur over the coverage texture:
        horizontal into _shadow_blur_tex, vertical back into _shadow_tex.

        Blending is disabled here rather than assumed: the pass overwrites
        what it reads, and the gather that runs before it leaves MAX on the
        blend equation. Leaving that live would MAX each pass onto its own
        destination instead of replacing it."""
        self._ctx.disable(moderngl.BLEND)
        self._blur_prog["src"].value = 2
        self._blur_prog["r_max"].value = self._r_max()
        passes = (((1, 0), self._shadow_tex, self._shadow_blur_fbo),
                  ((0, 1), self._shadow_blur_tex, self._shadow_fbo))
        for axis, src, dst in passes:
            dst.use()
            self._ctx.viewport = (0, 0, *self.size)
            self._ctx.disable(moderngl.DEPTH_TEST)
            src.use(location=2)
            self._blur_prog["axis"].value = axis
            self._blur_quad_vao.render(moderngl.TRIANGLES)

    def _render_ssao(self, frame):
        self._render_ssao_with(self._proj_xy(frame))

    def _render_ssao_with(self, proj_xy):
        """The one SSAO pass, over the half-resolution G-buffer, into
        _ssao_tex. Split from _render_ssao so a test can drive it with a
        known (fx, fy) instead of reaching into a frame to fake a
        projection -- the seam tests/test_render_gl.py's twin-comparison
        test exists to use."""
        self._ssao_fbo.use()
        self._ctx.viewport = (0, 0, *self._gbuf_size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._gbuf_tex.use(location=7)
        self._ssao_noise_tex.use(location=8)
        _set_uniform(self._ssao_prog, "gbuf_tex", 7)
        _set_uniform(self._ssao_prog, "noise_tex", 8)
        _set_uniform(self._ssao_prog, "target_size", tuple(float(v) for v in self._gbuf_size))
        _set_uniform(self._ssao_prog, "proj_xy", (float(proj_xy[0]), float(proj_xy[1])))
        self._ssao_vao.render(moderngl.TRIANGLES)

    def _blur_ssao(self):
        """One pass, into the ping-pong target, then swap so _ssao_tex is
        always the texture the actor shader samples.

        The swap is a trap for release(): after an odd number of frames the
        attribute names point at each other's GL objects (_ssao_tex may
        hold what was allocated as _ssao_blur_tex, and vice versa). That is
        harmless for release() -- both objects are released regardless of
        which attribute names them -- so do not "fix" it by tracking the
        original objects separately.
        """
        self._ssao_blur_fbo.use()
        self._ctx.viewport = (0, 0, *self._gbuf_size)
        self._ssao_tex.use(location=7)
        self._gbuf_tex.use(location=8)
        _set_uniform(self._ssao_blur_prog, "ssao_tex", 7)
        _set_uniform(self._ssao_blur_prog, "gbuf_tex", 8)
        _set_uniform(self._ssao_blur_prog, "target_size", tuple(float(v) for v in self._gbuf_size))
        _set_uniform(self._ssao_blur_prog, "depth_threshold", SSAO_RADIUS)
        self._ssao_blur_vao.render(moderngl.TRIANGLES)
        self._ssao_tex, self._ssao_blur_tex = self._ssao_blur_tex, self._ssao_tex
        self._ssao_fbo, self._ssao_blur_fbo = self._ssao_blur_fbo, self._ssao_fbo

    def _render_gbuffer(self, frame, instances, level):
        """Every actor once, into a half-resolution normal+depth buffer.

        The per-actor depth clears the main loop needs for painter's order
        (render_gl.py's draw loop) leave no shared depth to sample, so this
        is the only place a coherent depth of the whole actor layer exists.
        Lines and points are excluded for the same reason they never cast:
        they never reach the instanced path at all.

        mvp and rot are recomputed here from `frame.camera` rather than
        threaded through as parameters -- camera_matrix and rotation_matrix
        are pure functions of the camera alone, so this is the same value
        _draw_frame's own `mvp`/`rot` locals hold, not a second derivation
        that could drift. `view` is set once per frame, alongside the other
        actor programs, in _draw_frame's own view-uniform loop.

        `focal1` is threaded through the same way: read straight off
        `frame.camera.state` -- the same state camera_matrix and
        projection_matrix both build their matrices from -- so it cannot
        drift from the `mvp` this same frame is drawn with. GBUFFER_FSH
        adds it to v_view.z because this engine's actual perspective
        divide is by z + focal1, not bare z (see GBUFFER_FSH's and
        _proj_xy's comments)."""
        self._gbuf_fbo.use()
        self._ctx.viewport = (0, 0, *self._gbuf_size)
        # Alpha 0 is "no actor here" -- the value both SSAO sides read as
        # unoccluded, so an empty G-buffer contributes nothing.
        self._gbuf_fbo.clear(0.0, 0.0, 0.0, 0.0)
        self._ctx.enable(moderngl.DEPTH_TEST)
        self._ctx.depth_func = "<="
        mvp = camera_matrix(frame.camera, self._options.scale)
        rot = rotation_matrix(frame.camera.state).astype("f4")
        self._gbuf_prog["mvp"].write(mvp.T.tobytes())
        self._gbuf_prog["rot"].write(rot.T.tobytes())
        self._gbuf_prog["project"].value = 0
        self._gbuf_prog["focal1"].value = float(frame.camera.state.focal1)
        for inst in instances:
            if inst is not None:
                self._render_instanced(self._gbuf_prog, self._gbuf_layout, inst[0], inst[1], level)
        self._ctx.disable(moderngl.DEPTH_TEST)

    def _proj_xy(self, frame):
        """(fx, fy): the pinhole scale factors `ssao_reference` and
        SSAO_FSH both use to turn (screen position, linear depth) into a
        position, each in its own space.

        These two numbers are convention-free, unlike the G-buffer's
        normals (see GBUFFER_FSH): fx and fy are exactly the linear x/y
        scale this engine's own projection applies before its perspective
        divide -- `projection_matrix(state)`'s x and y rows are `[fx,
        0, 0, 0]` and `[0, -fy, 0, 0]`, zero coefficient on z and w, so
        `clip.xy == (fx * x, -fy * y)` for a camera-space (x, y, z)
        regardless of z. Neither row depends on `state.focal1` either
        (only row 2 -- the depth-buffer z -- and row 3 -- w -- do, via
        `projection_matrix`'s `shift`), so fx and fy need no adjustment
        of their own for it: `focal1` is entirely the depth side's
        concern, folded into GBUFFER_FSH's alpha channel instead (`v_view.z
        + focal1`, set from a `focal1` uniform `_render_gbuffer` writes
        each frame) rather than into this pair.

        With that in place, `ndc = (x / depth) * f` -- `ssao_reference`'s
        and SSAO_FSH's own relation -- now holds exactly against this
        engine's real NDC for every reconstruction the G-buffer feeds,
        `focal1` included: `test_proj_xy_and_gbuffer_depth_reconstruct_
        the_real_projections_ndc` pins the full pair (fx/fy plus the
        depth convention) against `camera_matrix`'s actual clip.xy /
        clip.w for an off-axis point, and fails without the `focal1` term
        (measured before the fix: ndc off by the golden frame's camera's
        z=900 vs depth=z+focal1=1900, roughly 2.1x on both axes) --
        replacing an earlier, narrower version of this test that only
        pinned fx/fy's sign, pre-division, and could not have caught a
        missing depth term.

        Read off `projection_matrix` -- the same function camera_matrix
        builds `mvp` out of -- rather than re-deriving focal2/focal3 by
        hand, so this can never drift from what the actors are actually
        projected with. Row 1 of projection_matrix is negated (to flip
        screen-space y, a real sign this engine's own NDC needs) which is
        exactly the reason both rows are read as magnitudes here: that
        negation is a screen-axis convention, not a statement about which
        way the view axis points, and abs() strips it without touching
        the reasoning above."""
        proj = projection_matrix(frame.camera.state)
        return abs(float(proj[0][0])), abs(float(proj[1][1]))

    def _render_shadow_map(self, frame, instances, travel, level):
        """One orthographic depth map from the light over every actor's
        instances, spheres included, lines and points excluded as in every
        shadow pass. Returns the (light_vp, depth_bias) the receivers need
        -- light_vp already carrying the clip-to-texture bias, transposed
        for GLSL -- or None when no actor has anything to cast, in which
        case the receivers keep self_shadow = 0. No face culling: FITD
        winding is not consistent, so both faces write depth."""
        corners = []
        for actor, inst in zip(frame.actors, instances):
            if inst is not None:
                corners.extend(_world_box(actor))
        if not corners:
            return None
        matrix, extent = light_view_matrix(travel, corners, pad=NORMAL_OFFSET)
        self._shadow_map_fbo.use()
        self._ctx.viewport = (0, 0, SHADOW_MAP_SIZE, SHADOW_MAP_SIZE)
        self._ctx.enable(moderngl.DEPTH_TEST)
        self._ctx.depth_func = "<="
        self._shadow_map_fbo.clear(depth=1.0)
        prog = self._tess_shadow_prog
        prog["mvp"].write(matrix.T.astype("f4").tobytes())
        prog["project"].value = 0
        for inst in instances:
            if inst is not None:
                self._render_instanced(prog, self._tess_shadow_layout, inst[0], inst[1], level)
        self._ctx.disable(moderngl.DEPTH_TEST)
        biased = (_SHADOW_BIAS @ matrix.astype(np.float64)).astype("f4")
        return np.ascontiguousarray(biased.T), float(SHADOW_BIAS_UNITS / extent[2])

    def _composite_shadow(self, light, soft=False):
        """Multiply the background toward the room's ambient hue through the
        coverage texture: `mix(1, ambient, opacity)` is a per-channel
        factor <= 1.0 (ambient is 0..1), and it is multiplied into the
        destination via blend_func=(DST_COLOR, ZERO) rather than alpha-
        blended, so a shadowed pixel can only ever be scaled down toward
        the room's ambient colour -- never brightened -- regardless of how
        the destination compares to ambient. An alpha blend of the same
        colour would pull the destination toward ambient from either side,
        brightening any pixel already darker than ambient.

        This consumes `SceneLight.ambient` *raw*, as an absolute
        reflectance of the room -- a different quantity from the
        normalised `fill_tint` the actor shader gets out of
        shading_terms(), which shares the field's name but not its
        meaning. Its opacity comes from lighting.shadow_opacity, which
        sits beside lighting.key_weight: two curves over the same
        `contrast`, deliberately different, kept in one place.

        Ordering caveat: this is a full-target quad with the depth test
        disabled, composited inside the per-actor loop, so it darkens
        whatever the target already holds -- including actors drawn earlier
        in this same frame. A nearer actor's silhouette can therefore paint
        over a farther actor's body. The painter's-order loop makes it rare
        (measured at 0 overlapping pixels across 50 live frames), and the
        mask discard keeps foreground geometry safe, but the mechanism is
        real: a true fix would need the shadows gathered into one coverage
        pass before any actor is drawn.

        Under `soft` the coverage is the gathered, mask-erased, softened
        texture and is consumed fractionally; the ordering caveat above
        no longer applies, since this runs once before any body is drawn."""
        self._target.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_tex.use(location=2)
        self._mask_tex.use(location=1)
        self._shadow_prog["shadow_tex"].value = 2
        self._shadow_prog["mask_tex"].value = 1
        self._shadow_prog["target_size"].value = self.size
        self._shadow_prog["shadow_color"].value = tuple(float(c) for c in light.ambient)
        self._shadow_prog["opacity"].value = shadow_opacity(light.contrast)
        self._shadow_prog["soft"].value = 1 if soft else 0
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = moderngl.DST_COLOR, moderngl.ZERO
        self._shadow_quad_vao.render(moderngl.TRIANGLES)
        self._ctx.disable(moderngl.BLEND)

    def _cast_hard_shadow(self, actor, inst, mask_by_id, frame, travel, mvp, level):
        """One actor's `shadows=hard` projected silhouette, erased by its own
        masks and multiplied onto whatever `self._target` currently is.

        Extracted so the per-actor loop and the integration pre-loop share
        one copy of the rule; the only difference between the two callers is
        which layer `self._target` names when they run."""
        self._rasterize_masks([mask_by_id[i] for i in actor.mask_ids if i in mask_by_id])
        if level:
            cast = self._rasterize_shadow_tessellated(inst, travel, mvp, _plane_y(actor), level)
        else:
            cast = self._rasterize_shadow(actor, travel, mvp)
        if cast:
            self._composite_shadow(frame.light)

    def _resolve_into(self, fbo):
        """Resolve the multisample buffer into `fbo`'s single-sampled
        texture. A no-op when msaa is off: `fbo` was the render target
        itself, and its texture already holds the result."""
        if self._ms_fbo is not None:
            self._ctx.copy_framebuffer(fbo, self._ms_fbo)

    def _composite(self, frame):
        """The actor layer back onto the plate layer, into `.texture`."""
        src_h, src_w = frame.background.pixels.shape[:2]
        strength = INTEGRATION_STRENGTHS[self._options.integration]
        sigma, cell, pixelate = softness(
            self._options.background_filter, (src_w, src_h), self.size)
        # Scaled here rather than in the shader because `radius` and
        # `inv_sigma2` are both derived from sigma on this side: a lower
        # level buys a narrower blur and fewer taps with it, and a higher
        # one widens until MAX_BLUR_RADIUS caps the window.
        sigma *= strength
        radius = 0 if sigma <= 0.0 else min(MAX_BLUR_RADIUS, int(math.ceil(2.0 * sigma)))
        self._composite_prog["radius"].value = radius
        self._composite_prog["inv_sigma2"].value = (
            0.0 if sigma <= 0.0 else 1.0 / (2.0 * sigma * sigma))
        self._composite_prog["cell"].value = float(cell)
        # Ungraded on purpose: `pixelate` names which plate cell a pixel
        # falls in, which has no half-measure -- an actor at half a grid is
        # on no grid at all. Every level that composites pixelates alike.
        self._composite_prog["pixelate"].value = 1 if pixelate else 0
        self._composite_prog["strength"].value = strength
        self._composite_prog["plate_black"].value = tuple(float(v) for v in frame.plate.black)
        self._composite_prog["plate_white"].value = tuple(float(v) for v in frame.plate.white)
        # The *source* amplitude, uncorrected. The shader magnifies this
        # field the way `background_filter` magnified the room's own
        # dither, and that magnification is what attenuates it -- an
        # analytic correction here as well would attenuate it twice.
        #
        # Correcting the amplitude was the earlier model, and it matched
        # the room's variance while missing its character: a scalar cannot
        # turn one flat value per plate cell into the ramp an interpolating
        # filter actually produces, and the residual against the local mean
        # -- which is what a dither looks like -- came out ~3x the room's.
        self._composite_prog["plate_grain"].value = float(frame.plate.grain)
        self._composite_prog["smooth_grain"].value = 1 if dither_arrives_smoothed(
            self._options.background_filter, (src_w, src_h), self.size) else 0
        self._fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.disable(moderngl.BLEND)
        self._fbo.color_mask = (True, True, True, True)
        # Defensive, not corrective: with the composite running nothing rebinds
        # _fbo as a render target between the assignment above and this
        # line, so the colour mask can't actually have drifted from the GL
        # binding point the way _target's does after `clear()` in the
        # per-actor loop above. Kept anyway, matching that loop's habit of
        # re-`use()`ing after every colour-mask write -- one bind per frame
        # is cheap insurance, and the day _fbo takes on render-target duty
        # elsewhere in this file it stops being free to assume this call is
        # a no-op.
        self._fbo.use()
        self._plate_tex.use(location=5)
        self._actor_tex.use(location=6)
        self._composite_prog["plate_tex"].value = 5
        self._composite_prog["actor_tex"].value = 6
        self._composite_vao.render(moderngl.TRIANGLES)

    def _upload_materials(self, table):
        """Write `table.parameters()` into the material texture unless it is
        the table object uploaded last time (default_table() is cached, so
        every actor on the default shares one object and one upload).

        Identity is a sound cache key only because both a MaterialTable and
        the CLASS_PRESETS it reads are immutable: the same object can never
        produce different parameters. A test that mutates CLASS_PRESETS must
        hand every actor a fresh MaterialTable, or this will serve the
        parameters from before the mutation."""
        if table is self._material_key:
            return
        params = table.parameters()                      # (256, 12)
        rows = np.stack([params[:, :4], params[:, 4:8], params[:, 8:]], axis=0)   # (3, 256, 4)
        self._material_tex.write(np.ascontiguousarray(rows, dtype="f4").tobytes())
        self._material_key = table

    # ---- per-actor primitives ----

    def _draw_actor(self, actor, frame, palette):
        geometry = actor.geometry
        position = np.asarray(actor.position, dtype=np.float64)
        tri_data = self._triangle_data(geometry, position, palette)
        if len(tri_data):
            texture = self._body_texture(actor.texture)
            # geometry.uv is None both when the body is genuinely unpainted
            # and when BodyGeometry.__post_init__ dropped a mismatched
            # sidecar back to None (a stale triangulation hash, or a paint
            # copied from another body number) -- either way there are no
            # real per-corner UVs to sample, so treat it exactly like
            # "unpainted" rather than sampling every corner at (0, 0).
            textured = (texture is not None and geometry.uv is not None
                        and self._options.realism != "classic")
            if textured:
                # unit 5: shared with the composite's plate texture
                # (_plate_tex.use(location=5) above); each pass rebinds it
                # before sampling, so the two never collide within a frame
                texture.use(5)
            _set_uniform(self._actor_prog, "body_albedo", 5)
            _set_uniform(self._actor_prog, "has_body_texture", 1 if textured else 0)
            self._render_triangles(tri_data)
        self._draw_lines(actor, frame, palette, position)
        self._draw_points(actor, frame, palette, position)

    def _triangle_data(self, geometry, position, palette):
        parts = []
        if len(geometry.tris):
            idx = geometry.tris.reshape(-1)
            pos = geometry.vertices[idx].astype(np.float64) + position
            norm = geometry.normals[idx]
            colors = geometry.tri_colors.repeat(3)
            col = palette[colors]
            rest = geometry.rest[idx]
            ao = geometry.ao[idx][:, None]
            index = colors.astype("f4")[:, None]
            uv = (np.zeros((len(idx), 2), "f4") if geometry.uv is None
                  else geometry.uv.reshape(-1, 2)[:len(idx)].astype("f4"))
            parts.append(np.concatenate(
                [pos.astype("f4"), norm.astype("f4"), col.astype("f4"),
                 rest.astype("f4"), ao.astype("f4"), index, uv], axis=1))
        if geometry.spheres:
            sphere_verts, sphere_tris = self._sphere  # cached, lru_cache-shared: never mutated
            idx = sphere_tris.reshape(-1)
            unit = sphere_verts[idx]  # fancy indexing copies
            for centre_idx, radius, color in geometry.spheres:
                centre = geometry.vertices[centre_idx].astype(np.float64) + position
                pos = (unit.astype(np.float64) * radius + centre).astype("f4")
                norm = unit.astype("f4")
                col = np.tile(palette[color], (len(pos), 1)).astype("f4")
                # rest = the sphere's own surface about its rest centre, so
                # grain is fixed to the ball; ao = open (nothing is baked for
                # spheres, which FITD uses for heads and hands)
                rest = (unit.astype(np.float64) * radius + geometry.rest[centre_idx]).astype("f4")
                ao = np.ones((len(pos), 1), "f4")
                index = np.full((len(pos), 1), float(color), "f4")
                # spheres share this buffer and stay untextured; a negative
                # uv is the sentinel the shader reads for that
                uv = np.full((len(pos), 2), -1.0, "f4")
                parts.append(np.concatenate([pos, norm, col, rest, ao, index, uv], axis=1))
        if not parts:
            return np.zeros((0, 16), dtype="f4")
        return np.concatenate(parts, axis=0)

    def _render_triangles(self, data):
        buf = self._ctx.buffer(np.ascontiguousarray(data, dtype="f4").tobytes())
        vao = self._ctx.vertex_array(
            self._actor_prog,
            [(buf, "3f 3f 3f 3f 1f 1f 2f", "in_pos", "in_normal", "in_color", "in_rest", "in_ao", "in_index", "in_uv")])
        vao.render(moderngl.TRIANGLES)
        vao.release()
        buf.release()

    def _draw_lines(self, actor, frame, palette, position):
        geometry = actor.geometry
        if not len(geometry.lines):
            return
        a = geometry.vertices[geometry.lines[:, 0]].astype(np.float64) + position
        b = geometry.vertices[geometry.lines[:, 1]].astype(np.float64) + position
        proj_a = frame.camera.project(a)
        proj_b = frame.camera.project(b)
        verts = []
        for i in range(len(geometry.lines)):
            if proj_a[i, 0] == _SENTINEL_X or proj_b[i, 0] == _SENTINEL_X:
                continue
            color = tuple(palette[geometry.line_colors[i]])
            verts += _line_quad(proj_a[i], proj_b[i], 0.5, color)
        if verts:
            self._render_screen(verts)

    def _draw_points(self, actor, frame, palette, position):
        geometry = actor.geometry
        if not len(geometry.points):
            return
        pts = geometry.vertices[geometry.points].astype(np.float64) + position
        proj = frame.camera.project(pts)
        verts = []
        for i in range(len(geometry.points)):
            if proj[i, 0] == _SENTINEL_X:
                continue
            sx, sy, depth = proj[i]
            size = float(geometry.point_sizes[i])
            color = tuple(palette[geometry.point_colors[i]])
            verts += _point_quad(sx, sy, depth, size, color)
        if verts:
            self._render_screen(verts)

    def _render_screen(self, verts):
        data = np.array(verts, dtype="f4")
        buf = self._ctx.buffer(data.tobytes())
        vao = self._ctx.vertex_array(self._screen_prog, [(buf, "3f 3f", "in_ndc", "in_color")])
        vao.render(moderngl.TRIANGLES)
        vao.release()
        buf.release()

    # ---- readback ----

    def read_rgb(self):
        w, h = self.size
        data = np.frombuffer(self.texture.read(), dtype=np.uint8).reshape(h, w, 4)
        return data[::-1, :, :3].copy()

    def thumbnail(self):
        """Downsample `.texture` to a (200,320,3) uint8 array, GPU-side.

        A fullscreen blit into the fixed 320x200 `_thumb_fbo`, sampling
        `.texture` with GL_LINEAR: at scale=2 this lands exactly on the
        4-texel box average (each destination texel centre maps to
        source-texel-space i*2+0.5, i.e. frac=0.5 in both axes -- a
        standard GL_LINEAR two-tap-per-axis blend, which is the same
        weighting a true box filter would use). At larger scales GL_LINEAR
        still blends only the 4 nearest source texels rather than the full
        NxN box the old numpy `.mean()` averaged, trading a slightly
        softer result for a single texture fetch per output pixel instead
        of an NxN one -- this is the whole point of the optimisation
        (measured ~28x at scale 4, ~56x at scale 8 against the old
        read_rgb()+numpy .mean() path; see the finding-1 benchmark in the
        fix report). A decoupled copy, matching the previous numpy-backed
        contract.
        """
        prev_viewport = self._ctx.viewport
        prev_fbo = self._ctx.fbo
        prev_filter = self.texture.filter
        try:
            self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._thumb_fbo.use()
            self._ctx.viewport = (0, 0, W, H)
            self._ctx.disable(moderngl.DEPTH_TEST)
            self.texture.use(location=0)
            self._bg_prog["tex"].value = 0
            self._bg_prog["mode"].value = 0
            self._bg_prog["src_size"].value = (float(self.size[0]), float(self.size[1]))
            self._thumb_quad_vao.render(moderngl.TRIANGLES)
            data = np.frombuffer(self._thumb_fbo.read(components=3), dtype=np.uint8)
            data = data.reshape(H, W, 3)
        finally:
            self.texture.filter = prev_filter
            self._ctx.viewport = prev_viewport
            if prev_fbo is not None and not isinstance(prev_fbo.mglo, moderngl.InvalidObject):
                prev_fbo.use()
        return data[::-1, :, :].copy()


def _line_quad(p0, p1, half_width, color):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        nx, ny = half_width, 0.0
    else:
        nx, ny = -dy / length * half_width, dx / length * half_width
    c0a, c0b = _quad_corners(p0[0], p0[1], p0[2], nx, ny)
    c1a, c1b = _quad_corners(p1[0], p1[1], p1[2], nx, ny)
    tri = [c0a, c0b, c1b, c0a, c1b, c1a]
    return [coord for corner in tri for coord in (*corner, *color)]


def _point_quad(sx, sy, depth, size, color):
    # Top-left anchored, matching the legacy render.py _point_quad.
    corners = [
        _to_ndc(sx, sy, depth),
        _to_ndc(sx + size, sy, depth),
        _to_ndc(sx + size, sy + size, depth),
        _to_ndc(sx, sy + size, depth),
    ]
    tri = [corners[0], corners[1], corners[2], corners[0], corners[2], corners[3]]
    return [coord for corner in tri for coord in (*corner, *color)]
