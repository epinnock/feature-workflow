# Stage 1 - Figma proposal

## Which file

Proposals go in the design-system file of the surface being changed, so the frames are built
from the same components and variables the product uses. Keep a table like this one in your
ops repo (for example in the skill's copy of this file, or in `features/HUB.md`) and fill it in
once:

| Surface | File | Key | Conventions |
|---|---|---|---|
| `<dashboard repo>` (web app) | `<Product> Dashboard - Design system` | `<file key>` | pages (Cover, Foundations, Components, Screens) and their ids; variable collection and its modes (Light / Dark); fonts; where the component ledger and design-system docs live |
| `<plugin or mobile repo>` | `<Product> <Surface> - Design system` | `<file key>` | fixed window or device size (frames that wide); earlier proposal pages and their ids |
| Cross-surface flows (API, search, roadmap-level) | `Screens & Flows` | `<file key>` | one band per cluster, band pitch, where labels sit |

Add a new page named `<Feature> - proposal`, with a title card (feature name, date, one-line
summary, link to plan.md) at the top left, then one frame per screen or state. Name frames
`<Area> / <Screen> · <state>` so the ledger reads like the plan (`Orders / List · loaded`,
`Orders / List · empty`, `Orders / Access denied`).

Draw with local primitives that follow the file's token recipe rather than library instances
when the shipped component has baked children an instance cannot change (Card, Dialog). Reuse
instances for Button, Badge, Input, Select, Avatar, sidebar and header, which usually map
cleanly. Write down each surface's recipe here once (ground, card radius and border, text
colours, accent, type family; which modes exist and whether to build Light and let variables
carry Dark), because two surfaces of the same product often look nothing alike and a builder
who guesses will draw the wrong one. Build from the file's own component instances and
variables; hand-draw only what has no component. Frames match the width of the existing screens
(a plugin window, a device, a 1440 desktop); scrolling content may be taller.

Show real content, in the product's own units: actual project names, plausible counts, the
copy that will ship. Placeholder text at a gate produces placeholder decisions.

## Transport

- **Local plugin bridge** (a Figma plugin that exposes the full Plugin API to your agent over a
  local connection, e.g. a console/bridge MCP server): no rate limit beyond Figma's own, full
  Plugin API. Preferred for anything over ~30 writes or for building components. Pin the target
  file first and prefix every script with `if (figma.root.name !== '<expected>') throw`, so a
  script never writes into whatever file happens to be focused. If the bridge detaches and only
  a person at that machine can reattach it, do not restart it from a script. Known gotchas:
  `figma.currentPage` resets per script; bound paints can drop opacity; `resize()` sets both
  axes.
- **Remote Figma MCP** (`use_figma`; load its `/figma-use` skill first): fine for a handful of
  frames. It is rate limited per seat (check your plan's limit); run two builders at most.
- `get_screenshot` / `download_assets` for the PNG renders; `get_metadata` to confirm ids.

## Output

`figma/ledger.json`:

```json
{"fileKey": "<file key>", "page": {"name": "Order history - proposal", "id": "...", "url": "https://www.figma.com/design/<key>?node-id=..."},
 "titleCard": "...", "frames": [{"name": "Orders / List · loaded", "id": "...", "png": "figma/orders-list-loaded.png", "size": [1440, 1024]}],
 "localPieces": [{"name": "StatTile", "id": "..."}], "deviations": ["..."], "builtAt": "YYYY-MM-DDTHH:MM:SSZ"}
```

A feature that spans two files can add `"pluginFile": {"fileKey": ..., "frames": [...]}`;
`figma-vs-stage.py` reads both lists.

Plus one PNG per frame beside it, and in `plan.md`: the "UI changes" section (what each
screen does, in words, with the copy) and the "Built Figma frames" table (frame, node id).
Link the page as `https://www.figma.com/design/<key>?node-id=<page id with a dash>`.

## When there is no UI

Say so in STATUS.md ("Stage 1: no UI surface; API/worker change only") and put a short
sequence description in `plan.md` instead. Do not invent screens to have something to show.
