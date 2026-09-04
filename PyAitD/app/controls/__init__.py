# SPDX-License-Identifier: GPL-2.0-only
"""Input: the action vocabulary, key bindings, keyboard and pointer state,
the per-tick engine snapshot, and the routing of actions into the game.
Layering: may import pygame, PyAitD.engine, app.config and app.ui; never
app.shell or PyAitD.render (tests/test_layering.py).

Only `actions` is re-exported here. app.config imports
PyAitD.app.controls.actions, and importing a submodule runs this package
__init__ first, so anything re-exported here that reaches app.config would
be a cycle. Import the other modules by name
(`from PyAitD.app.controls.keyboard import ...`)."""
from PyAitD.app.controls.actions import Action, DIRECTION_BITS, KEY_BINDABLE
