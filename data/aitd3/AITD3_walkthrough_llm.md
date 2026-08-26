# Alone in the Dark 3 — LLM-Assisted Walkthrough

> **Purpose:** A concise, state-oriented walkthrough that lets an LLM guide a player one safe action at a time while tracking chapters, transformations, hazards, puzzle items, and progression-critical inventory.

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

## [AITD3-P00] The Beginning — Saloon and Wine Cellar

**Goal:** Collect the opening puzzle items, discover the trapdoor, and escape the wine cellar.

1. After recovering from the explosion, head toward the saloon.
2. Before entering, take the **GAS CAN** from the right side of the porch.
3. Enter the saloon.
4. Take the **OIL CAN**.
5. Take the **KEY** from the table.
6. Take the **MARACA** from the theatre area.
7. **USE** the **GAS CAN** on the cinematograph to watch the film.
8. Find the small room immediately left of the bar.
9. Take the **MATCHBOX** hidden there.
10. Go behind the bar counter.
11. A gunman above you will begin shooting.

> [!TIP]
> Stay directly underneath him to avoid his shots until he leaves.

12. **SEARCH** the shelves.
13. Take the **FLASK**, **BOTTLE**, and **WOOD ALCOHOL**.
14. **THROW** the bottle to break it.
15. Take the **TOKEN** revealed inside.
16. **USE** the token in the side of the harpsichord facing the bar.
17. Take the **LAMP**.
18. **PUSH** the right horn of the bull skull — the horn pointing left.
19. When the trapdoor opens and an enemy comes up, kill him.
20. Take the **GOLD BULLET** and **ACE OF DIAMONDS**.
21. Drop through the trapdoor into the wine cellar.
22. **USE** the oil to fill the lamp.
23. **USE** a match to light the lamp.
24. Take the **CANE** at the far end of the room.
25. Read the poster on the wall and note the clue **"Lefty."**
26. **OPEN** the left barrel.
27. Use the **MARACA** to lure the rattlesnakes away.
28. Climb the ladder.

**Continue to:** [AITD3-C01] Chapter 1.

## [AITD3-C01] Chapter 1 — Cells and Sheriff's Office

**Goal:** Escape the cell area, obtain the Winchester and badge, and leave by the rope ladder.

1. Take the **STONE** from the bed.
2. **THROW** the stone to break it.
3. Take the **INDIAN AMULET** hidden inside.
4. Deal with any skeleton enemies that appear.
5. Go to the cell door.
6. **USE** the **CANE** to retrieve the cell-door key.
7. Unlock the door and leave.
8. **RUN** to the far end of the corridor.
9. Enter the room there.
10. **PUT/USE** the **WOOD ALCOHOL** on the ground in front of the drunkard.
11. Wait for him to drink it and die.
12. Take the **FLASK** he leaves.
13. Return to the corridor.
14. Pass through the small entryway marked with a pentacle.

> [!WARNING]
> The source indicates that the **INDIAN AMULET** is required to cross the pentacle.

15. Enter the sheriff's room.
16. **SEARCH** the desk.
17. Take the **SHERIFF'S BADGE** and **WINCHESTER BULLETS**.
18. **USE** the key on the gun-case lock.
19. Take the **WINCHESTER**.
20. Read the posters for hints.

> [!OPTIONAL]
> The room opposite has no required item. Opening its fireplace causes a large enemy to drop down and attack.

21. Go to the main hall containing the wardrobe.
22. **PUSH** the wardrobe into the door to block the Elwood Brother trying to enter.
23. **OPEN** the wardrobe.
24. Take the **SHOTGUN**.
25. Climb the rope ladder.

**Continue to:** [AITD3-C02] Chapter 2.

## [AITD3-C02] Chapter 2 — Rooftops, Lone Miner, and Dynamite Passage

**Goal:** Defeat the Lone Miner, solve the voodoo-room trap, and blast open the route to the machine.

1. Take the **WHIP**.
2. Continue until you reach the small area with the floating block firing beams.
3. Time your movement and take the **VOODOO HANGMAN'S ROPE** from beneath it.

> [!WARNING]
> The beams are lethal according to the source. Time the run carefully.

