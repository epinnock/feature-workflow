# Stage 2 - Narrated deck

Use the `narrated-deck` skill as-is for the mechanics (slides.html, narration.md, narrate.py,
build-deck.py, shoot.js, stitch.py, publishing). This file only says what a *feature* deck
contains and where it lives.

Working directory: `<features_root>/<slug>/deck/`. Copy the PNG renders from `../figma/` into
`deck/img/` and inline them as data URIs (a ten-line script that base64-encodes each `<img src>`
is enough) so the published page is self-contained.

## Slides (8-11, 4-5 minutes)

1. Title: feature name, one-sentence thesis, date.
2. The problem in the user's words: who hits it, how often, what it costs. Real numbers from
   the code or data where they exist ("3 accounts, 265 projects").
3. Current behaviour: what the product does today, from the plan's "Current behaviour"
   section. One diagram at most.
4-6. The proposal, one screen per slide, each with its Figma render and the copy that ships.
   A state slide (empty, error, denied) if the feature has one worth a decision.
7. Data and API: what is read, what is written, where it lives, who can call it.
8. Guarantees: the plan's "Guarantees" table as sentences ("a non-member can never…"), and
   who can see the feature. This replaces a generic security slide; the founder approves the
   guarantees, and Gate B reports against the same list.
9. What UAT will prove: the acceptance table, compressed to case names, with the "Needs
   founder" cases called out and when they could run. Delivery order in one line.
10. Founder decisions: three at most, each phrased so "yes" is a decision, with the
    recommended answer and whether it is expensive to reverse after code. One line at the end:
    "n further defaults are in the plan; say the word to change any".
11. The ask: "approve the design as shown" or "approve with these changes".

Narration 45-70 words a slide, sentence case, no bullet reading. The deck exists so the
founder can approve without opening the plan; anything they would need to look up belongs on
a slide.

## Memo deck for features with no UI

A pure API, worker, config or pipeline change skips Stage 1's frames, never the deck. Build a
3-5 slide memo deck with the same pipeline: (1) title + thesis, (2) what changes and for whom,
with one diagram of the before/after path, (3) guarantees, (4) what UAT will prove + the
founder decisions, (5) the ask. Two to three minutes. The plan is not a substitute: the
founder does not read plans.

## Output

- `deck/index.html`, the self-contained published page, `deck/<slug>.mp4`, `deck/narration.md`
- The published deck URL
- `plan.md` "Narrated deck" section: path, slide count, duration, voice, URL
- `links.json` "deck"; STATUS.md line, then present Gate A
