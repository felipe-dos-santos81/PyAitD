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
in vec3 in_pos; in vec3 in_normal; in vec3 in_color; in vec3 in_rest; in float in_ao; in float in_index; in vec2 in_uv;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec4 v_shadow; out vec3 v_view; out vec2 v_uv;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_color = in_color; v_normal = rot * in_normal;
    v_rest = in_rest; v_ao = in_ao; v_index = in_index;
    v_world_y = in_pos.y;   // in_pos is already world space: the actor position was added on the CPU
    v_shadow = light_vp * vec4(in_pos + in_normal * normal_offset, 1.0);
    v_view = (view * vec4(in_pos, 1.0)).xyz;
    v_uv = in_uv;
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
// The body's painted albedo atlas (Task 4's resolved UVs). has_body_texture
// gates the sample so lines, points, spheres and unpainted bodies -- all of
// which leave v_uv at its default -- never touch the sampler at all.
uniform sampler2D body_albedo; uniform int has_body_texture;
// Screen-space AO (Task 4). ssao_tex is the half-resolution occlusion
// texture, sampled at full target resolution the same way mask_tex is;
// occlusion_on gates the sample so occlusion="off" never touches the
// sampler, mirroring has_body_texture's own gate above.
uniform sampler2D ssao_tex; uniform int occlusion_on;
in vec3 v_color; in vec3 v_normal; in vec3 v_rest; in float v_ao; flat in float v_index; in float v_world_y;
in vec4 v_shadow; in vec3 v_view; in vec2 v_uv;
out vec4 f_color;

