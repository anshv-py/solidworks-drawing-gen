# Reference drawings

## flange-gdt-reference.jpg
- Supplied by the project owner as an example of the *expected output quality*.
  Original source/copyright unknown (appears to be a textbook-style GD&T example);
  keep for internal reference only.
- It is a **manufacturing drawing**: limit dimensions (e.g. Ø44.60/44.45), datums A/B/C,
  position/perpendicularity/runout/parallelism/flatness frames, thread callout
  M42×1.5-6g. None of that tolerancing is derivable from a CAD model - CAD Drawing AI
  must reproduce the *geometry* content (views, sections, dimensions, center marks,
  hole pattern callout) and leave tolerancing unspecified unless supplied by the user.
- Views: a full section along the axis and an end view showing the 8×45° bolt
  pattern on a Ø86 PCD. `examples/models/flange.step` is a simplified model built
  from its nominal sizes (no thread, no counterbore steps) for testing.
