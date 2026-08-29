# SPDX-License-Identifier: GPL-2.0-only
"""Every GLSL source the GL backend compiles, as plain strings.

Strings only -- no imports, no functions, no state (tests/test_layering.py
pins that). render_gl.py imports them under its historical underscore
names, so every internal reference and every test import is unchanged."""
BG_VSH = """
#version 330
in vec2 in_pos; in vec2 in_uv; out vec2 v_uv;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); v_uv = in_uv; }
"""
BG_FSH = """
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
ACTOR_VSH = """
#version 330
uniform mat4 mvp; uniform mat3 rot;
// The receiver's place in the light-view depth map: its world position
// pushed along its world normal, so a surface never shadows itself at
// its own depth. Unread under shadows=hard (light_vp stays zero).
uniform mat4 light_vp; uniform float normal_offset;
// Camera-space position, for the fragment shader's screen-space
// derivatives. A direction would not do: bump needs dP/dx and dP/dy.
uniform mat4 view;
in vec3 in_pos; in vec3 in_normal; in vec3 in_color; in vec3 in_rest; in float in_ao; in float in_index;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec4 v_shadow; out vec3 v_view;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_color = in_color; v_normal = rot * in_normal;
    v_rest = in_rest; v_ao = in_ao; v_index = in_index;
    v_world_y = in_pos.y;   // in_pos is already world space: the actor position was added on the CPU
    v_shadow = light_vp * vec4(in_pos + in_normal * normal_offset, 1.0);
    v_view = (view * vec4(in_pos, 1.0)).xyz;
}
"""
ACTOR_FSH = """
#version 330
uniform int shading; uniform int lighting;
// key_tint/fill_tint are shading_terms()'s *normalised tints*, not
// reflectances: they carry the room's hue and sum to a peak of 1.0. The
// shadow composite's `shadow_color` is the other thing -- SceneLight's raw
// ambient, an absolute reflectance. Same room, two different quantities.
uniform vec3 light; uniform vec3 key_tint; uniform vec3 fill_tint;
uniform sampler2D mask_tex; uniform vec2 target_size;
// Materials (scene lighting only). material_tex is 256x3 RGBA32F: row 0 is
// (roughness, specular, metallic, rim), row 1 (detail, detail_scale,
// detail_kind, 0), row 2 (bump, sss, emissive, 0) for the palette index in
// v_index. preset_a/preset_b/preset_c are the RealismPreset strengths
// (spec, rim, ao), (contact, detail, hemisphere) and (bump, sss, emissive);
// under realism=classic all nine are 0 and every term below is exactly 1.0
// or 0.0, leaving `base` untouched.
uniform sampler2D material_tex;
uniform vec3 preset_a; uniform vec3 preset_b; uniform vec3 preset_c;
uniform float plane_y; uniform float contact_height;
// The light-view depth map (shadows=soft): hardware-compared, bilinear.
// self_shadow gates the lookup; depth_bias is in map depth units, from
// SHADOW_BIAS_UNITS over the map's extent along the light.
uniform sampler2DShadow shadow_map; uniform int self_shadow; uniform float depth_bias;
in vec3 v_color; in vec3 v_normal; in vec3 v_rest; in float v_ao; flat in float v_index; in float v_world_y;
in vec4 v_shadow; in vec3 v_view;
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

    int index = int(v_index + 0.5);
    vec4 m0 = texelFetch(material_tex, ivec2(index, 0), 0);
    vec4 m1 = texelFetch(material_tex, ivec2(index, 1), 0);
    // Mikkelsen's unparametrized bump: perturb the normal by the screen-space
    // gradient of a height field, using derivatives of the camera-space
    // position instead of a tangent frame. FITD bodies carry no UVs and no
    // tangents, so this is the only bump that is available at all.
    //
    // Every derivative is taken here, at top level. dFdx/dFdy/fwidth are
    // undefined inside non-uniform control flow, and both `relief` and
    // `m2.x` come from texture-dependent values -- so the *branch* below
    // tests preset_c.x, a uniform, and only the assignment to `n` sits
    // inside it. That branch is also what keeps realism=classic
    // byte-exact: the unguarded form still evaluates
    // normalize(abs(det) * n), which is n mathematically but not
    // bit-for-bit. (`relief` is the height field; the half vector below is
    // already called `h`.)
    vec4 m2 = texelFetch(material_tex, ivec2(index, 2), 0);
    // The height is a *length*, in the same units as v_view -- Mikkelsen's
    // formula divides the height gradient by the position gradient, so a
    // height that did not scale with the geometry would give a slope of
    // detail/1_unit and vanish on FITD's hundreds-of-units bodies. One
    // detail_scale is one noise cell, so `detail * detail_scale` makes a
    // material's relief slope simply `detail` times the noise's own
    // gradient, at whatever size the body is modelled.
    float relief = m1.x * m1.y * detail_noise(v_rest / m1.y, int(m1.z + 0.5));
    vec3 sx = dFdx(v_view), sy = dFdy(v_view);
    vec3 r1 = cross(sy, n), r2 = cross(n, sx);
    float det = dot(sx, r1);
    vec2 dh = vec2(dFdx(relief), dFdy(relief));
    vec3 grad = sign(det) * (dh.x * r1 + dh.y * r2);
    // One noise cell shrinking toward half a pixel is relief the frame
    // cannot resolve; fading it out there is what stops a hero shimmering
    // as he walks away.
    vec3 fw = fwidth(v_rest / m1.y);
    float fade = 1.0 - smoothstep(0.25, 0.5, max(fw.x, max(fw.y, fw.z)));
    // det == 0 means the shading normal lies in the screen-space tangent
    // plane -- which FITD geometry reaches whenever a body's authored
    // normal disagrees with its facet, and which would leave
    // normalize(0 * n - 0) undefined. There is no frame to bump against
    // there, so the normal is left alone.
    if (preset_c.x > 0.0 && det != 0.0) {
        n = normalize(abs(det) * n - preset_c.x * m2.x * fade * grad);
    }

    float vis = 1.0;
    if (self_shadow == 1) {
        // How much of the key reaches this fragment: a slope-scaled bias in
        // map depth on top of the vertex shader's normal offset, four
        // hardware-compared taps averaged into a soft edge. Under
        // shadows=hard the branch is skipped and vis stays exactly 1.0, so
        // `* vis` below is the identity and `base` is the classic
        // expression bit for bit.
        vec4 s = v_shadow;
        s.z -= depth_bias * (1.0 + 2.0 * (1.0 - abs(dot(n, l)))) * s.w;
        vis = 0.25 * (textureProj(shadow_map, s)
                    + textureProjOffset(shadow_map, s, ivec2(1, 0))
                    + textureProjOffset(shadow_map, s, ivec2(0, 1))
                    + textureProjOffset(shadow_map, s, ivec2(1, 1)));
    }
    // Half-Lambert: the lit side reaches fill_tint + key_tint, the shadow
    // side falls to fill_tint rather than to black. `base` is the whole of
    // realism=classic's answer and must stay this exact expression.
    float wrapped = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
    // The key's share is what a shadow removes; the fill's share stays, so
    // a shadowed limb falls to the room's fill colour and never to black.
    vec3 base = v_color * (fill_tint + key_tint * wrapped * wrapped * vis);

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
    vec3 spec = key_tint * mix(vec3(1.0), v_color, m0.z) * pow(max(dot(n, h), 0.0), gloss) * m0.y * preset_a.x * vis;
    vec3 rim = key_tint * pow(1.0 - max(dot(n, view), 0.0), 3.0) * m0.w * preset_a.y;
    float grain = 1.0 + preset_b.y * m1.x * detail_noise(v_rest / m1.y, int(m1.z + 0.5));
    f_color = vec4(base * (grain * hemi * occl) + spec + rim, 1.0);
}
"""
TESS_VSH = """
#version 330
// PN-triangle tessellation, one instance per source triangle (see
// _INSTANCE_ATTRIBUTES), evaluated at the sub-patch barycentric in in_bary.
// Emits exactly _ACTOR_VSH's varyings so _ACTOR_FSH is reused unchanged;
// refine.evaluate is the numpy twin the parity test pins this against.
uniform mat4 mvp; uniform mat3 rot;
uniform mat4 light_vp; uniform float normal_offset;
// Camera-space position, for the fragment shader's screen-space
// derivatives. A direction would not do: bump needs dP/dx and dP/dy.
uniform mat4 view;
// project == 1 is the shadow mode: the evaluated point slides along
// `travel` onto the plane y == plane_y before mvp -- lighting.project_to_plane's
// math for an ALREADY-CLAMPED travel. This shader does no clamping itself:
// the caller must tip `travel` onto the MIN_UP cone (lighting._clamp_downward)
// before writing this uniform, exactly as project_to_plane does on the CPU
// side, or an unclamped near-horizontal travel divides by a near-zero
// travel.y here.
uniform int project; uniform vec3 travel; uniform float plane_y;
// Cast mode only: the camera's world x axis, tan of the light source's
// angular radius, the penumbra radius the blur can honour, and the target
// size in pixels -- a caster's height above its plane becomes a penumbra
// width in world units and then a radius in pixels, written to v_penumbra
// as a fraction of r_max. Under project == 0 v_penumbra is 0 and unread.
uniform vec3 right; uniform float tan_source; uniform float r_max; uniform vec2 target_size;
in vec3 in_bary;
in vec4 in_p0; in vec4 in_n0; in vec4 in_c0; in vec3 in_r0;
in vec4 in_p1; in vec4 in_n1; in vec4 in_c1; in vec3 in_r1;
in vec4 in_p2; in vec4 in_n2; in vec4 in_c2; in vec3 in_r2;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec3 v_world;   // the evaluated world position: read back by transform feedback in tests, unused by the fragment shader
out vec3 v_view;
out float v_penumbra;
out vec4 v_shadow;

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
    v_shadow = light_vp * vec4(pos + n * normal_offset, 1.0);
    v_penumbra = 0.0;
    if (project == 1) {
        float drop = plane_y - pos.y;                   // height above the plane: world y grows downward
        pos += (plane_y - pos.y) / travel.y * travel;
        // penumbra width = drop * tan(source angle), projected to pixels
        // along the camera's x axis at the shadow point's own depth
        vec4 a = mvp * vec4(pos, 1.0);
        vec4 b = mvp * vec4(pos + right * drop * tan_source, 1.0);
        vec2 px = (b.xy / max(b.w, 1.0) - a.xy / max(a.w, 1.0)) * 0.5 * target_size;
        v_penumbra = clamp(length(px) / r_max, 0.0, 1.0);
    }
    gl_Position = mvp * vec4(pos, 1.0);
    v_world = pos;
    v_view = (view * vec4(pos, 1.0)).xyz;
    // the three corners carry the triangle's one colour; blending them keeps
    // every instance attribute referenced, so no driver's linker drops one
    v_color = in_c0.xyz * u + in_c1.xyz * v + in_c2.xyz * w; v_index = in_c0.w;
    v_normal = rot * n;
    v_rest = in_r0 * u + in_r1 * v + in_r2 * w;
    v_ao = in_p0.w * u + in_p1.w * v + in_p2.w * w;
    v_world_y = pos.y;
}
"""
SCREEN_VSH = """
#version 330
in vec3 in_ndc; in vec3 in_color;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec4 v_shadow; out vec3 v_view;
void main() {
    gl_Position = vec4(in_ndc, 1.0); v_color = in_color; v_normal = vec3(0.0, 0.0, 1.0);
    v_rest = vec3(0.0); v_ao = 1.0; v_index = 0.0; v_world_y = 0.0;
    v_shadow = vec4(0.0);   // lines and points never reach the term
    v_view = vec3(0.0);     // nor the derivative bump
}
"""
STENCIL_VSH = """
#version 330
in vec2 in_pos;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); }
"""
STENCIL_FSH = """
#version 330
out vec4 f_color;
void main() { f_color = vec4(1.0); }
"""
SHADOW_GEOM_VSH = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
void main() { gl_Position = mvp * vec4(in_pos, 1.0); }
"""
SHADOW_FSH = """
#version 330
uniform sampler2D shadow_tex; uniform sampler2D mask_tex;
uniform vec2 target_size; uniform vec3 shadow_color; uniform float opacity;
uniform int soft;
out vec4 f_color;
void main() {
    vec2 uv = gl_FragCoord.xy / target_size;
    float cover = texture(shadow_tex, uv).r;
    if (soft == 0) {
        // The per-actor path, verbatim: this actor's foreground masks hide
        // its shadow exactly as they hide the actor, and coverage is
        // binary, so overlapping limbs darken a pixel once.
        if (texture(mask_tex, uv).r > 0.5) discard;
        if (cover < 0.5) discard;
        cover = 1.0;
    } else if (cover <= 0.0) {
        // The gathered path: every cast was erased by its own actor's
        // masks and softened before this runs; coverage is fractional.
        discard;
    }
    // A per-channel factor <= 1.0 (shadow_color is 0..1), multiplied
    // (not alpha-blended) into the destination below: this can only ever
    // scale the background down toward the room's ambient hue, never
    // brighten it, unlike a src-alpha blend which pulls the destination
    // toward ambient from either side.
    f_color = vec4(mix(vec3(1.0), shadow_color, opacity * cover), 1.0);
}
"""
SHADOW_CAST_FSH = """
#version 330
// The gathered ground-shadow cast: coverage in R, and in G the
// *complement* of the penumbra radius, 1 - r / r_max. This actor's own
// foreground masks erase its cast here, once, so the gathered coverage
// needs no mask at composite time.
//
// Both channels blend with MAX, which is the union of coverage in R and,
// because G holds the complement, the *smallest* radius in G. That is the
// rule this pass needs: a ground pixel lit through two blockers is as
// sharp as the nearer one, and a solid body's own heights all project
// across each other, so keeping the largest radius would leave its whole
// shadow as soft as its highest point and never harden at the feet. GL
// gives one blend equation to both colour channels, so the complement is
// what buys MIN on G without a second target or a second pass.
uniform sampler2D mask_tex; uniform vec2 target_size;
in float v_penumbra;
out vec4 f_color;
void main() {
    if (texture(mask_tex, gl_FragCoord.xy / target_size).r > 0.5) discard;
    f_color = vec4(1.0, 1.0 - v_penumbra, 0.0, 0.0);
}
"""
SHADOW_BLUR_FSH = """
#version 330
// One axis of the penumbra blur: each covered source pixel is spread over
// a box of its own radius, written as a gather -- this output pixel asks
// every neighbour within r_max whether that neighbour's radius reaches it,
// and takes cover / (2 r + 1) from each that does, carrying the largest
// radius that reached it into G for the second axis. lighting.soften is
// the numpy twin the parity test pins this against.
//
// G is the radius's complement, 1 - r / r_max, in this pass's input and
// its output alike: the cast writes it that way so MAX blending keeps the
// smallest radius (see SHADOW_CAST_FSH), and both axes run this same
// shader, so the second one reads back what the first one wrote. Only the
// decode and the store are complemented -- the carry is still the largest
// radius that reached the pixel, taken on the decoded value.
uniform sampler2D src; uniform ivec2 axis; uniform int r_max;
out vec4 f_color;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(src, 0);
    float cover = 0.0;
    float reach = 0.0;
    for (int d = -r_max; d <= r_max; d++) {
        ivec2 q = p + axis * d;
        if (q.x < 0 || q.y < 0 || q.x >= size.x || q.y >= size.y) continue;
        vec2 s = texelFetch(src, q, 0).rg;
        float r = floor((1.0 - s.g) * float(r_max) + 0.5);
        if (s.r > 0.0 && float(abs(d)) <= r) {
            cover += s.r / (2.0 * r + 1.0);
            reach = max(reach, r);
        }
    }
    f_color = vec4(min(cover, 1.0), 1.0 - reach / float(r_max), 0.0, 0.0);
}
"""
