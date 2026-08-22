# SPDX-License-Identifier: GPL-2.0-only
"""Animation state machine port (FITD anim.cpp SetAnimObjet/SetInterAnimObjet)."""


def _trunc_div(v, n):
    return int(v / n)


def patch_inter_angle(value, previous, next_, bp, bx):
    diff = next_ - previous
    if diff == 0:
        return next_
    if diff <= 0x200:
        if diff >= -0x200:
            return _trunc_div(diff * bp, bx) + previous
        next_ += 0x400
        next_ -= previous
        return _trunc_div(next_ * bp, bx) + previous
    previous += 0x400
    next_ -= previous
    return _trunc_div(next_ * bp, bx) + previous


def patch_inter_step(value, previous, next_, bp, bx):
    if next_ == previous:
        return next_
    return _trunc_div((next_ - previous) * bp, bx) + previous


class AnimPlayer:
    def __init__(self, body, anim, start_tick):
        self.body = body
        self.anim = anim
        self.frame = 0
        self.start_tick = start_tick
        self.prev_frame = None  # last committed keyframe (FITD startAnim)
        self._states = [(0, (0, 0, 0))] * len(body.groups)
        self.anim_step = (0, 0, 0)  # FITD animStepX/Y/Z (interpolated per tick)
        self.wrapped = False  # anim looped on the last keyframe commit

    def set_anim(self, anim, start_tick):
        # SetAnimObjet port (AITD1: keep current frame, apply keyframe 0 states)
        self.anim = anim
        self.start_tick = start_tick
        self.prev_frame = None
        self.frame = 0
        self.anim_step = (0, 0, 0)
        self.wrapped = False
        keyframe = anim.frames[0]
        n = min(anim.num_groups, len(self.body.groups))
        self._states = list(
            zip(keyframe.group_types[:n], keyframe.group_deltas[:n])
        ) + [(0, (0, 0, 0))] * (len(self.body.groups) - n)

    def group_states(self):
        return self._states

    def advance(self, tick):
        # SetInterAnimObjet port (non-optimise branch): returns True when the
        # keyframe commits (FITD END_FRAME)
        n = min(self.anim.num_groups, len(self.body.groups))
        frame = self.frame % self.anim.num_frames
        keyframe = self.anim.frames[frame]
        keyframe_length = keyframe.timestamp
        time = (tick - self.start_tick) & 0xFFFF
        bp, bx = time, keyframe_length
        prev = self.prev_frame if self.prev_frame is not None else keyframe
        if time < keyframe_length:
            states = []
            for i in range(n):
                gtype = keyframe.group_types[i]
                pd = prev.group_deltas[i]
                nd = keyframe.group_deltas[i]
                if gtype == 0:
                    delta = (
                        patch_inter_angle(0, pd[0], nd[0], bp, bx),
                        patch_inter_angle(0, pd[1], nd[1], bp, bx),
                        patch_inter_angle(0, pd[2], nd[2], bp, bx),
                    )
                else:
                    delta = (
                        patch_inter_step(0, pd[0], nd[0], bp, bx),
                        patch_inter_step(0, pd[1], nd[1], bp, bx),
                        patch_inter_step(0, pd[2], nd[2], bp, bx),
                    )
                states.append((gtype, delta))
            self._states = states + [(0, (0, 0, 0))] * (len(self.body.groups) - n)
            self.anim_step = tuple(int(s * bp / bx) for s in keyframe.anim_step)
            self.wrapped = False
            return False
        # keyframe complete: commit and advance
        self._states = list(
            zip(keyframe.group_types[:n], keyframe.group_deltas[:n])
        ) + [(0, (0, 0, 0))] * (len(self.body.groups) - n)
        self.prev_frame = keyframe
        self.start_tick = tick
        self.frame = (self.frame + 1) % self.anim.num_frames
        self.wrapped = self.frame == 0
        self.anim_step = keyframe.anim_step
        return True