4. Continue to the door with the cast-iron plate in front of it.
5. Take the **CAST-IRON PLATE**.
6. **WEAR** it.
7. Leave this door for later.
8. Continue past the chimney.

> [!WARNING]
> Going down the chimney can be fatal if the fireplace below was not opened earlier; if it was opened, the source says three skeleton enemies are waiting there.

9. Take the **CARTRIDGE BELT**.
10. Continue to the **LONE MINER**.
11. Equip the **WHIP** and strike him once.
12. Take the **BAG OF GOLD COINS**, which the source identifies as shotgun ammunition.
13. **LOAD** the **WINCHESTER** with the **GOLD BULLET**.
14. Use it to kill the Lone Miner.
15. Take the **BAG OF SCORPIONS** he drops.
16. Enter the room.
17. Take the **GATLING GUN** and **FLASK**.
18. Return to the previously skipped door.
19. Stand back and **SHOOT** the door to open it.
20. Enter.
21. Light the lamp.
22. When the hangman begins using voodoo to suffocate you, **USE** the **VOODOO HANGMAN'S ROPE**.
23. Walk to the trapdoor.
24. **DROP/USE** the **SCORPIONS** on the hangman below.
25. **PUSH** the lever to close the trapdoor.
26. Take the **DYNAMITE STICK** and **DRIED MEAT** from the other side.
27. Leave the room.
28. Deal with the two skeleton enemies.
29. Return to the room with the barrel.
30. When the door closes and someone fires at you, hide in the corner behind the barrel.
31. Wait for the shooting to stop.
32. Take the **SHORT FUSE** from the wall crack beside the barrel.
33. **USE/COMBINE** the short fuse with the dynamite.
34. **PUT** the dynamite into the crack.
35. Light it.
36. Hide behind the barrel.
37. After the explosion, enter the new area.
38. Step on the floor tile showing an arrow.
39. Enter the corridor that opens.

> [!WARNING]
> Do not fall through the crack in the wall.

40. Deal with the skeleton enemy.
41. Approach the strange machine.

**Continue to:** [AITD3-C03] Chapter 3.

## [AITD3-C03] Chapter 3 — Gear Machine and Kid's Ghost

**Goal:** Repair the machine, reach the opposite building, and follow the Kid through the picture.

1. **PUT** the **SHERIFF'S BADGE** into the mechanism as the missing gear.
2. **USE** the **WHIP** to turn the handle on top.
3. Go through the door.
4. Take the **FLASK**.
5. Walk up the plank.
6. Take the **WINCHESTER BULLETS**.
7. Return to the room.
8. Face the plank.
9. **RUN** along it and leap through the glass window of the opposite building.
10. Continue down the main hallway.
11. Take the **COSTUME RING** near the hole in the floor.
12. Ignore Emily for now.
13. Return to the first door on the left.
14. Note the map between the two left lanterns.
15. **USE** a match to light the lantern beside the door.
16. Enter the opened room.

> [!OPTIONAL]
> Lighting the opposite lantern reveals the ghost of the Indian shaman and a message.

17. Take the **NEWSPAPER SHEET**.
18. When the door closes and the Kid's ghost appears, **PUT** the **DRIED MEAT** into the clock.
19. Take the **TOKEN** obtained after silencing the vulture.
20. Follow the Kid when he jumps into the picture.
21. Before leaving, take the **NIGHT VALET** and **FLASK**.

**Continue to:** [AITD3-C04] Chapter 4.

## [AITD3-C04] Chapter 4 — Balcony, Flash Puzzle, and Shaft

**Goal:** Open the balcony route, defeat the two-headed monster with the flash, and descend the shaft.

