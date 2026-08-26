# Alone in the Dark (1992) — LLM-Assisted Walkthrough

> **Purpose:** A concise, state-oriented walkthrough that lets an LLM guide a player one safe action at a time while tracking rooms, hazards, and important inventory.

## How an LLM should use this walkthrough

This file is optimized for **state-aware play assistance**, not for reading as a long narrative.

When helping a player:

1. Identify the player's **current section**, **last completed step**, **character**, and relevant **inventory**.
2. Give only the **next 1–3 actions** unless the player explicitly asks for a larger sequence.
3. Prefer the game's exact action language when it matters: **TAKE**, **USE**, **OPEN**, **SEARCH**, **PUSH**, **PUT**, **THROW**, **DROP**, **FIGHT**, **SHOOT**, **RUN**, **JUMP**, **DRINK**, and **EAT**.
4. Always mention a nearby **WARNING** before giving an action that could trigger it.
5. Track important item state: **acquired**, **used**, **consumed**, **dropped**, **broken**, or **still required**.
6. If the player's state does not match the walkthrough, work backward to the nearest supported step and provide a recovery path. **Do not invent undocumented mechanics or item locations.**
7. If the source itself describes a bug, uncertainty, optional tactic, or timing-sensitive action, preserve that uncertainty.
8. Avoid unnecessary spoilers. Explain the purpose of an action only when it helps the player avoid a mistake or recover from one.

### Recommended response format

When the player asks “What do I do next?”, respond in this shape:

- **Current:** section + step
- **Next:** the immediate action
- **Use/Equip:** only if an item or weapon matters
- **Watch for:** hazard, timing constraint, or enemy behavior
- **Expected:** the state change that confirms the step worked

The player does **not** need to provide every state field every time. Ask only for information required to disambiguate the next action.

### Callouts

- **WARNING** — can cause death, damage, item loss, or a blocked route.
- **TIP** — safer or easier tactic from the source.
- **OPTIONAL** — useful but not required for progression.
- **BUG/QUIRK** — source-described behavior that may be inconsistent.


## Walkthrough

## [AITD1-R01] Attic

**Goal:** Secure the attic and collect the starting equipment.

1. **PUSH** the wardrobe in front of the window.
2. **PUSH** the chest onto the trapdoor in the floor near the piano.
3. **OPEN** the chest and take the **RIFLE**.
4. **OPEN** the wardrobe and take the **OLD INDIAN COVER**.
5. Go to the table and take the **OIL LAMP**.

**Continue to:** [AITD1-R02] Storeroom.

## [AITD1-R02] Storeroom

**Goal:** Collect the bow and prepare the lamp.

1. Take the **BOW** from the corner near the door.
2. **SEARCH** the shelves on the right and take the **OIL CAN**.
3. **USE** the **OIL CAN** to refill the **OIL LAMP**.
4. Leave the room.

**Continue to:** [AITD1-R03] Upstairs Hallway.

## [AITD1-R03] Upstairs Hallway

**Goal:** Reach the next room without triggering the collapsing floor.

1. Enter the first door on the right.

> [!WARNING]
> Do **not** continue down the hallway. The floor will collapse and cause death.

**Continue to:** [AITD1-R04] Bedroom/Study Room.

## [AITD1-R04] Bedroom/Study Room

**Goal:** Obtain the saber and survive the incoming zombie.

1. **SEARCH** the rolltop desk in the corner and take the **KEY TO THE CHEST**.
2. **USE** the key on the chest beside the door and take the **OLD CAVALRY SABER**.
3. Open the door.
4. **FIGHT** the zombie that enters.

> [!WARNING]
> The **OLD CAVALRY SABER** breaks after limited use. Keep both pieces if it breaks; they are needed later.

5. Leave the room.
6. Enter the door directly across the hall.

**Continue to:** [AITD1-R05] Dressing Room.

## [AITD1-R05] Dressing Room

**Goal:** Survive the pursuing zombie and reach the bedroom.

1. Enter the room, then turn around.
2. **FIGHT** or **SHOOT** the zombie that follows from the hallway.
3. Leave through the door near the window.

**Continue to:** [AITD1-R06] Bedroom.

