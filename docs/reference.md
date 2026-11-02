# Reference

## Offensive formations and slots

The supplied November 2026 playbook contains 34 plays in 10 formations. A
drawn route identifies its player by `Slot_0`. Its `Points_0` array contains
the waypoints drawn *after* the player leaves their starting position.

For these ten formations, the game assigns the same position to each slot:

| Slot | Position | Starting alignment |
| ---: | --- | --- |
| 0 | Quarterback (QB) | Behind the center |
| 1 | Center (C) | Always (−50, 0) |
| 2 | Left tackle (LT) | Always (−50, −350) |
| 3 | Right tackle (RT) | Always (−50, 350) |
| 4 | Running back (RB) | Varies by formation |
| 5 | Right receiver (WR-R) | Positive Y |
| 6 | Left receiver (WR-L) | Negative Y |

Each pair below is **(X, Y)** in game units relative to the ball. All starting
heights are zero. On the diagram, positive X is upfield, positive Y is to the
right, and the cyan line marks X = 0.

| Formation | QB · 0 | RB · 4 | WR-R · 5 | WR-L · 6 |
| --- | --- | --- | --- | --- |
| Twins Right | (−600, 0) | (−50, 1050) | (−50, 1650) | (−50, −1350) |
| Twins Left | (−600, 0) | (−50, −1050) | (−50, 1400) | (−50, −1650) |
| Singleback Deuce | (−400, 0) | (−650, 0) | (−50, 1700) | (−50, −1700) |
| Shotgun Right | (−600, 0) | (−550, 300) | (−50, 1650) | (−50, −1650) |
| Shotgun Left | (−600, 0) | (−550, −300) | (−50, 1650) | (−50, −1650) |
| I-Wing Right | (−400, 0) | (−700, 0) | (−150, 700) | (−50, −1650) |
| I-Wing Left | (−400, 0) | (−700, 0) | (−50, 1650) | (−150, −700) |
| Goal Line | (−400, 0) | (−650, 0) | (−100, 700) | (−100, −700) |
| Bunch Right | (−600, 0) | (−200, 1050) | (−50, 1650) | (−50, −1350) |
| Bunch Left | (−600, 0) | (−200, −1050) | (−50, 1350) | (−50, −1650) |

### How the positions were verified

The source for the coordinates is the installed **Gridiron Remastered Playtest**,
Steam build **26369073**, asset `GridIron/Content/CustomCookData/formations.txt`
(payload SHA-1 `710db78a605ae87d328a96cb916381e47bc7c942`). Match
`FormationName_0` to `formationName` and use the slot number as the key in
`playerPositions`. Each entry explicitly supplies `playerType` and
`playerPosition`. The game calls both tackles T and both receivers WR; the
editor distinguishes sides using their lateral coordinates. The Twins Right
alignment also matches the labeled P11A-SWRT screenshot.

The sample has 25 Twins Right plays and one play for each other formation.
Of the Twins Right plays, seven route the left tackle, six route the right
tackle, and twelve route neither. The center has no drawn route anywhere in
this file, although it has an explicit starting position in every lineup.
These observations describe the sample; they do not establish eligibility rules.

The installation also has seven other offensive definitions (Huddle, Wide Wing,
Flying V, Wedge, L Right, L Left, Strongman). Their availability in the game's
custom-play editor is unverified. For an unrecognized formation, the editor
can still display the saved waypoints and raw slot numbers.

## gridiron_playbook

```{eval-rst}
.. automodule:: gridiron_playbook
   :members:
```
