# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.asset_resolver import AssetResolver
from PyAitD.floor import Floor
from PyAitD.formats import Body, Camera, Room
from PyAitD.game import init_game
from PyAitD.mask_geometry import MaskDraw
from PyAitD.scene import CameraView, FrameDescription, build_frame, mask_applies_to_actor
from PyAitD.skel import skin
from PyAitD.world import CameraState


def _boot(data_dir):
    game = init_game(data_dir)
    game.num_camera = game.new_num_camera
    floor = Floor(data_dir, game.current_floor)
    return game, floor


def _legacy_scene(game, floor):
    """The pre-layer _scene_frame body: what draw_list and actor order were."""
    from PyAitD.actors import anim_player_for, sort_actor_indices
    from PyAitD.picking import actor_bbox
    room = floor.rooms[game.current_room]
    cam = floor.cameras[room.camera_indices[game.num_camera]]
    state = CameraState.from_camera(cam, room.world_x, room.world_y, room.world_z).angles()
    out = []
    for index in sort_actor_indices(game, state.x, state.y, state.z):
        actor = game.actors[index]
        body = game.assets.body(actor.body_num)
        states = ([(0, (0, 0, 0))] * len(body.groups) if actor.anim == -1
                  else anim_player_for(game, index).group_states())
        result = skin(body, states,
                      (actor.world_x + actor.step_x, actor.world_y + actor.step_y, actor.world_z + actor.step_z),
                      state, actor_angles=(actor.alpha, actor.beta, actor.gamma))
        out.append((index, actor_bbox(result), result))
    return out


# --- data_dir-gated tests (skip without game assets; kept per the brief but
# not primary evidence -- see the synthetic tests below for coverage that
# actually runs on this machine). ---


def test_build_frame_matches_legacy_order_and_draw_list(data_dir):
    game, floor = _boot(data_dir)
    frame, draw_list = build_frame(game, floor, AssetResolver(game.assets))
    legacy = _legacy_scene(game, floor)
    assert isinstance(frame, FrameDescription)
    assert draw_list == [(i, bbox) for i, bbox, _ in legacy]
    assert [a.index for a in frame.actors] == [i for i, _, _ in legacy]
    for actor, (_, _, result) in zip(frame.actors, legacy):
        assert actor.logical.points == result.points


def test_mask_ids_follow_the_trigger_rule(data_dir):
    game, floor = _boot(data_dir)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    for actor in frame.actors:
        expected = tuple(m.id for m in frame.masks if mask_applies_to_actor(m, actor.room, actor.zv))
        assert actor.mask_ids == expected


def test_float_projection_parity_with_skin(data_dir):
    game, floor = _boot(data_dir)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    for actor in frame.actors:
        world = actor.geometry.vertices + np.array(actor.position, dtype=np.float32)
        projected = frame.camera.project(world.astype(np.float64))
        logical = np.array(actor.logical.points, dtype=np.float64)
        culled = logical[:, 0] == -10000.0
        assert np.array_equal(projected[culled], logical[culled])
        assert np.abs(projected[~culled][:, :2] - logical[~culled][:, :2]).max() <= 0.5


def test_every_floor_camera_and_body_stays_within_half_a_pixel(data_dir):
    # exhaustive parity: every body at the origin of every camera on floor 0
    from PyAitD.geometry import pose_geometry
    from PyAitD.assets import Assets
    assets = Assets(data_dir)
    floor = Floor(data_dir, 0)
    for room in floor.rooms:
        for cam_idx in room.camera_indices:
            state = CameraState.from_camera(floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z).angles()
            view = CameraView(state)
            for num in range(min(assets.body_count(), 40)):
                body = assets.body(num)
                states = [(0, (0, 0, 0))] * len(body.groups)
                logical = np.array(skin(body, states, (0, 0, 0), state, actor_angles=(0, 0, 0)).points)
                projected = view.project(pose_geometry(body, states, (0, 0, 0)).vertices.astype(np.float64))
                culled = logical[:, 0] == -10000.0
                assert np.abs(projected[~culled][:, :2] - logical[~culled][:, :2]).max(initial=0) <= 0.5


# --- Synthetic tests: no game data required. These are the primary evidence
# for this task -- everything above SKIPs on a machine with no game assets. ---


def test_mask_rule_is_the_render_rule():
    mask = MaskDraw(0, (), (0, 0, 0, 0), viewed_room=0, test_rects=((1, 3, 2, 4),))
    assert mask_applies_to_actor(mask, 0, (10, 20, 0, 0, 30, 40))
    assert not mask_applies_to_actor(mask, 1, (10, 20, 0, 0, 30, 40))
    assert not mask_applies_to_actor(mask, 0, (1000, 1100, 0, 0, 1000, 1100))
    assert not mask_applies_to_actor(mask, 0, None)


