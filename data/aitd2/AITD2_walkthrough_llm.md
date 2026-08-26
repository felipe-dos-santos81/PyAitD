# Alone in the Dark 2 — LLM-Assisted Walkthrough

> **Purpose:** A concise, state-oriented walkthrough that lets an LLM guide a player one safe action at a time while tracking character changes, inventory, combat tactics, hazards, and puzzle state.

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


## General play guidance from the source

- **DRINK** flasks when you obtain them; the source states that there is no health limit.
- **USE** cartridges for the riot gun when obtained.
- For the **THOMPSON**, wait until the magazine is low before reloading. The source says a loading clip refills it to 30 bullets rather than adding 30.
- Many fights can be avoided or made easier through positioning, ambushes, or environmental puzzles.
- Read books, parchments, photos, manuscripts, and similar items. They may contain puzzle clues.
- If double-tapping forward does not trigger running:
  1. Hold the forward key.
  2. Press **ENTER** or **ESCAPE** to open a menu.
  3. Press **ESCAPE** to close it.
  4. Press forward again.

## Quick item/weapon reference

- **Flask:** restores health.
- **Loading clip:** 30 bullets for the Thompson.
- **Cartridges:** ammunition for the riot gun.
- **Armored vest / coat of mail:** reduces damage.
- **Revolver:** starting weapon; source notes an apparent reload bug.
- **Thompson:** fast, high-capacity firearm.
- **Riot gun:** powerful, slower to reload, with limited ammunition.
- **Battledore / frying pan:** improvised melee weapons.
- **Sword-stick:** fast and strong melee weapon.
- **Derringer:** fast but weaker firearm.
- **Pirate sabre / sword:** melee weapon.
- **Pirate pistol:** one-shot capacity with limited ammunition.
- **Nichols' sword:** special late-game sword.

## Walkthrough

## [AITD2-C01] Carnby — Gardens

**Goal:** Enter the hidden maze, collect the rope and hook, solve the underground altar puzzle, and reach the basement.

1. Wait for the first guard to stand.
2. Kill him; the source recommends using your hands to conserve ammunition.
3. Take his **FLASK**, **THOMPSON**, and **LOADING CLIP**.
4. Move to the right side of the screen.
5. **RUN** along the path until you reach the anchor statue.
6. Two guards will attack.
7. If possible, quickly **PUSH** the anchor statue and enter the passage behind it.

> [!TIP]
> The source says it is possible to pass much of the garden without killing every guard, but recommends eliminating at least some because they may carry useful items.

8. In the maze, deal with the guard attacking from the right corridor.
9. Take his **PHOTO** and examine it for a puzzle clue.
10. Take the corridor leading left.
11. Deal with the guard there.
12. Take his **LOADING CLIP** and **FLASK**.
13. Continue to the end and take the **ROPE**.
14. Note the **ACE OF DIAMONDS** marker on the ground.
15. Return to the main corridor and continue downward.
16. At the crossroad, deal with the guard attacking from the left.
17. Go down.
18. Deal with the next guard and take his **BOOK**.
19. Continue down and left toward the additional card markers.
20. Take the **HOOK**.
21. Deal with or evade the approaching guards.
22. Step on the **ACE OF DIAMONDS** to enter the underground passage.
23. Deal with the short hammer-wielding enemy if necessary.
24. Identify the two underground corridors:
    - One leads to a ladder and the other ace marker, but its trapdoor is initially closed.
    - The other leads to a chest.
25. Go to the chest route.

> [!TIP]
> The source recommends saving here.

26. **PUSH** the chest toward the wall.
27. When the altar rises and the ghost appears, **keep pushing** until you obtain the **METALLIC CARD**.

> [!WARNING]
> The source says that if you stop pushing too early, you will not be able to obtain the metallic card.

28. After obtaining the card, stop pushing.
29. Use the **THOMPSON** to kill the ghost.
30. Take the **SWORD** it drops.
31. **PUT** the **METALLIC CARD** on the altar to open the other trapdoor.
32. Optionally take the **FLASK** near the ladder.
33. Return to the garden crossroad.
34. Go up, then take the difficult-to-see passage to the left.
35. At the T-junction, go down.
36. Deal with the guard and take his **FLASK**.
37. Continue until the attacking branches block the route.
38. **USE** the **SWORD** to destroy the branches.
39. Enter the next area; the sword will break.
40. Deal with **Shorty Leg**.
41. Take his **NEWSPAPER PAGE**.
42. Take the nearby **FLASK**.
43. **USE** either the **ROPE** or **HOOK** on the other item to combine them.
44. **THROW/USE** the combined rope and hook on the statue.
45. Go down the newly opened passage.

> [!WARNING]
> You will drop all weapons when entering the next area. This is expected.

**Continue to:** [AITD2-C02] Carnby — Basement.

