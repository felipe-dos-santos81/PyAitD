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
from PyAitD.render.lighting import project_to_plane, shading_terms, shadow_opacity
from PyAitD.render.materials import PALETTE_SIZE, PRESETS
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


_BG_VSH = """
#version 330
in vec2 in_pos; in vec2 in_uv; out vec2 v_uv;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); v_uv = in_uv; }
"""
_BG_FSH = """
#version 330
uniform sampler2D tex; uniform int mode; uniform vec2 src_size;
in vec2 v_uv; out vec4 f_color;
vec4 xbr(vec2 uv) {
    // 2-tap edge-aware blend: sample the 4 neighbours, keep the pixel
    // unless two diagonal neighbours agree, then blend toward them.
    vec2 px = 1.0 / src_size;
    vec4 c = texture(tex, uv);
    vec4 n = texture(tex, uv + vec2(0.0, -px.y)); vec4 s = texture(tex, uv + vec2(0.0, px.y));
    vec4 w = texture(tex, uv + vec2(-px.x, 0.0)); vec4 e = texture(tex, uv + vec2(px.x, 0.0));
    vec2 f = fract(uv * src_size) - 0.5;
    vec4 h = f.x < 0.0 ? w : e; vec4 v = f.y < 0.0 ? n : s;
    if (distance(h.rgb, v.rgb) < 0.05 && distance(h.rgb, c.rgb) > 0.1 && abs(f.x) + abs(f.y) > 0.5)
        return h;
    return c;
}
void main() {
    if (mode == 2) f_color = xbr(v_uv); else f_color = texture(tex, v_uv);
}
"""
_ACTOR_VSH = """
#version 330
uniform mat4 mvp; uniform mat3 rot;
in vec3 in_pos; in vec3 in_normal; in vec3 in_color; in vec3 in_rest; in float in_ao; in float in_index;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_color = in_color; v_normal = rot * in_normal;
    v_rest = in_rest; v_ao = in_ao; v_index = in_index;
    v_world_y = in_pos.y;   // in_pos is already world space: the actor position was added on the CPU
}
"""
_ACTOR_FSH = """
#version 330
uniform int shading; uniform int lighting;
// key_tint/fill_tint are shading_terms()'s *normalised tints*, not
// reflectances: they carry the room's hue and sum to a peak of 1.0. The
// shadow composite's `shadow_color` is the other thing -- SceneLight's raw
// ambient, an absolute reflectance. Same room, two different quantities.
uniform vec3 light; uniform vec3 key_tint; uniform vec3 fill_tint;
uniform sampler2D mask_tex; uniform vec2 target_size;
// Materials (scene lighting only). material_tex is 256x2 RGBA32F: row 0 is
// (roughness, specular, metallic, rim), row 1 (detail, detail_scale,
// detail_kind, 0) for the palette index in v_index. preset_a/preset_b are
// the RealismPreset strengths (spec, rim, ao) and (contact, detail,
// hemisphere); under realism=classic all six are 0 and every term below
// is exactly 1.0 or 0.0, leaving `base` untouched.
uniform sampler2D material_tex;
uniform vec3 preset_a; uniform vec3 preset_b;
uniform float plane_y; uniform float contact_height;
in vec3 v_color; in vec3 v_normal; in vec3 v_rest; in float v_ao; flat in float v_index; in float v_world_y;
out vec4 f_color;

float hash3(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float value_noise(vec3 p) {   // -1..1, C1 continuous
    vec3 i = floor(p); vec3 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    float n = mix(mix(mix(hash3(i), hash3(i + vec3(1, 0, 0)), f.x),
                      mix(hash3(i + vec3(0, 1, 0)), hash3(i + vec3(1, 1, 0)), f.x), f.y),
                  mix(mix(hash3(i + vec3(0, 0, 1)), hash3(i + vec3(1, 0, 1)), f.x),
                      mix(hash3(i + vec3(0, 1, 1)), hash3(i + vec3(1, 1, 1)), f.x), f.y), f.z);
    return n * 2.0 - 1.0;
}
float detail_noise(vec3 p, int kind) {
    if (kind == 1) return value_noise(p);                                                        // grain
    if (kind == 2) return sin(p.x * 6.2832) * sin(p.z * 6.2832) * (0.5 + 0.5 * value_noise(p));  // weave
    if (kind == 3) return value_noise(vec3(p.x * 4.0, p.y * 0.25, p.z * 4.0));                   // streak along y, the limb axis
    if (kind == 4) return value_noise(vec3(p.x * 0.25, p.y * 6.0, p.z * 0.25));                  // brushed across it
    return 0.0;
}

void main() {
    if (texture(mask_tex, gl_FragCoord.xy / target_size).r > 0.5) discard;
    if (shading == 0) {
        // unshaded: flat palette colour, and the only path lines and points take
        f_color = vec4(v_color, 1.0);
        return;
    }
    vec3 n = (shading == 1)
        ? normalize(cross(dFdx(gl_FragCoord.xyz), dFdy(gl_FragCoord.xyz)))
        : normalize(v_normal);
    vec3 l = normalize(light);
    if (lighting == 0) {
        // the pre-scene-light rig, kept byte-identical: abs() because FITD
        // polygons have no consistent winding
        f_color = vec4(v_color * (0.55 + 0.45 * abs(dot(n, l))), 1.0);
        return;
    }
    // Orient rather than fold: -z is toward the camera, so a normal with a
    // positive z faces away from the viewer and is pointing into the body.
    //
    // NOT dead code under shading == 1. There the normal is
    // normalize(cross(dFdx(gl_FragCoord.xyz), dFdy(gl_FragCoord.xyz))),
    // whose z is algebraically a constant +1 before normalisation
    // (dFdx(gl_FragCoord.xy) == (1,0) and dFdy == (0,1) at every
    // fragment), so this branch fires for *every* lambert fragment. That
    // is the point: it makes the derivative normal a camera-facing one,
    // which is what removes the winding dependence FITD geometry cannot
    // provide. Deleting the flip inverts every lambert normal.
    if (n.z > 0.0) n = -n;
    // Half-Lambert: the lit side reaches fill_tint + key_tint, the shadow
    // side falls to fill_tint rather than to black. `base` is the whole of
    // realism=classic's answer and must stay this exact expression.
    float wrapped = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
    vec3 base = v_color * (fill_tint + key_tint * wrapped * wrapped);

    int index = int(v_index + 0.5);
    vec4 m0 = texelFetch(material_tex, ivec2(index, 0), 0);
    vec4 m1 = texelFetch(material_tex, ivec2(index, 1), 0);
    vec3 view = vec3(0.0, 0.0, -1.0);                 // from the surface toward the viewer
    vec3 h = normalize(l + view);
    // Camera-space y grows downward, so "up" (the sky half of the
    // hemisphere ambient) is -n.y.
    // Written as `1.0 + strength * ...`, like every other new term, so that
    // realism=classic (preset_b.z == 0) collapses to exactly 1.0 by
    // construction. The equivalent mix(1.0 - k, 1.0 + k, t) is only
    // *probably* exact at k == 0: GLSL defines mix as x*(1-a) + y*a, which
    // Sterbenz guarantees for a >= 0.5 but not below, leaving the branch's
    // byte-for-byte classic identity to the driver's discretion.
    float hemi = 1.0 + preset_b.z * 0.3 * (clamp(-n.y * 0.5 + 0.5, 0.0, 1.0) * 2.0 - 1.0);
    // World y grows downward too: the feet are at plane_y and everything
    // above them has a smaller y. Darkens by up to half at the plane.
    float height = clamp((plane_y - v_world_y) / contact_height, 0.0, 1.0);
    float contact = 1.0 - preset_b.x * 0.5 * (1.0 - height);
    float occl = mix(1.0, v_ao, preset_a.z) * contact;
    float gloss = exp2(1.0 + 10.0 * (1.0 - m0.x));
    vec3 spec = key_tint * mix(vec3(1.0), v_color, m0.z) * pow(max(dot(n, h), 0.0), gloss) * m0.y * preset_a.x;
    vec3 rim = key_tint * pow(1.0 - max(dot(n, view), 0.0), 3.0) * m0.w * preset_a.y;
    float grain = 1.0 + preset_b.y * m1.x * detail_noise(v_rest / m1.y, int(m1.z + 0.5));
    f_color = vec4(base * (grain * hemi * occl) + spec + rim, 1.0);
}
"""
_TESS_VSH = """
#version 330
// PN-triangle tessellation, one instance per source triangle (see
// _INSTANCE_ATTRIBUTES), evaluated at the sub-patch barycentric in in_bary.
// Emits exactly _ACTOR_VSH's varyings so _ACTOR_FSH is reused unchanged;
// refine.evaluate is the numpy twin the parity test pins this against.
uniform mat4 mvp; uniform mat3 rot;
// project == 1 is the shadow mode: the evaluated point slides along
// `travel` onto the plane y == plane_y before mvp -- lighting.project_to_plane.
uniform int project; uniform vec3 travel; uniform float plane_y;
in vec3 in_bary;
in vec4 in_p0; in vec4 in_n0; in vec4 in_c0; in vec3 in_r0;
in vec4 in_p1; in vec4 in_n1; in vec4 in_c1; in vec3 in_r1;
in vec4 in_p2; in vec4 in_n2; in vec4 in_c2; in vec3 in_r2;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec3 v_world;   // the evaluated world position: read back by transform feedback in tests, unused by the fragment shader

vec3 edge_point(vec3 pi, vec3 pj, vec3 ni, float straight) {
    // a third of the way from pi toward pj, projected onto pi's tangent
    // plane -- or left on the chord when the edge is a crease
    return (2.0 * pi + pj) / 3.0 - (1.0 - straight) * dot(pj - pi, ni) * ni / 3.0;
}
vec3 edge_normal(vec3 pi, vec3 pj, vec3 ni, vec3 nj, float straight) {
    vec3 d = pj - pi;
    vec3 h = ni + nj;
    float dd = dot(d, d);
    float v = dd > 1e-12 ? 2.0 * dot(d, h) / dd : 0.0;
    return normalize(h - (1.0 - straight) * v * d);
}
void main() {
    vec3 p0 = in_p0.xyz, p1 = in_p1.xyz, p2 = in_p2.xyz;
    vec3 n0 = in_n0.xyz, n1 = in_n1.xyz, n2 = in_n2.xyz;
    float s01 = in_n0.w, s12 = in_n1.w, s20 = in_n2.w;
    vec3 b210 = edge_point(p0, p1, n0, s01), b120 = edge_point(p1, p0, n1, s01);
    vec3 b021 = edge_point(p1, p2, n1, s12), b012 = edge_point(p2, p1, n2, s12);
    vec3 b102 = edge_point(p2, p0, n2, s20), b201 = edge_point(p0, p2, n0, s20);
    vec3 e = (b210 + b120 + b021 + b012 + b102 + b201) / 6.0;
    vec3 b111 = e + (e - (p0 + p1 + p2) / 3.0) / 2.0;
    float u = in_bary.x, v = in_bary.y, w = in_bary.z;
    vec3 pos = p0 * u*u*u + p1 * v*v*v + p2 * w*w*w
             + b210 * 3.0*u*u*v + b120 * 3.0*u*v*v + b201 * 3.0*u*u*w
             + b021 * 3.0*v*v*w + b102 * 3.0*u*w*w + b012 * 3.0*v*w*w
             + b111 * 6.0*u*v*w;
    vec3 n110 = edge_normal(p0, p1, n0, n1, s01);
    vec3 n011 = edge_normal(p1, p2, n1, n2, s12);
    vec3 n101 = edge_normal(p2, p0, n2, n0, s20);
    vec3 n = normalize(n0 * u*u + n1 * v*v + n2 * w*w + n110 * u*v + n011 * v*w + n101 * w*u);
    if (project == 1) pos += (plane_y - pos.y) / travel.y * travel;
    gl_Position = mvp * vec4(pos, 1.0);
    v_world = pos;
    // the three corners carry the triangle's one colour; blending them keeps
    // every instance attribute referenced, so no driver's linker drops one
    v_color = in_c0.xyz * u + in_c1.xyz * v + in_c2.xyz * w; v_index = in_c0.w;
    v_normal = rot * n;
    v_rest = in_r0 * u + in_r1 * v + in_r2 * w;
    v_ao = in_p0.w * u + in_p1.w * v + in_p2.w * w;
    v_world_y = pos.y;
}
"""
_SCREEN_VSH = """
#version 330
in vec3 in_ndc; in vec3 in_color;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
void main() {
    gl_Position = vec4(in_ndc, 1.0); v_color = in_color; v_normal = vec3(0.0, 0.0, 1.0);
    v_rest = vec3(0.0); v_ao = 1.0; v_index = 0.0; v_world_y = 0.0;
}
"""
_STENCIL_VSH = """
#version 330
in vec2 in_pos;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); }
"""
_STENCIL_FSH = """
#version 330
out vec4 f_color;
void main() { f_color = vec4(1.0); }
"""
_SHADOW_GEOM_VSH = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
void main() { gl_Position = mvp * vec4(in_pos, 1.0); }
"""
_SHADOW_FSH = """
#version 330
uniform sampler2D shadow_tex; uniform sampler2D mask_tex;
uniform vec2 target_size; uniform vec3 shadow_color; uniform float opacity;
out vec4 f_color;
void main() {
    vec2 uv = gl_FragCoord.xy / target_size;
    // A foreground mask hides the shadow exactly as it hides the actor.
    if (texture(mask_tex, uv).r > 0.5) discard;
    // Coverage is binary, so overlapping limbs darken a pixel once.
    if (texture(shadow_tex, uv).r < 0.5) discard;
    // A per-channel factor <= 1.0 (shadow_color is 0..1), multiplied
    // (not alpha-blended) into the destination below: this can only ever
    // scale the background down toward the room's ambient hue, never
    // brighten it, unlike a src-alpha blend which pulls the destination
    // toward ambient from either side.
    f_color = vec4(mix(vec3(1.0), shadow_color, opacity), 1.0);
}
"""


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


def camera_matrix(view, scale):
    """(4,4) float32 view-projection matrix: world-homogeneous @ m.T gives
    clip space (row-vector convention, matching the parity test).

    `scale` is accepted for interface symmetry with the rest of this module
    (and to leave room for a future per-scale tweak) but is not used here:
    NDC is resolution independent, and the internal target's actual pixel
    resolution is applied later by the GL viewport, not by this matrix.
    """
    state = view.state
    rot = rotation_matrix(state)
    translate = np.eye(4)
    translate[:3, 3] = (-state.x, -state.y, -state.z)
    rotate = np.eye(4)
    rotate[:3, :3] = rot
    proj = np.array([
        [state.focal2 / SCREEN_CENTER_X, 0, 0, 0],
        [0, -state.focal3 / SCREEN_CENTER_Y, 0, 0],
        [0, 0, _DEPTH_A, _DEPTH_B],
        [0, 0, 1.0, 0],
    ])
    shift = np.eye(4)
    shift[2, 3] = state.focal1  # depth = z + focal1 becomes the clip w
    m = proj @ shift @ rotate @ translate
    return m.astype(np.float32)


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
        self._mask_tex = None
        self._mask_fbo = None
        self._shadow_tex = None
        self._shadow_fbo = None
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

            self._shadow_tex = ctx.texture(self.size, 1)
            self._shadow_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._shadow_tex.repeat_x = False
            self._shadow_tex.repeat_y = False
            self._shadow_fbo = ctx.framebuffer(color_attachments=[self._shadow_tex])
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

            self._bg_prog = ctx.program(vertex_shader=_BG_VSH, fragment_shader=_BG_FSH)
            self._actor_prog = ctx.program(vertex_shader=_ACTOR_VSH, fragment_shader=_ACTOR_FSH)
            self._screen_prog = ctx.program(vertex_shader=_SCREEN_VSH, fragment_shader=_ACTOR_FSH)
            self._screen_prog["shading"].value = 0  # lines/points are never shaded
            self._screen_prog["lighting"].value = 0
            self._stencil_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=_STENCIL_FSH)

            # 256 palette indices x 2 rows of 4 float parameters; uploaded
            # whenever an actor hands over a table object we have not seen.
            self._material_tex = ctx.texture((PALETTE_SIZE, 2), 4, dtype="f4")
            self._material_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

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

            # The tessellating programs and their sub-patch buffers exist
            # whatever `smoothing` says: the option is a per-frame choice
            # (Renderer.set_options rebuilds the backend anyway), and
            # compiling at construction is how every other program fails
            # over to the software backend when a driver rejects it.
            self._tess_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_ACTOR_FSH)
            self._tess_shadow_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_STENCIL_FSH)
            self._tess_prog["travel"].value = (0.0, 1.0, 0.0)
            self._tess_layout = instance_layout(self._tess_prog)
            self._tess_shadow_layout = instance_layout(self._tess_shadow_prog)
            for level in SMOOTHING_LEVELS[1:]:
                self._subpatch_bufs[level] = ctx.buffer(np.ascontiguousarray(subpatch(level), dtype="f4").tobytes())

            self._sphere = icosphere(1)
        except Exception:
            self.release()
            raise

    def release(self):
        # `self._target` is intentionally absent: it aliases either
        # `self._ms_fbo` (when msaa is on) or `self._fbo` (when it's off),
        # and each of those is released below under its own name. Releasing
        # it a second time through `self._target` would be a double-release
        # of the same GL object.
        for resource in (
            self._quad_vao, self._quad,
            self._thumb_quad_vao, self._thumb_quad,
            self._stencil_prog, self._screen_prog, self._actor_prog, self._bg_prog,
            self._material_tex,
            self._tess_prog, self._tess_shadow_prog, *self._subpatch_bufs.values(),
            self._shadow_quad_vao, self._shadow_quad,
            self._shadow_prog, self._shadow_geom_prog,
            self._shadow_fbo, self._shadow_tex,
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
            # Best-effort: prev_fbo can have been release()'d by another
            # backend sharing this ctx between when we captured it and now
            # (moderngl.InvalidObject`d, not cleared) -- restoring a dead
            # framebuffer isn't recoverable, so just leave ours bound.
            if prev_fbo is not None and not isinstance(prev_fbo.mglo, moderngl.InvalidObject):
                prev_fbo.use()

    def _draw_frame(self, frame):
        self._target.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.disable(moderngl.BLEND)
        self._target.color_mask = (True, True, True, True)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)

        self._draw_background(frame.background)

        mvp = camera_matrix(frame.camera, self._options.scale)
        rot = rotation_matrix(frame.camera.state).astype("f4")
        scene_lit = self._options.lighting == "scene"
        level = self._options.smoothing
        travel = None
        if scene_lit:
            # rotation_matrix maps world -> camera and is orthonormal, so
            # its transpose maps back. `direction` points toward the light;
            # light travels the other way. Computed only here so the
            # byte-for-byte `fixed` escape hatch never touches frame.light.
            travel = -(rot.astype(np.float64).T
                       @ np.asarray(frame.light.direction, np.float64))
            self._material_tex.use(location=3)
        self._set_frame_uniforms(self._actor_prog, frame, mvp, rot, scene_lit)
        if level:
            self._set_frame_uniforms(self._tess_prog, frame, mvp, rot, scene_lit)
        self._screen_prog["target_size"].value = self.size

        palette = frame.palette.astype("f4") / 255.0
        mask_by_id = {mask.id: mask for mask in frame.masks}

        for actor in frame.actors:
            masks = [mask_by_id[i] for i in actor.mask_ids if i in mask_by_id]
            self._rasterize_masks(masks)  # switches to the mask FBO and disables depth test

            instances = None
            if level:
                data = self._instance_data(actor.geometry, np.asarray(actor.position, np.float64), palette)
                instances = (self._ctx.buffer(data.tobytes()), len(data)) if len(data) else None

            if scene_lit and self._rasterize_shadow(actor, travel, mvp):
                self._composite_shadow(frame.light)

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
                self._draw_actor_tessellated(actor, frame, palette, instances, level)
                if instances is not None:
                    instances[0].release()
            else:
                self._draw_actor(actor, frame, palette)
            self._ctx.disable(moderngl.DEPTH_TEST)

        if self._ms_fbo is not None:
            # Resolves the multisample buffer down into `.texture`, which is
            # what read_rgb, thumbnail and Renderer all read.
            self._ctx.copy_framebuffer(self._fbo, self._ms_fbo)

    def _set_frame_uniforms(self, prog, frame, mvp, rot, scene_lit):
        """Everything an actor program needs once per frame. Shared by
        _actor_prog and _tess_prog so the two can never disagree about the
        light; the values are exactly what _draw_frame set inline before."""
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
            prog["contact_height"].value = CONTACT_HEIGHT
            prog["material_tex"].value = 3
        else:
            prog["lighting"].value = 0
            prog["light"].value = LIGHT_DIR
            prog["key_tint"].value = (0.0, 0.0, 0.0)
            prog["fill_tint"].value = (0.0, 0.0, 0.0)
            prog["preset_a"].value = (0.0, 0.0, 0.0)
            prog["preset_b"].value = (0.0, 0.0, 0.0)
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
        into the single-channel coverage texture. Returns whether anything
        was actually rasterised, so the caller can skip compositing an
        empty coverage texture entirely.

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

    def _composite_shadow(self, light):
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
        pass before any actor is drawn."""
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
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = moderngl.DST_COLOR, moderngl.ZERO
        self._shadow_quad_vao.render(moderngl.TRIANGLES)
        self._ctx.disable(moderngl.BLEND)

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
        params = table.parameters()                      # (256, 8)
        rows = np.stack([params[:, :4], params[:, 4:]], axis=0)   # (2, 256, 4): texture row 0, row 1
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