1. **SEARCH** the dresser.
2. Take the **30/30 BULLET**, **PEARL**, and **BULB**.
3. **PUSH** the dresser mirror.
4. Take the **KEY** hidden behind it.
5. Check the pouch on the lady statue on the bed.
6. Take the **ARROW**.
7. **PUT** the arrow into the bow of the angel statuette.
8. Return to the main hallway through the newly opened door.
9. **USE** the key on the door beside the hole.
10. Enter.
11. Take the **FLASK**, **INSTRUCTION SHEET**, and **EMILY'S DIARY**.
12. Remove the **DIAMOND** from the costume ring.
13. **PUT** the diamond into the missing eye of the small dragon statuette.
14. Take the resulting **BOX OF WINCHESTER BULLETS**.
15. Go to the balcony.
16. Walk toward the unusual green floor tile.
17. When the gunman begins shooting from behind the shutters, **PUT** the **NIGHT VALET** directly in front of the shutters.
18. Wait for the gunman to approach and fall.
19. **PUSH** the loose standing shutter to create a bridge.
20. Cross the gap and enter the room.
21. Take the **KEY**, **INSTRUCTION SHEET**, **SHUTTER RELEASE**, and **FLASH**.
22. Examine the photographs if desired for context.
23. Return across the balcony and back to the hallway.
24. **USE** the key on the right-hand door at the window through which you originally entered.
25. Enter.

> [!WARNING]
> Do not approach the screaming two-headed monster.

26. Locate the circle drawn on the floor beside the closet on the right.
27. Stand on the circle.
28. **USE** the **BULB**.
29. Then **USE** the **SHUTTER RELEASE** to assemble the flash.
30. **USE** the flash on the monster.
31. Take the **OIL CAN**.
32. **USE** it to refill the lamp.
33. **SHOOT** or hit the target on the closet.
34. Take the **WAR STICK** and **FLASK** from inside.
35. **USE** the token in the harpsichord's side slot.
36. After the story sequence, go down the shaft.

**Continue to:** [AITD3-C05] Chapter 5.

## [AITD3-C05] Chapter 5 — Lava Pillars, Library, and Cemetery

**Goal:** Cross the lava, obtain the pocket watch and printing clues, then open O.E.J.'s grave.

1. Light the lamp.
2. **RUN** to the archway before the bats reach you.
3. Stand below the arch.
4. **JUMP** to the first lava pillar.
5. Continue jumping from the **center** of each pillar for safer landings.
6. At the fifth pillar, show the Indian the **WAR STICK**.
7. Take the **SMALL KEY** and **WINCHESTER BULLETS**.
8. Continue across the pillars.
9. Jump around the four central pillars in a **clockwise** direction, following the circular marking.
10. From the pillar with the circle, jump to the pillar on the **right** first.
11. Continue upward.
12. When stranded on the last pillar, **USE** the **INDIAN AMULET**.
13. Let the Indian shaman raise you to the building.
14. Defeat the star-throwing cowboy and the top-hat enemy.
15. Take the **FLASK**, **TOP HAT**, and **KEY**.
16. **USE** the key on the left door.
17. **SEARCH** all three bookcases; each contains a book.
18. **USE** the **SMALL KEY** on the locked book.
19. **SEARCH** the statuette and take the **POCKET WATCH**.
20. Light the match on the table to read the white book.
21. Take the **PRINTING PLATE**.
22. **USE** it on the printing press at the right side of the table.
23. Read the resulting newspaper.
24. Leave the room.
25. Go to the right-hand door.
26. **USE** the **POCKET WATCH** to open it.
27. After Morrison attacks, calm him according to the scripted sequence.
28. Take the **STORY-BOARD** from him.
29. Go to the marble bust on the left.
30. **PUT** the **TOP HAT** on it.
31. Take the **TWO BOXES OF WINCHESTER BULLETS**.
32. Wait for the sequence in which Morrison fires, the ghouls react, and the curtain is pulled from the stained-glass window.
33. After Morrison is killed, defeat the ghoul that attacks.
34. Go to the staircase leading toward the stained-glass window.
35. Stand in front of the staircase, take a small step back, and **SHOOT** the window.
36. Go up the stairs.
37. Drop into the cemetery.
38. When the two undertakers rise, **PUT** the **WAR STICK** at the center of the round stone of the dead.
39. Go to **O.E.J.'s grave**.
40. **USE** the **ACE OF DIAMONDS** to open it.
41. Take the **MESSAGE FROM ONE-EYED JACK**.
42. Go up to the new floor.

**Continue to:** [AITD3-C06] Chapter 6.

## [AITD3-C06] Chapter 6 — Ballroom, Film Puzzle, and Bank