def _flat_body(vertices):
    return Body(flags=0, zv=(0, 0, 0, 0, 0, 0), scratch=(), vertices=vertices,
                groups=[], group_order=[], primitives=[])


def test_camera_view_project_matches_skin_across_full_rotation_order():
    # All three camera axes nonzero (alpha=109, beta=185 are the proven
    # "camera2" angles from test_world.py::test_transform_point_camera2_angles;
    # gamma=0x20 added here to exercise the Z rotation too), a large
    # translation (matching real room-coordinate scale, see
    # test_world.py::test_camera_from_room_coords) and small vertex offsets
    # (typical body-model-space magnitude). skel.skin (independent of
    # scene.py) is the ground truth.
    cam = CameraState(109, 185, 0x20, -7410, -2800, 1160, 300, 189, 158).angles()
    vertices = [(0, 0, 0), (50, -30, 80), (-62, 15, -40), (75, 90, -50), (100, 50, 100)]
    position = (30, -10, 200)
    body = _flat_body(vertices)

    logical = np.array(skin(body, [], position, cam).points, dtype=np.float64)
    world = np.array(vertices, dtype=np.float64) + np.array(position, dtype=np.float64)
    projected = CameraView(cam).project(world)

    culled = logical[:, 0] == -10000.0
    assert not culled.any()  # sanity: this scenario exercises the projected branch
    diff = np.abs(projected[:, :2] - logical[:, :2])
    assert diff.max() <= 0.5


def test_camera_view_project_depth_le_50_is_sentinel():
    # Identity rotation, camera at the origin: depth = z + focal1.
    # z=-260 -> depth=40 (culled); z=-250 -> depth=50, the "<=50" boundary
    # (still culled); z=-240 -> depth=60 (not culled).
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()
    world = np.array([[10, 20, -260], [10, 20, -250], [10, 20, -240]], dtype=np.float64)

    body = _flat_body([(10, 20, -260), (10, 20, -250), (10, 20, -240)])
    expected = np.array(skin(body, [], (0, 0, 0), cam).points, dtype=np.float64)
    assert list(expected[:, 0]) == [-10000.0, -10000.0, 176.66666666666666]  # ground truth sanity

    projected = CameraView(cam).project(world)
    assert np.array_equal(projected, expected)


def test_camera_view_project_y_over_10000_is_sentinel():
    # skin culls on world y > 10000 *before* subtracting camera.y (see
    # skel.skin: "if y > 10000" happens before "y -= camera.y"). y=10001 is
    # culled regardless of camera.y; y=10000 (the boundary) is not culled,
    # and camera.y is then subtracted as normal.
    cam = CameraState(0, 0, 0, 0, 9800, 0, 300, 100, 100).angles()
    world = np.array([[0, 10001, 0], [0, 10000, 300]], dtype=np.float64)

    body = _flat_body([(0, 10001, 0), (0, 10000, 300)])
    expected = np.array(skin(body, [], (0, 0, 0), cam).points, dtype=np.float64)
    assert expected[0, 0] == -10000.0 and expected[1, 0] == 160.0  # ground truth sanity

    projected = CameraView(cam).project(world)
    assert np.array_equal(projected, expected)


class _StubActor:
    def __init__(self, index_in_world, body_num, anim, world, step, angles, room, zv):
        self.index_in_world = index_in_world
        self.body_num = body_num
        self.anim = anim
        self.world_x, self.world_y, self.world_z = world
        self.step_x, self.step_y, self.step_z = step
        self.alpha, self.beta, self.gamma = angles
        self.room = room
        self.zv = zv


class _StubGame:
    def __init__(self, current_room, num_camera, actors):
        self.current_room = current_room
        self.num_camera = num_camera
        self.actors = actors


class _StubFloor:
    def __init__(self, rooms, cameras, masks_by_camera):
        self.rooms = rooms
        self.cameras = cameras
        self._masks_by_camera = masks_by_camera

    def mask_draws(self, camera_idx):
        return self._masks_by_camera[camera_idx]


class _StubResolver:
    def __init__(self, bodies_by_num, background, palette):
        self._bodies = bodies_by_num
        self._background = background
        self._palette = palette

    def body(self, num):
        return self._bodies[num]

    def background(self, floor, cam_idx):
        return self._background

    def palette(self, floor):
        return self._palette


