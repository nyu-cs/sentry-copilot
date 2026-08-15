# Template matching foundation

M0.3b.1 adds source-neutral OpenCV matching for one caller-supplied immutable BGR
`TemplateImage` against one explicit `Frame`, `ContentViewport`, and normalized or pixel search
ROI. It does not carry game-specific assets or rules.

`TemplateMatchResult` is immutable and records the score, caller threshold, match flag, raw-frame
search and match bounds, template ID, and frame/source provenance. Pixel ROIs must lie completely
inside the supplied content viewport; templates must fit inside the search region.

`debug_output_path` is optional. When supplied, the matcher writes an annotated copy to that exact
caller-selected path; the original frame and template are never modified. The module does not
perform OCR, page/player/strategy recognition, UI interaction, or domain-state mutation.