// Warm blood under thin skin: the tint the terminator picks up. One
// constant, not a material field -- the hue is a property of people, not
// of this palette index.
const vec3 SSS_TINT = vec3(1.0, 0.82, 0.74);

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
// The per-kind stretch of the noise coordinate, split out of detail_noise
// so that the bump's fade can take fwidth of the coordinate the noise
// really samples. Streak and brushed stretch an axis by 4 and by 6, and a
// fwidth measured on the unstretched cell misses that by the same factor:
// brushed metal ran at 2.4x Nyquist at z=600 with the fade still reading
// 1.0, which is exactly the shimmer the fade exists to stop.
vec3 noise_coord(vec3 p, int kind) {
    if (kind == 3) return vec3(p.x * 4.0, p.y * 0.25, p.z * 4.0);   // streak along y, the limb axis
    if (kind == 4) return vec3(p.x * 0.25, p.y * 6.0, p.z * 0.25);  // brushed across it
    return p;                                                       // grain and weave sample the cell itself
}
// `p` has already been through noise_coord.
float detail_noise(vec3 p, int kind) {
    if (kind == 2) return sin(p.x * 6.2832) * sin(p.z * 6.2832) * (0.5 + 0.5 * value_noise(p));  // weave
    if (kind == 1 || kind == 3 || kind == 4) return value_noise(p);                              // grain, streak, brushed
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
    // Every derivative this bump needs is taken here, at top level -- but
    // the rule is narrower than "at top level". dFdx/dFdy/fwidth are
    // undefined inside *non-uniform* control flow only, and the one branch
    // below tests preset_c.x, a uniform, so the whole block would be legal
    // inside it. What genuinely has to stay out here is `nc`, `dn` and
    // `relief`: the grain colour multiply at the end of main reads `dn`
    // unconditionally. Everything after them -- sx, sy, r1, r2, det, dh,
    // grad, fw, fade, ref, k, surf_grad -- feeds the guarded assignment
    // and nothing else, so sinking it into the branch is a legitimate
    // optimisation, not a correctness bug; this comment does not forbid
    // it. The branch itself is what keeps realism=classic byte-exact:
    // unguarded, the line would still evaluate normalize(n) with a zero
    // perturbation, which is n mathematically but not bit-for-bit.
    // (`relief` is the height field; the half vector below is already
    // called `h`.)
    vec4 m2 = texelFetch(material_tex, ivec2(index, 2), 0);
    // One coordinate, one sample, read by all three consumers: the height
    // here, the fade below and the surviving grain colour multiply at the
    // end of main. Written once so the fade can never drift out of step
    // with what the noise samples again.
    int kind = int(m1.z + 0.5);
    vec3 nc = noise_coord(v_rest / m1.y, kind);
    float dn = detail_noise(nc, kind);
    // The height is a *length*, in the same units as v_view -- Mikkelsen's
    // formula divides the height gradient by the position gradient, so a
    // height that did not scale with the geometry would give a slope of
    // detail/1_unit and vanish on FITD's hundreds-of-units bodies. One
    // detail_scale is one noise cell, so `detail * detail_scale` makes a
    // material's relief slope simply `detail` times the noise's own
    // gradient, at whatever size the body is modelled.
    float relief = m1.x * m1.y * dn;
    vec3 sx = dFdx(v_view), sy = dFdy(v_view);
    vec3 r1 = cross(sy, n), r2 = cross(n, sx);
    float det = dot(sx, r1);
    vec2 dh = vec2(dFdx(relief), dFdy(relief));
    vec3 grad = sign(det) * (dh.x * r1 + dh.y * r2);
    // One noise cell shrinking toward half a pixel is relief the frame
    // cannot resolve; fading it out there is what stops a hero shimmering
    // as he walks away.
    vec3 fw = fwidth(nc);
    float fade = 1.0 - smoothstep(0.25, 0.5, max(fw.x, max(fw.y, fw.z)));
    // det is dot(cross(sx, sy), n), so abs(det) / length(cross(sx, sy)) is
    // |cos| of the angle between the shading normal and the facet the pixel
    // actually covers: 1 where they agree, 0 where the normal has fallen
    // into the screen-space tangent plane. FITD reaches that whenever an
    // authored normal disagrees with its facet, and a smoothed normal
    // sweeps through it continuously -- so the degeneracy is a band, not a
    // point, and a `det != 0.0` test would be a cliff with the bump at full
    // wrong strength one ULP off the line. Ramp it out instead.
    float ref = length(cross(sx, sy));
    float k = smoothstep(0.0, 0.25, abs(det) / max(ref, 1e-20));
    // Mikkelsen's line divided through by abs(det): the surface gradient,
    // which is the quantity that actually tilts the normal. Dividing is
    // what makes the exactly-degenerate frame a limit -- `n` keeps its
    // unit coefficient as k reaches 0, where the undivided form would
    // shrink to normalize(0).
    vec3 surf_grad = grad / max(abs(det), 1e-20);
    if (preset_c.x > 0.0) {
        n = normalize(n - k * preset_c.x * m2.x * fade * surf_grad);
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
    // Paint changes colour, not physics: the sampled albedo replaces the
    // ramp colour, while the palette-index material table keeps driving
    // specular, rim, bump, sss and emissive. A negative uv marks a sphere,
    // which shares the triangle buffer and stays untextured.
    vec3 albedo = v_color;
    if (has_body_texture != 0 && v_uv.x >= 0.0) {
        albedo = texture(body_albedo, v_uv).rgb;
    }
    // Screen-space occlusion attenuates the *fill* share and nothing else.
    // The key share is already gated by `vis` (the shadow map), and F's
    // rule holds: a shadowed limb falls to the room's fill, never to
    // black -- so the fill is the one share an occlusion term may touch.
    //
    // Not folded into `occl` below, however much the name invites it:
    // `occl` multiplies the whole of `base`, key share included, as does
    // `hemi`. Either would darken the key light a second time, which the
    // shadow map already owns.
    //
    // ssao is exactly 1.0 when occlusion_on is 0, and multiplying by
    // exactly 1.0 is exact in IEEE 754 -- that, not a mix(), is what
    // makes the off path byte-identical.
    float ssao = 1.0;
    if (occlusion_on != 0) {
        ssao = texture(ssao_tex, gl_FragCoord.xy / target_size).r;
    }
    vec3 base = albedo * (fill_tint * ssao + key_tint * wrapped * wrapped * vis);
    // Peaks at the light/shade boundary (wrapped 0.5, where 4x(1-x) is 1)
    // and vanishes on both the fully lit and the fully unlit side.
    //
    // Gated by `vis`, like the key's own share in `base`: subsurface
    // scattering is key light that entered the surface, so where the
    // shadow map says no key arrives there is nothing to scatter, and a
    // warm terminator across a face standing in another actor's shadow is
    // backwards. `wrapped` is the *geometric* wrap and shadowing does not
    // touch it, so without this factor a fully key-shadowed skin fragment
    // still took the full tint. (`rim` has the same gap and keeps it: it
    // predates this term and is out of scope here.)
    //
    // Under classic preset_c.y is 0, mix(a, b, 0) is exactly a, and base
    // is untouched whatever `vis` is; under shadows=hard `vis` is exactly
    // 1.0, so this is the same expression it was.
    base *= mix(vec3(1.0), SSS_TINT, preset_c.y * m2.y * vis * 4.0 * wrapped * (1.0 - wrapped));

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
    // Blinn-Phong's lobe integrates to less as it tightens, so without
    // (gloss + 8) / 8pi a polished metal reads *dimmer* than a rough one.
    // preset_a.x already zeroes the whole term under classic.
    vec3 spec = key_tint * mix(vec3(1.0), albedo, m0.z) * pow(max(dot(n, h), 0.0), gloss)
              * ((gloss + 8.0) / (8.0 * 3.14159265)) * m0.y * preset_a.x * vis;
    vec3 rim = key_tint * pow(1.0 - max(dot(n, view), 0.0), 3.0) * m0.w * preset_a.y;
    float grain = 1.0 + preset_b.y * m1.x * dn;
    vec3 shaded = base * (grain * hemi * occl) + spec + rim;
    // mix(x, y, 0) is x*(1-0) + y*0 -- exactly x -- so classic is untouched
    // by construction. That is `a` on the nose 0.0, not the general mix
    // the hemisphere comment above warns about; it is the same identity
    // `occl`'s mix(1.0, v_ao, preset_a.z) has always rested on.
    f_color = vec4(mix(shaded, albedo, preset_c.z * m2.z), 1.0);
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
in vec4 in_p0; in vec4 in_n0; in vec4 in_c0; in vec3 in_r0; in vec2 in_uv0;
in vec4 in_p1; in vec4 in_n1; in vec4 in_c1; in vec3 in_r1; in vec2 in_uv1;
in vec4 in_p2; in vec4 in_n2; in vec4 in_c2; in vec3 in_r2; in vec2 in_uv2;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec3 v_world;   // the evaluated world position: read back by transform feedback in tests, unused by the fragment shader
out vec3 v_view;
out float v_penumbra;
out vec4 v_shadow;
out vec2 v_uv;

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
    v_uv = in_uv0 * u + in_uv1 * v + in_uv2 * w;
    v_normal = rot * n;
    v_rest = in_r0 * u + in_r1 * v + in_r2 * w;
    v_ao = in_p0.w * u + in_p1.w * v + in_p2.w * w;
    v_world_y = pos.y;
}
"""
SCREEN_VSH = """
#version 330
in vec3 in_ndc; in vec3 in_color; in vec2 in_uv;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec4 v_shadow; out vec3 v_view; out vec2 v_uv;
void main() {
    gl_Position = vec4(in_ndc, 1.0); v_color = in_color; v_normal = vec3(0.0, 0.0, 1.0);
    v_rest = vec3(0.0); v_ao = 1.0; v_index = 0.0; v_world_y = 0.0;
    v_shadow = vec4(0.0);   // lines and points never reach the term
    v_view = vec3(0.0);     // nor the derivative bump
    v_uv = in_uv;
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
GBUFFER_FSH = """
#version 330
// The SSAO prepass's only output: view-space normal in rgb, positive
// linear view depth in alpha.
//
// Linear depth rather than the depth buffer's projective value, because
// ssao_reference has to reproduce this exactly and a projection inverse
// is the easiest place for a twin and a shader to disagree by a hair.
// The depth attachment is still there -- it is what makes the pass
// depth-test correctly against itself -- but nothing reads it.
//
// Alpha 0.0 marks a pixel no actor covered. ssao_reference and SSAO_FSH
// both treat that as "unoccluded" rather than as depth zero.
//
// v_view.z, not -v_view.z: this engine's camera space is +z-forward (a
// FITD-derived convention, not OpenGL's -z-forward), confirmed against
// the golden frame -- an actor at world z in [580, 820] renders covered
// pixels with v_view.z in [564.5, 696.0], and -v_view.z on the same
// scene is negative everywhere a pixel is covered. Depth is otherwise
// convention-free: it is a positive distance along the view axis, and
// ssao_reference/SSAO_FSH each reconstruct a position from it in their
// own -z-forward space (ssao.py's _view_position sets z = -depth) --
// neither side ever sees an engine-space position, so no sign decision
// is needed here for depth.
//
// focal1: this engine's actual perspective divide is by z + focal1, not
// by bare z (CameraState.project: `depth = z + self.focal1`; see
// GLBackend._proj_xy's docstring for how projection_matrix's `shift`
// gets there). That is not a fudge factor -- this engine's projection
// centre sits at -focal1 along z, so z + focal1 *is* the true pinhole
// distance from the projection centre, the honest linear depth for this
// camera. Writing it (rather than bare v_view.z) is what makes
// `ndc = x * f / depth` exact, which is precisely the relation
// ssao_reference's _view_position/_project and SSAO_FSH all assume --
// with this term included, ssao.py needs no changes of its own to be
// correct. focal1 is per camera, not per vertex, so it arrives as a
// uniform GLBackend._render_gbuffer sets once per frame, the same way
// mvp and rot are, rather than a varying.
//
// Normals are the one quantity that actually crosses the boundary
// between the two spaces, and unlike depth they are not convention-free:
// a surface facing the camera has its normal pointing toward -z in this
// engine's +z-forward space, but ssao.py was written for a -z-forward
// space, where a camera-facing normal points toward +z. Left unmirrored,
// every normal this pass writes would be flipped end-to-end through
// Task 4's whole pipeline -- consistently wrong on both the numpy twin
// and the shader, so the twin-vs-shader parity test would still pass
// while a flat, camera-facing surface occluded itself. diag(1, 1, -1) is
// the fix, applied here rather than in ssao.py (a self-contained
// reference this bridges into, not the space that should change): a
// mirror on z is its own inverse-transpose, so this is exact, not an
// approximation.
in vec3 v_normal;
in vec3 v_view;
uniform float focal1;
out vec4 f_gbuf;
void main() {
    f_gbuf = vec4(normalize(vec3(v_normal.xy, -v_normal.z)), v_view.z + focal1);
}
"""
SSAO_FSH = """
#version 330
// Screen-space ambient occlusion over the half-resolution G-buffer.
//
// Every line here has a counterpart in PyAitD/render/ssao.py's
// ssao_reference, which tests/test_render_gl.py pins this against at
// 4/255 -- the same arrangement `soften` and SHADOW_BLUR_FSH have. When
// you change one, change both, or the test will tell you.
//
// Depth is positive linear view distance in the G-buffer's alpha, and 0.0
// means no actor covered that pixel. Output is a *multiplier*: 1.0 is
// unoccluded, which is what makes an empty G-buffer contribute nothing.
uniform sampler2D gbuf_tex;
uniform sampler2D noise_tex;
uniform vec2 target_size;      // the half-resolution G-buffer's size
uniform vec2 proj_xy;          // the projection's (fx, fy), shared with the twin
uniform float radius;
uniform float bias;
uniform int kernel_count;
uniform vec3 kernel[64];
out vec4 f_color;

vec3 view_position(vec2 uv, float depth) {
    vec2 ndc = uv * 2.0 - 1.0;
    return vec3(ndc.x * depth / proj_xy.x, ndc.y * depth / proj_xy.y, -depth);
}

void main() {
    vec2 uv = gl_FragCoord.xy / target_size;
    vec4 g = texture(gbuf_tex, uv);
    float depth = g.a;
    if (depth <= 0.0) { f_color = vec4(1.0); return; }
    vec3 n = normalize(g.rgb);
    vec3 p = view_position(uv, depth);

    vec2 r = texture(noise_tex, gl_FragCoord.xy / 4.0).rg;
    // Duff et al., "Building an Orthonormal Basis, Revisited". Built from
    // the normal alone and exactly orthonormal for every normal, unlike a
    // Gram-Schmidt against the noise vector, whose tangent collapses
    // toward zero length wherever the noise happens to align with the
    // normal -- measured down to 4.2e-3, which amplifies a last-bit
    // disagreement into a whole flipped kernel sample. The rotation then
    // happens *within* the tangent plane, so the noise still decorrelates
    // neighbouring pixels without ever conditioning the basis.
    float sgn = n.z >= 0.0 ? 1.0 : -1.0;
    float a = -1.0 / (sgn + n.z);
    float b = n.x * n.y * a;
    vec3 b1 = vec3(1.0 + sgn * n.x * n.x * a, sgn * b, -sgn * n.x);
    vec3 b2 = vec3(b, sgn + n.y * n.y * a, -n.y);
    vec3 tangent   =  b1 * r.x + b2 * r.y;
    vec3 bitangent = -b1 * r.y + b2 * r.x;

    float occluded = 0.0;
    for (int i = 0; i < kernel_count; i++) {
        vec3 k = kernel[i];
        vec3 sample_pos = p + (tangent * k.x + bitangent * k.y + n * k.z) * radius;
        if (sample_pos.z >= -1e-6) continue;         // behind the camera: no screen position
        vec2 s_ndc = vec2(sample_pos.x * proj_xy.x, sample_pos.y * proj_xy.y) / (-sample_pos.z);
        vec2 s_uv = clamp(s_ndc * 0.5 + 0.5, vec2(0.0), vec2(1.0));
        float s_depth = texture(gbuf_tex, s_uv).a;
        float sample_dist = -sample_pos.z;
        if (s_depth > 0.0 && s_depth < sample_dist - bias) {
            occluded += clamp(radius / max(abs(depth - s_depth), 1e-6), 0.0, 1.0);
        }
    }
    f_color = vec4(clamp(1.0 - occluded / float(kernel_count), 0.0, 1.0));
}
"""
SSAO_BLUR_FSH = """
#version 330
// One bilateral-ish pass over the occlusion texture: a 4x4 box the width
// of the noise tile, which is exactly what removes the tile's pattern,
// rejecting taps whose depth is far from the centre's so the blur does
// not drag occlusion across a silhouette.
uniform sampler2D ssao_tex;
uniform sampler2D gbuf_tex;
uniform vec2 target_size;
uniform float depth_threshold;
out vec4 f_color;
void main() {
    vec2 texel = 1.0 / target_size;
    vec2 uv = gl_FragCoord.xy / target_size;
    float centre_depth = texture(gbuf_tex, uv).a;
    if (centre_depth <= 0.0) { f_color = vec4(1.0); return; }
    float sum = 0.0;
    float total = 0.0;
    for (int y = -2; y < 2; y++) {
        for (int x = -2; x < 2; x++) {
            vec2 q = uv + vec2(float(x), float(y)) * texel;
            float d = texture(gbuf_tex, q).a;
            // A tap on the far side of a silhouette is a different
            // surface; averaging it in is what makes a thin limb halo.
            if (d > 0.0 && abs(d - centre_depth) < depth_threshold) {
                sum += texture(ssao_tex, q).r;
                total += 1.0;
            }
        }
    }
    f_color = vec4(total > 0.0 ? sum / total : 1.0);
}
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
COMPOSITE_FSH = """
#version 330
// The one full-target pass that puts the actor layer back onto the plate.
//
// The actor layer is premultiplied: its shader writes alpha 1, so a
// multisample resolve of covered and uncovered samples yields colour
// already scaled by coverage, which is exactly what "over" wants. At
// msaa = 0 alpha is 0 or 1 and this is `plate` or `rgb` with no arithmetic
// in between -- byte-exact against drawing the body straight onto the
// plate, which is the identity every composing integration level has
// to hold against level 0.
//
// Sampling is done on the premultiplied values throughout: blurring colour
// and coverage together is what keeps a soft edge from bleeding the
// interior's colour outward into fully transparent pixels.
uniform sampler2D plate_tex; uniform sampler2D actor_tex;
uniform int radius;        // Gaussian half-width in target pixels; 0 = one tap
uniform float inv_sigma2;  // 1 / (2 sigma^2); unread when radius is 0
uniform float cell;        // one plate pixel, in target pixels
uniform int pixelate;      // 1 under `nearest`: fetch per plate cell
uniform vec3 plate_black;   // the room's floor, 0..1 linear RGB
uniform vec3 plate_white;   // the room's ceiling
uniform float plate_grain;  // RMS luma residual of the plate's own dither, at
                            // the plate's own resolution -- estimate_plate's
                            // measurement, uncorrected. `dither` below
                            // reproduces the magnification the room's own
                            // dither went through, and that is what
                            // attenuates it.
uniform int smooth_grain;   // 1 when the background filter interpolates, so
                            // the plate's dither arrives as a ramp across
                            // each cell rather than as hard source texels
uniform float strength;     // the integration level's multiplier, applied to
                            // the toe, the shoulder and the grain alike. The
                            // fourth term, softness, is scaled on the CPU
                            // instead -- `radius` and `inv_sigma2` are
                            // derived from sigma there, so there is nothing
                            // left here to scale. 1.0 is the full match this
                            // pass shipped as; `pixelate` is deliberately
                            // ungraded, being which cell a pixel falls in
                            // rather than an amount of anything.
out vec4 f_color;

// The room is a print with a floor and a ceiling: it cannot show anything
// darker than `plate_black` or brighter than `plate_white`. An actor
// outside that range is a hole cut in the print, or a highlight nothing
// around it could have produced -- so the match is to bring it inside the
// range, and to say nothing at all about a value already in it.
//
// The earlier model pushed toward the ends instead, weighting the push by
// (1 - luma)^4 to confine it there. That confines it only if the actor's
// midtone really is luma 0.5. In this game it is not: the attic's whole
// range is luma 16..124 counts and the figure's median is 47, where the
// quartic is still 0.43 -- so what was meant as an extremes-only
// correction lifted the entire actor, a neutral 60-count grey arriving as
// a warm (71, 63, 62). The clamp below has no midtone behaviour to get
// wrong, because it has no midtone behaviour.
// hash - 0.5 is uniform on [-0.5, 0.5], whose RMS is 1/sqrt(12). Scaling
// by sqrt(12) makes the field's RMS equal `plate_grain` at the plate's own
// resolution -- the amplitude estimate_plate measured -- before `dither`
// magnifies it the way the background filter magnified the room's. Not a
// taste constant: it is what "the plate's own amplitude" resolves to.
const float GAIN = 3.4641016;

// Hoskins' hash11 on a vec2 seed: no sin(), which GPUs implement to wildly
// different precision at large arguments. Seeded on the screen cell alone,
// so the noise sits still like the plate's dither instead of crawling.
float hash21(vec2 v) {
    vec3 p = fract(vec3(v.xyx) * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}

// The room's dither is per-source-texel noise that the background filter
// magnified, so the actor's has to be built the same way rather than
// corrected to the same variance. Under an interpolating filter the
// displayed field is a bilinear ramp between neighbouring source values:
// two fields can share a per-pixel RMS and still read as different
// processes, because what a dither *looks* like is its residual against
// the local mean, and a flat block's is ~3x a ramp's. Building the ramp
// also performs the attenuation `plate.grain_retention` used to apply as
// a scalar, which is why `plate_grain` arrives here uncorrected.
float dither(vec2 frag) {
    if (smooth_grain == 0) {
        // `nearest`, and xbr at the classic size: every displayed pixel is
        // some source texel, so the dither arrives intact and hard-edged.
        // Seeded on the screen cell, which is also the grid `pixelate`
        // fetches the actor on.
        return hash21(floor(frag / cell)) - 0.5;
    }
    // The source coordinate GL_LINEAR samples for this pixel, and the same
    // four-tap blend it performs there.
    vec2 x = frag / cell - 0.5;
    vec2 c = floor(x);
    vec2 f = x - c;
    float n00 = hash21(c);
    float n10 = hash21(c + vec2(1.0, 0.0));
    float n01 = hash21(c + vec2(0.0, 1.0));
    float n11 = hash21(c + vec2(1.0, 1.0));
    return mix(mix(n00, n10, f.x), mix(n01, n11, f.x), f.y) - 0.5;
}

vec4 sample_actor(ivec2 p, ivec2 size) {
    if (pixelate != 0) {
        // The centre of the plate cell this pixel falls in, so a blocky
        // plate gets blocky actors on the same grid.
        vec2 c = (floor(vec2(p) / cell) + 0.5) * cell;
        return texelFetch(actor_tex, clamp(ivec2(c), ivec2(0), size - 1), 0);
    }
    if (radius <= 0) return texelFetch(actor_tex, p, 0);
    vec4 sum = vec4(0.0);
    float total = 0.0;
    // `radius` is a uniform, so this is uniform control flow and the tap
    // count is the same for every pixel of the frame. Edge-clamped rather
    // than skipped, and normalised by the weight actually accumulated, so
    // the border neither darkens nor loses coverage.
    for (int dy = -radius; dy <= radius; dy++) {
        for (int dx = -radius; dx <= radius; dx++) {
            ivec2 q = clamp(p + ivec2(dx, dy), ivec2(0), size - 1);
            float w = exp(-float(dx * dx + dy * dy) * inv_sigma2);
            sum += texelFetch(actor_tex, q, 0) * w;
            total += w;
        }
    }
    return sum / total;
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 a = sample_actor(p, textureSize(actor_tex, 0));
    vec3 plate = texelFetch(plate_tex, p, 0).rgb;
    vec3 c = vec3(0.0);
    if (a.a > 0.0) {
        c = a.rgb / a.a;                        // unpremultiply to tone-match
        // `mix`, not a plain clamp, so `strength` grades it -- and above 1
        // it extrapolates past the range, which is what the top level
        // means. NEUTRAL_PLATE makes this the identity by construction:
        // max(c, 0) and min(c, 1) are c for anything the actor pass wrote.
        c = mix(c, min(max(c, plate_black), plate_white), strength);
        c += plate_grain * strength * dither(gl_FragCoord.xy) * GAIN;
        c = clamp(c, 0.0, 1.0);
    }
    f_color = vec4(plate * (1.0 - a.a) + c * a.a, 1.0);
}
"""