**Goal:** Reveal the code 806, open the bank safe, recover the amulet, and reach the shack.

1. Take the **OIL CAN** from the table.
2. Take the **ROLL OF FILM**.
3. Take the **BAG OF PEMMICAN** from the cupboard.
4. Note the secret passage immediately to the right of the cupboard; leave its door for later.
5. Go to the barbecue mechanism at the fireplace.
6. **USE** the oil on the mechanism.
7. Enter the ballroom.
8. Continue to the middle.
9. **SEARCH** the large man and take the **HAMMER**.
10. **SEARCH** the woman opposite him and take the **WINCHESTER BULLETS**.
11. Continue toward the band while avoiding the guitarist's shots.
12. **SEARCH** the gramophone.
13. Take the **GUITAR STRING**, **MUSICAL SCORE**, and **SAFE KEY**.
14. Leave the ballroom, dealing with the shooting small enemy and avoiding the spinning one.
15. Open the door in the secret passage.
16. Go to the door directly ahead.
17. **PUT/USE** the **30/30 BULLET** in the door mechanism.
18. **USE** the **HAMMER** to break the lock.
19. Enter the room.
20. Go to the small model train station.
21. Take the **LIGHT BULB**, **BLASTING CAP**, and **MAP**.
22. Go to the mounting table on the opposite side.
23. **USE** the **GUITAR STRING** to repair it.
24. **PUT** the **LIGHT BULB** into it.
25. View the **ROLL OF FILM**.
26. **USE** the **MUSICAL SCORE**.

**Expected:** The code **806** is revealed.

27. Enter the bank through the doorway.
28. Take the **BOOK** from the table.
29. Open the picture at the far end.
30. Enter **806** on the code device.
31. Confirm that the trap behind the glass counters is disabled.
32. Go to the safe door.
33. **USE** the **PEARL**.
34. Then **USE** the **SAFE KEY**.
35. When the bank clerk exits the safe and steals the amulet, kill him.
36. Recover the **INDIAN AMULET**.
37. Take the **WINCHESTER BULLETS** and **BAG OF MONEY** from the safe.
38. Open the window.
39. Slide down to the shack.

**Continue to:** [AITD3-C07] Chapter 7.

## [AITD3-C07] Chapter 7 — Mine Cart and Train Station

**Goal:** Obtain the suitcase key, destroy the train station, and trigger the scripted death at the water tank.

1. Take the **MESSAGE** from your companion.
2. Take the **FLASK** from the crate in the corner.
3. Stand in front of the mine cart.
4. **SEARCH** it.
5. Take the **DETONATOR BOX** and **WINCHESTER BULLETS**.
6. Ride the mine cart.
7. After McCarthy is killed, either deal with the attackers or immediately enter the train station on the right.
8. Inside the station, go to the standing sign marked **"station."**
9. **PUSH** the sign.
10. Watch the blue bucket drop the **KEY TO THE SUITCASE**.
11. **SEARCH** the bench and take the **EYE-BOLT**.
12. **USE** the eye-bolt to ring the bell beside the door **three times**.
13. Leave while the door is slowly rising.
14. Immediately **PUT** the **BLASTING CAP** on the fence to the left.
15. Cross the railroad tracks.
16. Go to the wall on the opposite side.
17. **USE** the **DETONATOR** to destroy the train station.

> [!WARNING]
> The source says that if the station is not destroyed, the clerk can later steal the **BAG OF MONEY**, preventing progression.

18. Walk in the direction opposite the station.
19. Go to the water tank.
20. When Jed Stone orders you to drop the suitcase and its key, comply.

**Expected:** The scripted sequence kills Carnby.

**Continue to:** [AITD3-C08] Chapter 8.

## [AITD3-C08] Chapter 8 — Cougar Transformation and Recovery

**Goal:** Recover the golden eagle as a cougar, return to human form, defeat the werewolves, and reach the next underground area.