def _legacy_stub_scene(game, floor, resolver):
    # Independent re-derivation of the pre-layer _scene_frame body, adapted
    # to a resolver instead of game.assets -- used as the ground truth for
    # draw_list, matching how the brief's own data_dir test compares against
    # _legacy_scene above.
    from PyAitD.actors import sort_actor_indices
    from PyAitD.picking import actor_bbox
    room = floor.rooms[game.current_room]
    cam_idx = room.camera_indices[game.num_camera]
    state = CameraState.from_camera(
        floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z,
    ).angles()
    out = []
    for index in sort_actor_indices(game, state.x, state.y, state.z):
        actor = game.actors[index]
        body = resolver.body(actor.body_num)
        states = [(0, (0, 0, 0))] * len(body.groups)  # every stub actor has anim == -1
        result = skin(body, states,
                      (actor.world_x + actor.step_x, actor.world_y + actor.step_y, actor.world_z + actor.step_z),
                      state, actor_angles=(actor.alpha, actor.beta, actor.gamma))
        out.append((index, actor_bbox(result), result))
    return out


def test_build_frame_assembles_frame_description_from_stubs():
    body_a = _flat_body([(0, 0, 0), (50, 0, 0), (0, 50, 0)])
    body_b = _flat_body([(0, 0, 0), (30, 10, 0), (0, 30, 20)])

    # actor A's zv/10 == (1, 2, _, _, 3, 4): inside mask 0's trigger rect.
    actor_a = _StubActor(0, 0, -1, (0, 0, 500), (0, 0, 0), (0, 0, 0), room=0, zv=(10, 20, 0, 0, 30, 40))
    # actor B's zv/10 == (100, 110, _, _, 100, 110): outside mask 0's rect.
    actor_b = _StubActor(1, 1, -1, (0, 0, 1500), (0, 0, 0), (0, 0, 0), room=0, zv=(1000, 1100, 0, 0, 1000, 1100))
    # a dead actor: excluded from sort_actor_indices (index_in_world < 0).
    actor_dead = _StubActor(-1, -1, -1, (0, 0, 0), (0, 0, 0), (0, 0, 0), room=0, zv=(0, 0, 0, 0, 0, 0))

    game = _StubGame(current_room=0, num_camera=0, actors=[actor_a, actor_b, actor_dead])
    room = Room(world_x=0, world_y=0, world_z=0, camera_indices=[0],
                hard_cols=[], sce_zones=[], offset_to_hard_col=0, offset_to_sce_zones=0)
    camera = Camera(alpha=0, beta=0, gamma=0, x=0, y=0, z=0, focal1=300, focal2=100, focal3=100)
    mask_applies = MaskDraw(0, (), (0, 0, 0, 0), viewed_room=0, test_rects=((1, 3, 2, 4),))
    mask_wrong_room = MaskDraw(1, (), (0, 0, 0, 0), viewed_room=5, test_rects=((0, 0, 999, 999),))
    floor = _StubFloor(rooms=[room], cameras=[camera], masks_by_camera={0: [mask_applies, mask_wrong_room]})
    background = object()  # identity sentinel, just needs to pass through
    palette = np.zeros((256, 3), dtype=np.uint8)
    resolver = _StubResolver({0: body_a, 1: body_b}, background, palette)

    frame, draw_list = build_frame(game, floor, resolver)

    legacy = _legacy_stub_scene(game, floor, resolver)
    assert isinstance(frame, FrameDescription)
    assert draw_list == [(i, bbox) for i, bbox, _ in legacy]
    assert [a.index for a in frame.actors] == [i for i, _, _ in legacy]
    for actor, (_, _, result) in zip(frame.actors, legacy):
        assert actor.logical.points == result.points

    # dead actor never makes it into the draw list or the frame
    assert -1 not in [i for i, _ in draw_list]
    assert len(frame.actors) == 2

    # masks: pass-through, plus the trigger-rectangle rule applied per actor
    assert frame.masks == (mask_applies, mask_wrong_room)
    for actor in frame.actors:
        expected_mask_ids = tuple(
            m.id for m in frame.masks if mask_applies_to_actor(m, actor.room, actor.zv)
        )
        assert actor.mask_ids == expected_mask_ids
    actor_a_draw = next(a for a in frame.actors if a.index == 0)
    actor_b_draw = next(a for a in frame.actors if a.index == 1)
    assert actor_a_draw.mask_ids == (0,)
    assert actor_b_draw.mask_ids == ()

    # camera, background and palette pass through unchanged
    expected_state = CameraState.from_camera(camera, 0, 0, 0).angles()
    assert (frame.camera.state.x, frame.camera.state.y, frame.camera.state.z) == (
        expected_state.x, expected_state.y, expected_state.z)
    assert frame.background is background
    assert frame.palette is palette
