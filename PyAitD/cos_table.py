# SPDX-License-Identifier: GPL-2.0-only
"""1024-entry fixed-point sine table (FITD cosTable.cpp, scale 32768).

COS[i] ~= sin(i * 2*pi/2048) * 32768. Index 0 is 4 in FITD's table (quirk,
kept for byte-exact behavior: rotation code never reads sin(0), but reads
index 0 as cos(3*pi/4) ~ 0).
"""
import math

COS_TABLE = [max(min(int(math.sin(i * math.pi / 512) * 32768), 32767), -32767) for i in range(1024)]
COS_TABLE[0] = 4
