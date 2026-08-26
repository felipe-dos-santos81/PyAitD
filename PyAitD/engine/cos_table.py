# SPDX-License-Identifier: GPL-2.0-only
"""1024-entry fixed-point sine table (FITD cosTable.cpp, scale 32768).

COS[i] ~= sin(i * 2*pi/2048) * 32768. Index 0 is 4 in FITD's table (quirk,
kept for byte-exact behavior: rotation code never reads sin(0), but reads
index 0 as cos(3*pi/4) ~ 0).
"""
import math

COS_TABLE = [max(min(int(math.sin(i * math.pi / 512) * 32768), 32767), -32767) for i in range(1024)]
COS_TABLE[0] = 4


def sin_cos(angle):
    """FITD cosTable.cpp lookup, scaled to a float unit circle (scale 32768).

    Parity-critical: scene.CameraView.camera_space and render_gl.rotation_matrix
    must use this exact same helper (term-for-term identical formula), or the
    GL and software/picking rotation paths silently diverge.
    """
    a = angle & 0x3FF
    return COS_TABLE[(a + 0x100) & 0x3FF] / 32768.0, COS_TABLE[a] / 32768.0
