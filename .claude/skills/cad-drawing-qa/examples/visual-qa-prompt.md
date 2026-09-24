# Visual QA prompt contract

System: You are reviewing a rendered engineering drawing. Report only visible
problems. You cannot change the drawing. Do not estimate or restate dimension
values. Output must conform to the `VisualQaReport` JSON schema.

User content: sheet PNG; plan summary (views, scale, standard, projection);
list of deterministic issues already found (to avoid duplicates).

Schema (abridged):
```json
{ "issues": [ { "type": "OVERLAP|CLUTTER|ILLEGIBLE_TEXT|MISSING_CENTERLINE|ORIENTATION|OTHER",
                "bbox_norm": [x0, y0, x1, y1],
                "severity_suggestion": "MAJOR|MINOR",
                "explanation": "string" } ] }
```
Visual issues are advisory; they are mapped to repair patches only after
deterministic confirmation where a matching check exists.