## [AITD1-R06] Bedroom

**Goal:** Obtain the two small mirrors.

1. Go to the nightstand on the left side of the bed, opposite the window, and take the **VASE**.
2. **FIGHT** or **SHOOT** the monster that jumps through the window.
3. **THROW** the **VASE**.
4. Take the **KEY TO THE DRESSER** revealed inside the vase.
5. **USE** the key on the dresser with the teddy bear on top.
6. Take the **TWO SMALL MIRRORS**.
7. Leave through the door near the bed.
8. Enter the door directly across the hall.

**Continue to:** [AITD1-R07] Bathroom.

## [AITD1-R07] Bathroom

**Goal:** Heal and clear unnecessary inventory.

1. **OPEN** the cabinet and take the **FIRST AID KIT**.
2. **OPEN** the first aid kit and take the **FLASK**.
3. **DRINK** the flask to restore health.
4. **DROP** or **THROW** items that are no longer needed:
   - First aid kit
   - Empty flask
   - Chest key
   - Dresser key
   - Empty oil can
5. Leave the room.
6. Open the door at the end of the hall.

**Continue to:** [AITD1-R08] Upper Lobby.

## [AITD1-R08] Upper Lobby

**Goal:** Neutralize the winged-monster hazard and reach the lower floor.

1. **PUT** one **SMALL MIRROR** on each small statue at the two ends of the room.

> [!WARNING]
> Avoid contact with the winged monsters. Stay close to the wall.

2. Go downstairs.

**Continue to:** [AITD1-R09] Lower Lobby.

## [AITD1-R09] Lower Lobby

**Goal:** Avoid the armor for now and continue exploring.

> [!WARNING]
> Do **not** touch the suit of armor yet.

1. Enter the door on the right side of the stairs.

> [!TIP]
> **Deferred action:** after obtaining the **VERY HEAVY STATUETTE** in [AITD1-R13], return here, stand directly in front of the armor, **THROW** the statuette at it, and take the **SWORD** from the destroyed armor.

**Continue to:** [AITD1-R10] Sitting Room.

## [AITD1-R10] Sitting Room

**Goal:** Collect the gramophone, ammunition, and matches.

> [!WARNING]
> Do **not** touch the ghost sitting in the chair.

1. Take the **GRAMOPHONE** from the table.
2. **SEARCH** the cabinet and take the **CARTRIDGES**.
3. **USE** the cartridges to reload the **RIFLE**.
4. Take the **MATCHBOX** from the fireplace mantle.
5. Leave the room.
6. Go to the door straight ahead on the opposite side of the stairs.

**Continue to:** [AITD1-R11] Hallway.

## [AITD1-R11] Hallway

**Goal:** Reach the bathroom.

1. Follow the hallway around.
2. Enter the **second** door you encounter.

> [!TIP]
> The first door is directly across from the door through which you entered this hallway.

**Continue to:** [AITD1-R12] Bathroom.

## [AITD1-R12] Bathroom

**Goal:** Obtain the jug and another health flask.

1. **RUN** into the room.
2. Take the **JUG** next to the cabinet.

> [!WARNING]
> Ignore the monster in the bathtub. It cannot be killed and will damage you.

3. **OPEN** the cabinet and take the **FIRST AID KIT**.
4. **OPEN** the kit and take the **FLASK**.
5. **DRINK** the flask to restore health.
6. Leave the room.
7. Continue down the hall to the next door.

**Continue to:** [AITD1-R13] Dark Bedroom.

## [AITD1-R13] Dark Bedroom

**Goal:** Obtain the statuette needed to destroy the armor.

1. **USE** the **MATCHBOX** to light the **OIL LAMP**.
2. Take the **VERY HEAVY STATUETTE** from the table.
3. Leave the room.
4. Use **OPEN/SEARCH** to put the lamp away.
5. Return to [AITD1-R09] Lower Lobby.
6. **THROW** the statuette at the suit of armor as described there.
7. Take the **SWORD**.
8. Leave the **VERY HEAVY STATUETTE** behind.
9. Walk to either side of the stairs and enter the dark opening.

**Continue to:** [AITD1-R14] Front Lobby.

