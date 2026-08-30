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

from PyAitD.engine.cos_table import sin_cos
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
    SHADOW_GEOM_VSH as _SHADOW_GEOM_VSH,
    SHADOW_FSH as _SHADOW_FSH,
    SHADOW_CAST_FSH as _SHADOW_CAST_FSH,
    SHADOW_BLUR_FSH as _SHADOW_BLUR_FSH,
    COMPOSITE_FSH as _COMPOSITE_FSH,
)
from PyAitD.render.lighting import (_clamp_downward, light_view_matrix, project_to_plane,
                                    shading_terms, shadow_opacity, SHADOW_MAP_SIZE)
from PyAitD.render.materials import PALETTE_SIZE, PRESETS
from PyAitD.render.plate import grain_retention, softness
from PyAitD.render.refine import subpatch
from PyAitD.render.render_options import SMOOTHING_LEVELS
from PyAitD.engine.world import SCREEN_CENTER_X, SCREEN_CENTER_Y

W, H = 320, 200

LIGHT_DIR = (-0.3, -0.5, -0.8)
NEAR, FAR = 50.0, 40960.0

_SENTINEL_X = -10000.0
_DEPTH_A = (FAR + NEAR) / (FAR - NEAR)
_DEPTH_B = -2 * FAR * NEAR / (FAR - NEAR)

_SHADING_INDEX = {"flat": 0, "lambert": 1, "smooth": 2}

CONTACT_HEIGHT = 150.0   # FITD units over which the contact term fades, roughly shin height

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
# (rgb, palette index), rest.xyz -- 15 floats, 45 per triangle, twelve
# packed attributes plus the per-vertex barycentric: 13 of the 16 slots
# GL 3.3 guarantees.
INSTANCE_FLOATS = 45
_INSTANCE_ATTRIBUTES = ("4f", "4f", "4f", "3f") * 3
_INSTANCE_NAMES = ("in_p0", "in_n0", "in_c0", "in_r0",
                   "in_p1", "in_n1", "in_c1", "in_r1",
                   "in_p2", "in_n2", "in_c2", "in_r2")


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
        self._sphere = None
        self._material_tex = None
        self._material_key = None
        self._shadow_map = None
        self._shadow_map_fbo = None
        self._tess_prog = None
        self._tess_shadow_prog = None
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

            # The two halves integration="on" splits the frame into. Both
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
        # the integration mode and the frame phase, and each of those is
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
            # All three VAOs are built on `_shadow_quad`, so all three come
            # before it: every other pair in this tuple frees the VAO ahead of its
            # buffer, and deleting a buffer does not unbind it from a VAO
            # that is not current.
            self._shadow_quad_vao, self._blur_quad_vao, self._composite_vao, self._shadow_quad,
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
        self._bg_tex = None
        self._bg_key = None
        self._material_key = None
        self._bg_src = None
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
        integrate = scene_lit and self._options.integration == "on"
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
        for prog in (self._actor_prog, self._tess_prog, self._tess_shadow_prog, self._cast_prog):
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
            rows.append(np.concatenate([pos, ao, normal, straight, col, index, rest], axis=2).reshape(len(idx), INSTANCE_FLOATS))
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
        sigma, cell, pixelate = softness(
            self._options.background_filter, (src_w, src_h), self.size)
        radius = 0 if sigma <= 0.0 else min(MAX_BLUR_RADIUS, int(math.ceil(2.0 * sigma)))
        self._composite_prog["radius"].value = radius
        self._composite_prog["inv_sigma2"].value = (
            0.0 if sigma <= 0.0 else 1.0 / (2.0 * sigma * sigma))
        self._composite_prog["cell"].value = float(cell)
        self._composite_prog["pixelate"].value = 1 if pixelate else 0
        self._composite_prog["plate_black"].value = tuple(float(v) for v in frame.plate.black)
        self._composite_prog["plate_white"].value = tuple(float(v) for v in frame.plate.white)
        # `frame.plate.grain` is the dither of the *source* 320x200 image;
        # the shader's amplitude has to be the dither of the plate as
        # displayed, after `background_filter` has magnified it. The two
        # differ by exactly the fraction `grain_retention` derives, and
        # without it the actor is grained at an amplitude the room around
        # it no longer has -- measured on the attic plate at scale 4, 8.48
        # counts of source dither against the 5.05 the displayed plate
        # still carries per cell. 1.0 wherever nothing is lost (cell <= 1,
        # `nearest`, xbr at the classic size), so the msaa-0 identity and
        # `test_grain_lands_at_the_plates_own_amplitude` are untouched.
        self._composite_prog["plate_grain"].value = float(frame.plate.grain) * grain_retention(
            self._options.background_filter, (src_w, src_h), self.size)
        self._fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.disable(moderngl.BLEND)
        self._fbo.color_mask = (True, True, True, True)
        # Not redundant: moderngl applies a framebuffer's stored colour mask
        # at `use()` time, so the assignment above only reaches the GL
        # binding point on a second `use()` -- the same desync the per-actor
        # loop documents after `clear()`.
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
            parts.append(np.concatenate(
                [pos.astype("f4"), norm.astype("f4"), col.astype("f4"),
                 rest.astype("f4"), ao.astype("f4"), index], axis=1))
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
                parts.append(np.concatenate([pos, norm, col, rest, ao, index], axis=1))
        if not parts:
            return np.zeros((0, 14), dtype="f4")
        return np.concatenate(parts, axis=0)

    def _render_triangles(self, data):
        buf = self._ctx.buffer(np.ascontiguousarray(data, dtype="f4").tobytes())
        vao = self._ctx.vertex_array(
            self._actor_prog,
            [(buf, "3f 3f 3f 3f 1f 1f", "in_pos", "in_normal", "in_color", "in_rest", "in_ao", "in_index")])
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
