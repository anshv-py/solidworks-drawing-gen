# Evaluation / test models

Generated with OCCT by `scripts/generate_fixtures.py`; `manifest.json` holds the
construction parameters that tests use as ground truth.

| Model | What it exercises |
|---|---|
| plate_with_holes | through holes, 2×2 rectangular pattern, centre hole; STL twin; m/inch unit variants |
| mounting_plate | counterbored holes, linear pattern, corner rounds |
| pocketed_block | rectangular pocket, blind hole |
| bracket | L-bracket, inside fillet, through slot, holes; STL twin |
| shaft | stepped shaft (external diameters), conical end chamfers |
| flange | hub + bore, 8× bolt holes on Ø86 PCD (from the reference drawing's nominal sizes); STL twin |
| cylindrical_part | blind axial bore, cross hole |
| enclosure | open box (deep pocket), wall holes |
| chamfered_block | planar chamfer, edge round |