## [AITD1-R14] Front Lobby

**Goal:** Stage the gramophone for later and enter the enclosed porch.

1. **DROP** the **GRAMOPHONE** here. You will need it later.
2. Turn left.
3. In the corner beside the stairs, enter the **right-hand** door of the two doors.

> [!TIP]
> The left-hand door is locked at this point.

**Continue to:** [AITD1-R15] Enclosed Porch.

## [AITD1-R15] Enclosed Porch

**Goal:** Obtain arrows and leave before the spiders become a problem.

1. **SEARCH** the back of the statue and take **THREE ARROWS**.
2. Leave the room quickly.

> [!WARNING]
> Spiders fall into this room. They will not follow you outside.

3. Cross to the other side of the stairs.
4. Enter the door beside the narrow hallway.

**Continue to:** [AITD1-R16] Kitchen.

## [AITD1-R16] Kitchen

**Goal:** Collect the cellar key, healing food, revolver, lamp oil, water, and soup.

1. Enter the smaller dark-brown door nearest the entrance.
2. Take the **KEY TO THE CELLAR** from the wall.
3. **SEARCH** the shelf and take the **BOX OF BISCUITS**.
4. **EAT** the biscuits to restore health.
5. **DROP** or **THROW** the empty box, first aid kit, and empty flask.
6. **SEARCH** the large cabinet near the table and take the **KNIFE**.
7. Enter the second small dark-brown door beside the normal-sized door.
8. Immediately back out of the small closet.
9. **USE** the **KNIFE** to kill the zombie that enters when the closet is opened.
10. Re-enter the closet.
11. **SEARCH** the coal pile in the corner and take the **BOX OF SHOES**.
12. **OPEN** the box and take the **REVOLVER**.
13. Take the **OIL CAN** from the other corner.
14. **USE** the oil can to refill the **OIL LAMP**.
15. **USE** the **JUG** beside the water barrel to fill it with water.
16. **DROP** or **THROW** the empty oil can, empty box, and knife.
17. Return to the kitchen.
18. Take the **POT OF SOUP** from the fireplace.
19. Leave through the normal-sized door beside the closet.
20. Open the door across the small hall.

**Continue to:** [AITD1-R17] Dining Room.

## [AITD1-R17] Dining Room

**Goal:** Distract the zombie with the soup.

1. Walk to the right side of the table.
2. **PUT** the **POT OF SOUP** on the table.
3. Avoid the walking zombie.
4. Wait until the zombie sits down.
5. Leave through the door beside the large cabinet.

**Continue to:** [AITD1-R18] Smoking Room.

## [AITD1-R18] Smoking Room

**Goal:** Get the lighter and neutralize the smoking ashtray.

1. **RUN** to the opposite side of the table and stand beside the chair.
2. Take the **LIGHTER** from the table.
3. **USE** the **WATER JUG** on the smoking ashtray.

> [!WARNING]
> You will take some smoke damage.

4. Open the unlocked double doors and enter the hall.
5. Return to the white stairs in the front lobby and climb them.
6. Return to the hallway leading toward the dark room where the statuette was found.
7. Continue to the end of the hall.
8. Open the door.

**Continue to:** [AITD1-R19] Hallway with Paintings.

## [AITD1-R19] Hallway with Paintings

**Goal:** Neutralize both dangerous paintings.

1. Go to the first painting, showing a man with an axe.
2. **PUT** the **OLD INDIAN COVER** on it.
3. Move to roughly the middle of the hallway.
4. **USE** the **BOW** to shoot an arrow at the painting at the far end.
5. Confirm that purple smoke appears after the arrow hits.
6. Enter the door at the far end.

**Continue to:** [AITD1-R20] Jeremy's Bedroom.

## [AITD1-R20] Jeremy's Bedroom

**Goal:** Obtain the false book and the study key.

1. Take the **FALSE BOOK** from the table.
2. **PUSH** the grandfather clock aside.
3. **SEARCH** the hole behind it and take the **KEY TO JEREMY'S STUDY**.
4. Leave the room.
5. Enter the double doors halfway down the hall.

**Continue to:** [AITD1-R21] Library.

