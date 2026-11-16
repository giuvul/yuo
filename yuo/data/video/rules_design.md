Design rules (from reviews of earlier videos; each one was a frequent defect):

Layout
- Plan the scene area (1920 x 780) as a grid before drawing: keep 60 px margins, give every element its own
  region, and leave at least 24 px between any two texts. Nothing may be cut off at the edges.
- Text inside a box, pill or shape must fit with padding: box width >= 0.6 x font size x characters + 48 px.
  If a label is long, make the box bigger or the label shorter (max ~24 characters per label).
- Labels sit beside lines and arrows, never on them; no line or arrow may pass through text. Put a label
  above or below an arrow, or on a small solid background.
- Minimum font size 28 px for any text (labels, axis ticks, sub-labels); main text 40 px or more.

Colours
- Use only the theme colours: `C.bg`, `C.bg2`, `C.panel`, `C.line`, `C.text`, `C.dim` and the accents
  `C.write`, `C.read`, `C.bad`, `C.good`, `C.violet`; `alpha(C.read, 0.25)` for a see-through fill. No hex,
  rgb(), hsl(), white or black: the same video may be rendered in a light or a dark theme.
- Text on `C.bg`, `C.bg2` or `C.panel` is `C.text`, `C.dim` or an accent; text on a solid accent fill is
  `C.bg`. These pairs stay readable in both themes.

Every sentence
- Every sentence must change something visible: a new element, a highlight, a moving dot, a step drawn.
  Never show a frame with only a heading while the narration explains something.
- An element appears on the sentence that mentions it, not before.

Explain with pictures
- If the narration says "picture", "graph", "square", "curve", "triangle" or describes a spatial idea, draw
  it with SVG (polygons, lines, circles, axes). Proofs and geometry need the actual construction.
- Charts have axes with numeric ticks and units; points and lines must sit at their true values.

Numbers and facts
- Every number on screen must equal the number in the narration. Compute values before you write them and
  check them (e.g. an equilibrium point lies on both curves; totals add up).
- Prefer one worked example with real numbers carried through the scenes.
