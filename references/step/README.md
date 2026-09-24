# STEP (ISO 10303)

| Source | Notes |
|---|---|
| ISO 10303-21 (clear-text encoding, "Part 21") | file syntax; our upload sniffing checks the `ISO-10303-21;` header |
| ISO 10303 AP203 / AP214 / AP242 | application protocols; AP242 adds semantic PMI (GD&T) - not parsed yet |
| CAx Implementor Forum recommended practices | https://www.cax-if.org (units, PMI, colours, validation properties) |

The ISO standards are purchased documents and are not stored here.
Unit handling verified by tests: files declared in mm, m and inch all read back in mm.