## [AITD1-R21] Library

**Goal:** Open the secret room before the pursuing monster reaches you.

1. **USE** the **OIL LAMP**.
2. **PUT** the lamp on the floor in the middle of the room.
3. Quickly **RUN** into the corridor at the upper-left of the screen.
4. Follow it around to the right.
5. Locate the indentation in the wall of books.
6. Continue slightly past the indentation.
7. **SEARCH** the books beside it to find the mechanism.
8. **USE** the **FALSE BOOK** to open the secret room.
9. Enter immediately.

> [!WARNING]
> A monster chases you in the library. According to the source, it can only be killed with a specific dagger found inside the secret room.

**Continue to:** [AITD1-R22] Secret Room.

## [AITD1-R22] Secret Room

**Goal:** Obtain the talisman and dagger, kill the library monster, and unlock the route to Jeremy's Study.

1. Take the **TALISMAN** from the shelf.
2. **SEARCH** the bookshelves and take the **CURVED-BLADE DAGGER**.
3. Return to the library.
4. **USE** the dagger to kill the pursuing monster.
5. Take the **OIL LAMP** from the floor.
6. Open the closed double doors to return to the lower lobby.
7. Go through the dark opening and down the stairs.
8. Retrieve the **GRAMOPHONE** from the front lobby.
9. **USE** the silver key to open the locked door beside the enclosed porch.

> [!BUG/QUIRK]
> The provided source refers to a **silver key** here but does not state where it was acquired. If the player does not have it, report this as a source gap rather than inventing a location.

10. Continue down the large hall.
11. Re-enter [AITD1-R18] Smoking Room.
12. **USE** the key to open the locked double doors.

**Continue to:** [AITD1-R23] Jeremy's Study.

## [AITD1-R23] Jeremy's Study

**Goal:** Restore the coat of arms and obtain the record.

1. **PUT** the **OLD CAVALRY SABER** in the coat of arms on the wall.
2. If the saber broke earlier, **PUT both broken halves** into the coat of arms.
3. **SEARCH** the bookcase in the corner and take the **RECORD**.
4. Leave through the smoking room and return to the hall.
5. Do **not** take the doors at the end of the hall.

**Continue to:** [AITD1-R24] Pirates Room.

## [AITD1-R24] Pirates Room

**Goal:** Defeat the pirate and unlock the dance hall.

1. **USE** the **SWORD** to kill the pirate.

> [!WARNING]
> The pirate cannot be defeated by shooting according to the source.

2. Take the **KEY TO THE DANCEHALL** from the pirate.
3. **USE** the key on the double doors.

**Continue to:** [AITD1-R25] Dance Hall.

## [AITD1-R25] Dance Hall

**Goal:** Make the ghosts dance and obtain the pirate-chest key.

1. Move to a corner.
2. Confirm that you have the **GRAMOPHONE**.
3. **USE** the **RECORD** ("Dance of Death").
4. Wait for the ghosts to begin dancing.

> [!WARNING]
> Do not let the ghosts touch you.

5. Take the **KEY TO THE PIRATE'S CHEST** from the fireplace mantle.
6. Leave the room.
7. Return to Jeremy's Study.
8. Go down the stairs in the floor.

**Continue to:** [AITD1-R26] Bottomless Chasm.

## [AITD1-R26] Bottomless Chasm

**Goal:** Escape the collapsing bridge and manipulate the worm's route.

1. **RUN** across the collapsing bridge.
2. Follow the tunnels until the giant worm appears behind you.
3. **RUN** away from the worm.
4. Turn right into another tunnel as soon as possible.

**Continue to:** [AITD1-R27] Cave.

## [AITD1-R27] Cave

**Goal:** Make the worm open the required tunnel.

1. **FIGHT** or **SHOOT** the monster waiting in the cave.
2. Continue down the tunnel until the worm appears again.
3. **RUN** back to the junction where you turned right and fought the monster.
4. Turn right into the tunnel opened by the worm.
5. If the worm still blocks that tunnel, repeat steps 2–4 until it moves away.

**Continue to:** [AITD1-R28] Underground.

## [AITD1-R28] Underground

**Goal:** Cross the dock safely and reach the upper opening.