## [AITD2-C02] Carnby — Basement

**Goal:** Open the locked door, use the barrel trap, and reach the elevator.

1. Take the **NICKEL** behind you.
2. Take the **CRANK** from the bridge.
3. Take the **PAPER BAG**.
4. Continue until you find Striker's body.
5. Take the notebook fragment and **PIPE CLEANER**.
6. At the locked door, **USE** the **NEWSPAPER PAGE**.
7. Then **USE** the **PIPE CLEANER**.
8. Take the resulting **KEY** and **MUSIC MAN'S PACT**.
9. Read the pact.
10. Unlock and enter the door.
11. Continue to the end of the room.
12. Prepare to use the lever-and-barrel trap on the guard.

> [!TIP]
> The source suggests inflating/using the paper bag to attract the guard, standing near the lever but outside the barrel's path, saving, then triggering the lever roughly 0.5–1 second after using the bag.

13. If the barrel trap misses, fight the guard or reload the save.
14. Take the guard's **FLASK**, **RIOT GUN**, and **MANUSCRIPT**.
15. Examine the clock by walking near it.
16. **USE** the **CRANK** on the right side of the clock.
17. Enter the newly opened passage.
18. Take the **BOOK**.
19. At the end, take the **CARTRIDGES**.
20. Enter the elevator.

**Continue to:** [AITD2-C03] Carnby — First Floor.

## [AITD2-C03] Carnby — First Floor

**Goal:** Defeat Music Man, solve the rotating-block puzzle, obtain the Santa suit, and reach the second floor.

1. Music Man attacks immediately.
2. Either fight him or **TEAR/USE HIS PACT**.

> [!TIP]
> The source recommends destroying the pact instead of fighting normally.

3. Take Music Man's **HOOK**.
4. Enter the door opposite the elevator.
5. Take the **BATTLEDORE**.
6. Open the other door.
7. Deal with the two guards.

> [!TIP]
> The source suggests shooting the nearest guard once with the riot gun, then ambushing the second guard from the previous room.

8. Take the additional **CARTRIDGES**.
9. Examine the four rotating blocks.
10. Hit the blocks until **all four show diamonds**.
11. When the door opens, deal with the attacking guard.
12. Take the **FLASK** and **BOTTLE OF WHISKY**.

> [!WARNING]
> Do **not** drink the whisky.

13. Take the **BOOK** from behind the large barrels.
14. **USE** the **NICKEL** in the slot machine.
15. Take the **TWO TOKENS**.
16. Deal with the nearly naked enemy outside.
17. Take his **SACK**.
18. **OPEN** the sack to obtain the **SANTA CLAUS SUIT**.
19. **WEAR** the Santa suit.
20. Go up the stairs in the previous room.

**Continue to:** [AITD2-C04] Carnby — Second Floor.

## [AITD2-C04] Carnby — Second Floor

**Goal:** Eliminate the trident hazard, clear the kitchen, poison two gangsters, and obtain protective equipment.

1. Follow the corridor to the right until you see the statue.
2. Position yourself so the statue throws its trident at you.
3. **RUN** behind the cook boy so the trident hits him instead.
4. After the boy and statue disappear, take the statue's **CROWN**.

> [!BUG/QUIRK]
> The source says the trident can sometimes appear stuck in the statue. If that happens, move around and try again; save before attempting the sequence.

5. Enter the kitchen.
6. Deal with the cook before he turns hostile.
7. Take the **FRIED EGGS** and **FRYING PAN** from the counter.
8. Take the **POISON** from the floor.
9. Take the **BOTTLE OF WINE** from the other counter.
10. Return to the hallway.
11. **USE/COMBINE** the poison with the wine.
12. Place the poisoned wine near the double doors opposite the statue.
13. Wait for the two gangsters to come out and die.
14. Enter the room.
15. Take the **DOUBLOON** from the floor.
16. **USE** both **TOKENS** in the jukebox.
17. Enter the newly opened door.
18. Take the **BULLETPROOF VEST**.
19. Take the **THOMPSON** and **LOADING CLIP** between the beds.

> [!BUG/QUIRK]
> The source warns that this Thompson may jam.

20. Go up the stairs in the hallway.

**Continue to:** [AITD2-C05] Carnby — Third Floor.

## [AITD2-C05] Carnby — Third Floor

**Goal:** Obtain the sword-stick and amulet, then reach the fourth floor.

1. Deal with the guard.
2. Open the only door.
3. Enter the door on Carnby's left.
4. Defeat **De Witt**.
5. Take his **SWORD-STICK**.
6. Take the **DERRINGER**.
7. At the far end of the room, take the **BOOK** and **PARCHMENT PIECE**.
8. Go to the end of the hallway.
9. Enter Elisabeth's bedroom.
10. Use the **SWORD-STICK** to defeat the two attacking sword-hands.
11. Take the second **PARCHMENT PIECE**.
12. **COMBINE** the two parchment pieces and read them.
13. Locate the bust/statue.
14. **PUT** the **CROWN** on the bust's head.
15. Enter the door on Carnby's right.
16. Take the **AMULET** from the center of the highlighted slab.