1. The **INDIAN AMULET** revives Carnby as a cougar.
2. Leave through the low vault.
3. Exit through the cemetery gates.
4. Enter the saloon.
5. Use the cougar's jump to climb the broken staircase.
6. Go to the hole in the floor and jump over it.
7. **RUN/JUMP** through the window to the roof.
8. **RUN/JUMP** through the wall crack and land on Jed's statue.
9. Take the **GOLDEN EAGLE**.
10. Follow the mine-cart tracks toward the shack.
11. Go behind the shack.
12. **USE** the tar barrel to coat your paw with tar.
13. Enter the building between the shack and cemetery.
14. **RUN** to the right-hand door.
15. **USE** the cask of silver salts to coat the paw with silver.
16. Return toward the cemetery.
17. When the two tortured men transform into werewolves, kill them with the **SILVER CLAWS**.
18. Return through the vault to the chamber.
19. Go to the fireplace.
20. **PUT** the **GOLDEN EAGLE** in the fireplace.

**Expected:** Carnby returns to human form.

21. After jumping out of the grave, go to the railroad track.
22. Take the **COLT** dropped by the armored man.
23. Take the **BAR OF SOAP** behind the cross of Carnby's former grave.
24. Go to the water tank.
25. When you encounter Carnby's double, do **not** try to kill him.
26. **DROP** the Colt.
27. Walk directly up to the double.

**Expected:** Carnby transforms into a cowboy.

28. Pick the **COLT** back up.
29. Climb the water tank.
30. Drop from the platform.
31. **USE** the **BAR OF SOAP** to kill the man with the metallic brush.
32. Take the **METALLIC BRUSH**.
33. Take the nearby **FLASK**.
34. **PUT** the metallic brush into the small hole in the peg protruding from the water column.
35. Go down the shaft.
36. Take the **NOTEBOOK** from one corner.
37. Take the **DEAD LEAF** from the opposite corner.
38. Examine the map on the wall.
39. **USE** the **DEAD LEAF** on the small Indian bust.
40. Climb the ladder.
41. Deal with the two large enemies.
42. **SEARCH** the opening in the wall on the right and take the **PICK-AXE**.
43. **SEARCH** the opening immediately left of the exit and take the **FLASK**.
44. Leave through the exit.

**Continue to:** [AITD3-C09] Chapter 9.

## [AITD3-C09] Chapter 9 — Invisible Platform Route and Laboratory Access

**Goal:** Cross the hidden platform path, obtain the poisoned-needle setup items, and open the laboratory.

1. Take the **SHEETS OF PAPER** on the left.
2. Stand to the left of the door through which you entered.
3. Walk toward the pit.
4. Step off the edge; a square platform should appear under you.
5. Follow this exact direction sequence:
   - **Left**
   - **Down**
   - **Left**
   - **Left**
   - **Up**
   - **Left**
   - **Up**
   - **Left**
   - **Up**
   - **Left**
6. On the far side, **RUN** up to the large "needle man."
7. Attack him with the **PICK-AXE**.
8. Enter and defeat the second enemy.
9. Take the **BOOK** he was reading.
10. Go to the lit candle.
11. **SEARCH** there and take the **SCORCHED BOOK**.
12. Find the candlestick embedded in the round pillar.
13. **PULL** it out to open the door.
14. Take the **WATER PITCHER** hidden behind the pillar.

> [!WARNING]
> Do **not** drink the water.

15. Take the **NEEDLE** near the door.
16. Enter the small corridor.
17. **POUR/USE** the water on the rifleman.
18. Enter the elevator.
19. Take the **PIGGY BANK**.
20. **THROW** it.
21. Take the **MICROSCOPIC GLASS PLATE**.
22. **PUSH** the elevator lever.
23. At the next level, enter the room.
24. Press the colored wall buttons in this exact order:
   1. **White**
   2. **Green**
   3. **Blue**
   4. **Red**

> [!TIP]
> The source says the microscopic glass plate reveals this sequence when used at the microscope.

25. Enter the laboratory.

**Continue to:** [AITD3-CF] Final Chapter.

## [AITD3-CF] Final Chapter — Laboratory and Final Showdown

**Goal:** Shrink through the laboratory puzzles, free Emily, defeat the Elwood Brothers and Jed Stone, and start the train.

