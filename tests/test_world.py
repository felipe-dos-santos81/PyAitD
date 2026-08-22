# SPDX-License-Identifier: GPL-2.0-only
from maitd.world import CameraState, rotate_step, transform_point


def test_identity_camera_no_rotation():
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100)
    cam.angles()
    assert transform_point(100, 50, 200, cam) == (100, 50, 200)


def test_rotate_90_degrees():
    # angle 0x100 = 90 deg. FITD Rotate: z_out = cos*y - sin*z ; x_out = sin*y + cos*z
    # cos(90)=COS[0x200]=0, sin(90)=COS[0x100]=32767: (32767*n)<<1 & 0xFFFF0000 keeps 9*n for n=10
    assert rotate_step(0x100, 10, 20) == (9, -19)
    assert rotate_step(0x100, 10, 0)[0] == 9
    assert rotate_step(0x100, 0, 10)[1] == -9


def test_rotate_step_identity():
    assert rotate_step(0, 10, 20) == (20, 10)  # angle==0 branch: x_out = z, z_out = y


def test_camera_from_room_coords():
    from maitd.formats import Camera
    cam = Camera(109, 185, 0, -741, 280, -116, 300, 189, 158)
    state = CameraState.from_camera(cam, world_x=0, world_y=0, world_z=0)
    assert (state.x, state.y, state.z) == (-7410, -2800, 1160)


def test_projection_center():
    # a point exactly at the camera origin + perspective: Z = focal1 -> X/Z*fov + center == center
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 189, 158)
    cam.angles()
    px, py, depth = cam.project(0, 0, 0)
    assert px == 160.0 and py == 100.0 and depth == 300
    # depth clip: Z + perspective <= 50 -> sentinel
    px2, py2, d2 = cam.project(0, 0, -290)
    assert (px2, py2, d2) == (-10000.0, -10000.0, -10000.0)