**Expected:** Carnby is transported to the fourth floor.

**Continue to:** [AITD2-C06] Carnby — Fourth Floor.

## [AITD2-C06] Carnby — Fourth Floor

**Goal:** Obtain the grenade and use the chimney route to attack the gangsters below.

1. Take and read the **MESSAGE**.
2. Take the **FLASK**.
3. Go through the door.
4. Deal with the gunman and fighter.
5. Take the gunman's **KEY**.
6. **OPEN** the chest.
7. Take the **THOMPSON** and **LOADING CLIP**.

> [!TIP]
> The source says this Thompson does not jam.

8. Take the **GRENADE**.
9. Go through the open door.
10. **USE** the **DOUBLOON** on the one-eyed Jack.
11. Take the **POMPON**.
12. Enter the door on the wall opposite the chest.
13. **THROW** the pompon into the snake area beyond the passage.
14. Let the clown follow it and be killed.
15. Enter the area while avoiding the snakes.
16. If not already equipped, **WEAR** the bulletproof vest.
17. **THROW** the **GRENADE** down the chimney.
18. Jump down the chimney.

**Continue to:** [AITD2-C07] Carnby — Second Floor After Chimney.

## [AITD2-C07] Carnby — Second Floor After Chimney

**Goal:** Finish the surviving gangsters and obtain the billiard ball.

1. Finish the remaining gangsters.
2. Take the **BALL** from the tree.
3. Return upstairs.

**Continue to:** [AITD2-C08] Carnby — Third Floor, Billiard Room.

## [AITD2-C08] Carnby — Third Floor, Billiard Room

**Goal:** Open the hidden door and trigger the next story sequence.

1. Return to the billiard room where De Witt was fought.
2. **PUT/DROP** the **BILLIARD BALL** into the machine to the left of the table.
3. Go to the newly revealed door.
4. **USE** the gunman's key to unlock it.
5. Enter.

**Expected:** Cutscene #1 begins.

## [AITD2-C09] Carnby — Escape After Cutscene #1

**Goal:** Escape the room and trigger the transition to Grace.

1. After Jack's story, **USE** the **HOOK** on the door to escape.
2. Return to the second floor.
3. Move toward the kitchen or another valid route described by the source.
4. Elisabeth will appear and capture/defeat Carnby.

**Expected:** Cutscene #2 and a character switch.

**Continue to:** [AITD2-G01] Grace — Flying Dutchman.

## [AITD2-G01] Grace — Flying Dutchman

**Goal:** Evade the guards, reach the captain's cabin, and obtain a key through the elevator puzzle.

> [!WARNING]
> Grace cannot fight the guards normally in this sequence. Prioritize hiding and movement.

1. Move the board.
2. Enter the passage behind it.
3. Take the **BAG OF SEEDS**, **SANDWICH**, and **PEPPER POT**.
4. **GIVE** the seeds to the parrot.
5. Listen to the information it gives you.
6. Leave.
7. Evade the patrol by moving in its direction, hiding behind the wall, waiting for it to pass, then running the opposite way.
8. Reach the deck by going up twice.
9. Hide behind the large man drinking beer.
10. **RUN** behind the boxes and barrels to the final barrel.
11. Take the **TINDERBOX**.
12. Go down the rope to the left of the last barrel.
13. Enter the captain's cabin.
14. **OPEN** the chest and take the **SMALL CANNON**.
15. Take the **CRYSTAL VASE** from the cabinet.
16. Take the **CAPTAIN'S STAFF** from the dresser near the bed.
17. Face the door to the right of the bed.
18. **PUT** the small cannon down.
19. **PUT** pepper in the cannon.
20. **THROW** the vase.
21. When the guard opens the door, **USE** the **TINDERBOX** to fire the cannon.
22. Leave and take the **BELL**.
23. Enter the now-open door.
24. Take the **CHICKEN'S FOOT** from the table.
25. Stand near the elevator.
26. **USE/RING** the bell.
27. Enter the elevator.

**Expected:** Grace obtains a key.

**Continue to:** [AITD2-G02] Grace — Second Floor.

## [AITD2-G02] Grace — Second Floor

**Goal:** Use environmental traps to bypass a guard.

1. **USE** the new key on the cupboard.
2. Take the **ICEBOX** and **POT OF MOLASSES**.
3. Go to the main hallway.
4. When the guard sees you, **USE** the ice on the floor.
5. Make the guard walk over the ice.
6. Go upstairs.

