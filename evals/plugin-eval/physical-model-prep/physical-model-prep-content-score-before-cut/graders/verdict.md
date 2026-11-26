---
type: llm
---

PASS if the reply gives CUT red 255,0,0, SCORE blue 0,0,255, ENGRAVE black 0,0,0 and a REFERENCE layer that is turned off before sending, and says blue (score) runs before red (cut) so scores land before pieces drop loose.
FAIL if it omits the RGB values, or runs the cut before the score.
