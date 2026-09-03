# SPDX-License-Identifier: GPL-2.0-only
from dataclasses import dataclass
from enum import Enum, auto


class GameMode(Enum):
    PLAY = auto()
    FOUND = auto()
    INVENTORY = auto()
    READING = auto()
    GAME_OVER = auto()
    CHARACTER_SELECT = auto()
    SYSTEM_MENU = auto()
    TITLE = auto()
    STARTUP_MENU = auto()
    CUTSCENE_END = auto()


class FoundResult(Enum):
    # the Take/Leave prompt's answer; consumed by interaction.apply_found_result
    TAKE = auto()
    LEAVE = auto()


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
class ChooseCharacter:
    pass


@dataclass(frozen=True)
class OpenSystemMenu:
    pass


@dataclass(frozen=True)
class ShowTitle:
    # startup only: AITD1.cpp:121 makeIntroScreens (title, then credits page)
    pass


@dataclass(frozen=True)
class OpenStartupMenu:
    # startup only: startupMenu.cpp:35 MainMenu
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


@dataclass(frozen=True)
class GameOver:
    # LM_GAME_OVER (life.cpp:2438-2450) fades music and spins 120 chrono units
    # inside the opcode; the wall-clock wait moves here so the tick that sets
    # flag_game_over does not block the event pump (see task-9 brief).
    delay_units: int = 120


@dataclass(frozen=True)
class CutsceneFinished:
    # PlayWorld(allowSystemMenu=0) breaks on FlagGameOver (mainLoop.cpp:185):
    # the scripted opening's terminal, not a death. The app replaces the game.
    pass


ModalEffect = (
    ShowFound | OpenInventory | ReadText | ShowPicture | GameOver
    | ChooseCharacter | OpenSystemMenu | ShowTitle | OpenStartupMenu
    | CutsceneFinished
)
ImmediateEffect = AddMessage | BeginTake

# the one place a modal effect type is mapped to the mode it puts the loop in
MODAL_MODE = {
    ShowFound: GameMode.FOUND,
    OpenInventory: GameMode.INVENTORY,
    ReadText: GameMode.READING,
    ShowPicture: GameMode.READING,
    ChooseCharacter: GameMode.CHARACTER_SELECT,
    OpenSystemMenu: GameMode.SYSTEM_MENU,
    ShowTitle: GameMode.TITLE,
    OpenStartupMenu: GameMode.STARTUP_MENU,
}
MODAL_MODE[GameOver] = GameMode.GAME_OVER
MODAL_MODE[CutsceneFinished] = GameMode.CUTSCENE_END


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
    requires_hold: bool = False
    # Run instead of walk: FITD's speed 5, the same one _process_track_manual
    # gives a double-tap forward (tracks.py). A property of the click, not of
    # the device that made it -- no engine module learns a mouse exists.
    run: bool = False
    engaged: bool = False
    waypoints: list = None
    path_room: int = -1
    # give-up bookkeeping (navigate._stalled): the steering target we are
    # closing on, the best distance seen to it, and how long since it improved
    stall_target: tuple = None
    stall_best: int = 0
    stall_ticks: int = 0
    approach_target_pose: tuple = None
    origin_floor: int | None = None
    origin_room: int | None = None
    # engaged held push: the world axis ("x" or "z") the hero pushes along,
    # and the lateral coordinate frozen when the push engaged
    push_axis: str | None = None
    push_lateral: int | None = None


@dataclass
class NavDecision:
    """One tick of follower output: mirrored joyd plus the steering target."""
    joyd: int
    target_x: int
    target_z: int
    advance: bool
    arrived: bool
    # gave up too far from the destination to call it an arrival: the intent is
    # dropped without dispatching, so a wedged hero cannot act through a wall
    abandoned: bool = False
    # carry the intent's run onto the advancing tick, so the track that steers
    # the hero reads one object -- the decision -- and never the intent
    run: bool = False
