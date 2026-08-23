# M3b interaction proof

## Keyboard-only

1. Start with `make run` and walk to the oil lamp with arrows or WASD.
2. In FOUND, use Left/Right and Enter; repeat once with Escape to leave it.
3. Open inventory with Enter or I, choose the lamp and Use with arrows and Enter.
4. Open inventory again, choose Drop/Put, then resume movement immediately.
5. Open and close a readable object; verify the page does not reopen and movement resumes.

## On-screen keyboard

Repeat the journey using only the macOS Accessibility Keyboard: arrows, Enter,
Space, I, and Escape. Record whether every press produces exactly one menu edge.

## Single-button mouse

Repeat FOUND, inventory object/action selection, reading navigation, and close
using only left click. Verify every target accepts a click near each corner and
letterbox clicks do nothing.

## Focus and freeze regression

Hold Up, move focus away from the window, return, release Up, and press Up again.
The actor must stop on focus loss, no modal may dismiss on focus return, and the
new Up press must move without a stall. Leave each modal open for ten seconds;
the window must continue repainting and closing normally.