1. Step onto the wooden dock.
2. Walk around to the right.
3. Stop when you reach the lighter-brown section of wood.
4. **JUMP** over that section.

> [!WARNING]
> The lighter section collapses if stepped on.

5. Avoid or kill the monster in the water.

> [!TIP]
> Killing it causes more monsters to appear, so avoidance may be preferable.

6. Climb the ledge to the opening.

**Continue to:** [AITD1-R29] Tunnel.

## [AITD1-R29] Tunnel

**Goal:** Clear the tunnel.

1. **FIGHT** or **SHOOT** the spider monster.
2. Continue down the tunnel.

**Continue to:** [AITD1-R30] Rock Pillar Cavern.

## [AITD1-R30] Rock Pillar Cavern

**Goal:** Cross the pillars and take the right fork.

1. From the opening, **SHOOT** the flying monster.
2. **JUMP** from rock pillar to rock pillar, using the pillars on the left.
3. When the camera/view changes, go to the opening on the right.
4. Follow the tunnel to the fork.
5. Take the **right** fork.

**Continue to:** [AITD1-R31] Large Cavern with Planks.

## [AITD1-R31] Large Cavern with Planks

**Goal:** Reach the pirate's chest.

1. Walk to the right side of the rock plateau.
2. **JUMP** over the light-colored wooden planks and land on the darker planks.
3. Continue **JUMPING** and climbing the rock pillars until you reach the far side.
4. Shoot or avoid the flying creature in the middle of the cavern.
5. Go to the chest.

**Continue to:** [AITD1-R32] Pirate's Chest.

## [AITD1-R32] Pirate's Chest

**Goal:** Obtain the gem and enter the hidden passage.

1. **USE** the **KEY TO THE PIRATE'S CHEST**.
2. Take the **GEM**.
3. **PUSH** the rock behind the chest to one side.
4. Enter the dark opening.
5. Follow the rock corridor.
6. Step down the ledge.
7. Continue forward until the screen goes black.

**Continue to:** [AITD1-R33] Dark Maze.

## [AITD1-R33] Dark Maze

**Goal:** Navigate the maze and open the stone door.

1. **USE** the **OIL LAMP**.
2. Move left, winding left as far as possible.
3. Turn downward and continue until you cannot go farther.
4. Turn to the right side of the screen.
5. Continue until you reach a stone door with a hole.
6. **USE** the **GEM** on the door.
7. Enter.
8. Use **OPEN/SEARCH** to put the lamp away.

**Continue to:** [AITD1-R34] End Cavern.

## [AITD1-R34] End Cavern

**Goal:** Stop the fireballs, destroy the tree, and escape back toward the mansion.

1. **RUN** and jump off the rock steps.
2. **RUN** to the stone altar in front of the tree while dodging fireballs and the monster in the water.
3. Take the **HOOK**.
4. While standing in front of the altar, **PUT** the **TALISMAN** on it.
5. Confirm that the fireballs stop.
6. **USE** the **LIGHTER** to relight the **OIL LAMP**.
7. **THROW** the lit **OIL LAMP** at the tree.
8. **RUN** to the right side of the cavern.
9. Climb onto another rock plateau.
10. Climb to the rock door.
11. **USE** the **HOOK** to open it.
12. Turn left and return to the maze, which should now be lit.
13. Turn right.
14. **USE** the **HOOK** to open the next door.
15. Turn left to return to [AITD1-R28] Underground.
16. Follow the wooden docks and climb to the opening on the opposite side.
17. Turn right.
18. Follow the tunnel straight ahead until you reach a small black opening.
19. Enter it.

**Continue to:** [AITD1-R35] Basement.

## [AITD1-R35] Basement

**Goal:** Return to the mansion and finish the game.

1. Walk around the wine racks to the far side of the room.
2. Climb the stairs.
3. You should return to the front lobby.
4. Walk down the large hall.
5. Open the double doors at the end.

**Expected:** End of game.

## Source

Reformatted from the user-provided walkthrough for personal, LLM-assisted play.

Reference: https://gamefaqs.gamespot.com/pc/564567-alone-in-the-dark-1992/faqs