**Expected:** The guard is eliminated by the ice trap.

**Continue to:** [AITD2-G03] Grace — Third Floor.

## [AITD2-G03] Grace — Third Floor

**Goal:** Immobilize the guard, obtain the Loa staff, and return to the second floor.

1. **USE** the **POT OF MOLASSES** to trap the guard.

> [!TIP]
> The source says the molasses works like the ice, except the guard is immobilized rather than killed.

2. Go to the billiard room.
3. Take the **TOKEN** from the billiard table.

> [!OPTIONAL]
> The source says it found no use for this token.

4. Enter Jack's bedroom, where Carnby was captured.
5. Move behind the chair.
6. **USE** the **CAPTAIN'S STAFF** on the grid.
7. Take the resulting **KEY** and **BOOK**.
8. Return to the location where Carnby previously took the amulet.
9. **USE** the captain's staff on the slab.
10. Take the **LOA STAFF**.

**Expected:** Grace is transported to the second floor.

**Continue to:** [AITD2-G04] Grace — Second Floor Return.

## [AITD2-G04] Grace — Second Floor Return

**Goal:** Remove another guard and trigger Grace's capture.

1. Go to the kitchen.
2. Lure the guard onto the still-active ice trap.
3. Go to the elevator.
4. **RING** the bell.
5. Enter the elevator.

**Expected:** Grace is captured and control returns to Carnby.

**Continue to:** [AITD2-C10] Carnby — Flying Dutchman Finale.

## [AITD2-C10] Carnby — Flying Dutchman Finale

**Goal:** Escape captivity, use the cannon to breach the quarters, free Grace, and defeat Jack.

1. Hold the **right arrow key** until Carnby obtains the key.
2. **USE** the key to free yourself.
3. Kill the guard.
4. Take his **SWORD**.
5. Leave the room.
6. Deal with the next guard.
7. Take his **THOMPSON** and **FLASK**.
8. Enter the corridor.
9. Deal with the guard there.
10. Take his **PIRATE PISTOL** and **SHORT FUSE**.
11. Enter the door near the left ladder.
12. Deal with the guards.
13. Take the **POKER**, **PLIERS**, and **KEY** in the corner.
14. Check the two additional doors on the left:
    - First door: defeat the guard and take the **COAT OF MAIL**, **AMMUNITION**, **PISTOL**, and **FLASK**.
    - Second door: contains another guard.
15. **USE** the new key on the rightmost door.
16. Fight the pirate with the **SWORD**.

> [!WARNING]
> Do **not** shoot this pirate. The source explicitly says to use the sword.

17. Take the **BARREL OF GUNPOWDER** and **BOOK**.
18. Climb the ladder.
19. Find the room with the cannon.
20. Deal with the sleeping guard.
21. **USE** the **PLIERS** to cut the cords holding the cannon.
22. Back away from the cannon.
23. Run into it and **PUSH** it until it faces the door.
24. Go through the opposite door — the one the cannon now points toward.
25. **PUT** the **BARREL OF GUNPOWDER** down.
26. Return to the cannon.
27. **PUT** the **SHORT FUSE** on the cannon.
28. **USE** the **POKER** to fire it.
29. Enter the breached quarters.
30. Take the **POUCH OF GOLD COINS**.
31. Return to the hallway and go to the opposite end.
32. **USE** the pouch.
33. Deal with the two cooks.
34. Enter the newly opened room.
35. Take the **FLASK**.
36. Enter the door near the sink.
37. Deal with the cook.
38. Take the **JACK OF DIAMONDS**.
39. Return to the locked door opposite the previous kitchen.
40. **USE** the **JACK OF DIAMONDS** to unlock it.

**Expected:** Carnby falls under Elisabeth's control again and the perspective briefly returns to Grace.

41. As Grace, **USE** the **LOA STAFF** on the statue.
42. Enter the passage.
43. Approach Elisabeth.
44. **USE** the **CHICKEN'S FOOT**.
45. As Carnby, do **not** fight the creature that attacks.
46. **RUN** to the deck.
47. Defeat Music Man.
48. Take his **HOOK**.
49. Climb the mast.
50. Defeat the enemy there.
51. **USE** the hook on the straight-running rope to reach the next mast.
52. Defeat the fighter.
53. Jump down to the deck.
54. Take **NICHOLS' SWORD**.
55. **USE** the **PLIERS** to free Grace.
56. Take the **FUSE** from the cannon.
57. **USE** Nichols' sword to defeat Jack.

> [!WARNING]
> The source says Jack may need to be killed twice.

**Expected:** End of game.

## Source

Reformatted from the user-provided walkthrough by Nikolay Kaleyski for personal, LLM-assisted play.

Reference: https://gamefaqs.gamespot.com/pc/564568-alone-in-the-dark-2/faqs