1. Go to the far end of the room.
2. **SEARCH** the table.
3. Take the **VIAL OF POISON**.
4. **USE** the poison on the **NEEDLE**.
5. Go to the distilling coil beside the prison cell.
6. **USE** the poison on the coil to shrink Carnby.
7. Enter the cell through the bars.
8. **USE** the **POISONED NEEDLE**.
9. Punch the mad doctor to inject the poison.
10. Take the **KEY**, **STRAW**, and **BOTTLE OF AMMONIA**.
11. **USE** the key to open the cell door.
12. **USE** the poison on the distilling coil again to shrink.
13. Enter the small passage in the wall below the table.
14. **USE** the **STRAW**.
15. **RUN** straight into the passage.
16. Around halfway through, hold **SPACEBAR** to pole-vault across the chasm.
17. Take the **VIAL OF POTION**.
18. Leave quickly before Carnby returns to normal size.
19. When you reach the arachnid creature, **POUR/USE** the potion on the glowing food.
20. Move out of the way.
21. Let the creature eat the food and shrink.
22. Take the **POT OF GLUE** near the cobweb without touching the web.

> [!OPTIONAL]
> The eye-shaped figure on the wall can show what is happening to Emily, but the source warns that Jed Stone can attack while you do this.

23. Go to the corner with the ceiling opening.
24. **USE** the glue to climb the wall.
25. When the headless enemy attacks, take his **HEAD** from the counter.
26. **THROW** the head down the opening you used to enter.
27. Take the **LEAD INGOT** from the boulder.
28. **PUSH** the boulder aside.
29. Take the **FLASK** and **WINCHESTER** behind it.
30. Enter the next room.
31. Defeat **Cobra**.

> [!TIP]
> If Cobra is difficult, the source suggests shooting from one side of the room, running to the opposite side when he approaches, and repeating.

32. Take Cobra's **WIG** and **SILVER DOLLAR**.
33. Take the **FLASK** in the room.
34. **USE** the **SILVER DOLLAR** in the slot in Jed Stone's picture.
35. Enter the opened door.
36. Go down the ladder.
37. Take the **MATCHBOX** at the bottom.
38. Open the door and enter.
39. Let Jed run away; the source says you will deal with him later.

> [!WARNING]
> Do **not** approach the red engraved skull holding Emily.

40. Take the **PARCHMENT**.
41. Take the **BULLETS** from the corner.
42. Take the **SCORCHED NEWSPAPER** from the opposite corner.
43. Go to the crucible.
44. **PUT** the **LEAD INGOT** into it.
45. **USE** a match to melt the lead.
46. Let the molten lead cover the green gem.

**Expected:** Emily is freed.

47. Take the hardened lead, now the **EVIL WAND**.
48. Leave Emily and follow the door Jed used.
49. When the door closes and the spiked wall begins moving, kill the thug.
50. Take his **KNIFE**.
51. Face the door through which you entered.
52. Stand a few steps away.
53. **THROW** the **BOTTLE OF AMMONIA**.

**Expected:** Emily wakes and rescues Carnby.

54. Move toward the metal door.
55. **USE** **COBRA'S WIG** on the chain hanging from the wall to unlock the door.
56. Enter the final area.
57. Run to the room on the left with two arched doorways.
58. Stand in front of the totem pole.
59. **PUT** the **EVIL WAND** into the totem pole.

**Expected:** The Elwood Brothers are eliminated.

60. Take the **FLASK** in the room.
61. Run to the water reservoir.
62. **OPEN** the faucet and let the water drain.
63. Take the **RUBBER GLOVE** immediately to the left of the reservoir.
64. **WEAR** the glove.
65. Go to the electrical wires.
66. **USE** the **KNIFE** to cut one wire.
67. Return to the totem-pole room.
68. Wait for Jed to step into the water and be electrocuted.
69. Follow Emily.
70. Before leaving, take the **SACK OF COAL** beside the metal door.
71. Go to the train engine.
72. **PUT** the coal into the furnace.
73. **USE** a match to light the furnace.
74. **PUSH** the lever on the right.

**Expected:** Ending sequence.

## Source

Reformatted from the user-provided walkthrough by TheGADMan for personal, LLM-assisted play.

Reference: https://gamefaqs.gamespot.com/pc/565051-alone-in-the-dark-3/faqs
