# SPDX-License-Identifier: GPL-2.0-only
from dataclasses import dataclass
from enum import Enum, auto


class GameMode(Enum):
    PLAY = auto()
    FOUND = auto()
    INVENTORY = auto()
    READING = auto()


class AfterLife(Enum):
    NONE = auto()
    FINISH_TAKE = auto()


@dataclass(frozen=True)
class LifeFrame:
    owner_idx: int
    life_num: int
    pc: int = 0
    after: AfterLife = AfterLife.NONE
    subject_idx: int = -1
    release_actor_idx: int = -1


@dataclass(frozen=True)
class AddMessage:
    message_id: int


@dataclass(frozen=True)
class BeginTake:
    object_idx: int


@dataclass(frozen=True)
class ShowFound:
    object_idx: int
    forced_refuse: bool


@dataclass(frozen=True)
class OpenInventory:
    pass


@dataclass(frozen=True)
class ReadText:
    text_index: int
    kind: int


@dataclass(frozen=True)
class ShowPicture:
    resource_index: int
    delay_units: int
    sample_id: int


ModalEffect = ShowFound | OpenInventory | ReadText | ShowPicture
ImmediateEffect = AddMessage | BeginTake

# the one place a modal effect type is mapped to the mode it puts the loop in
MODAL_MODE = {
    ShowFound: GameMode.FOUND,
    OpenInventory: GameMode.INVENTORY,
    ReadText: GameMode.READING,
    ShowPicture: GameMode.READING,
}


@dataclass
class TimedMessage:
    message_id: int
    age: int = 0


class InputMode(Enum):
    """Mouse is the default route; the keyboard route is retained, not replaced."""
    MOUSE = auto()
    KEYBOARD = auto()


@dataclass
class NavIntent:
    """Where the player clicked, and what they meant by it."""
    dest_x: int
    dest_z: int
    room: int
    target_object_idx: int = -1
    waypoints: list = None
    path_room: int = -1


@dataclass
class NavDecision:
    """One tick of follower output: mirrored joyd plus the steering target."""
    joyd: int
    target_x: int
    target_z: int
    advance: bool
    arrived: bool
