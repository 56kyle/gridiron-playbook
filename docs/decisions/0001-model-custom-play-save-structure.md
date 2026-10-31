---
status: accepted
date: 2026-10-27
---

# Model the complete custom-play save structure

## Context and Problem Statement

`data/GridIronCustomPlays.json` contains Unreal save metadata and a collection of drawn football plays. The package needs typed models that validate this document and preserve its structure when serialized. The sample contains 24 complete plays, but its last drawn play contains only a formation name.

## Decision Drivers

- Preserve the document's metadata, property names, and omitted fields.
- Expose readable Python attributes and typed nested values.
- Distinguish complete plays from partially saved drawing state.
- Avoid treating sample names, versions, or collection sizes as format constraints.

## Considered Options

- Model only the football plays and leave the save envelope as untyped data.
- Use one permissive play model for complete plays and partial drawing state.
- Model the complete document with separate complete-play and last-drawn-play models.

## Decision Outcome

Choose the complete document model with separate play and drawing-state models. `GridironPlaybook` validates the top-level document; `GridironPlay` requires a formation name, play name, and routes. Nested models represent coordinates, routes, save properties, header versions, and the observed schema descriptor variants.

Use snake-case attributes with explicit aliases for exported property names. Accept either attribute names or aliases during validation. Serialize with `mode="json"`, `by_alias=True`, and `exclude_unset=True` to reproduce the supplied JSON structure without adding omitted fields.

The last drawn play requires a formation name. Its absent play name and routes have empty defaults; explicit null values remain invalid. These defaults make the partial state usable while `exclude_unset=True` preserves whether those fields were present.

Use frozen models and tuples for sequence values. Pydantic accepts JSON arrays as tuples and serializes them back to arrays. The schema registry remains a dictionary keyed by property path; freezing a model prevents field assignment but does not make that dictionary immutable.

Reject unknown fields rather than silently discard them. Use UUID values for version and struct identifiers, and a fixed two-element tuple for the custom-version format and entries. Keep names, engine versions, slot numbers, and collection lengths open rather than infer enums or limits from one sample. These models describe the observed export format, not every possible Unreal save variant.

### Consequences

- Callers can validate the supplied document directly and navigate typed play data.
- Complete plays cannot accidentally omit a play name or routes.
- New exported fields and descriptor variants require deliberate schema updates.
- Serialization preserves JSON values and field presence, not whitespace or original UUID text formatting.

### Confirmation

Tests validate the entire supplied document and compare its JSON structure after serialization. Focused tests cover aliases, required fields, partial drawing state, nested invalid input, and model assignment protection. Project lint, type-check, and test sessions check the implementation.

## Pros and Cons of the Options

### Model only football plays

- Good, because the initial interface is small.
- Bad, because callers must separately handle metadata and the document cannot be validated as a whole.

### Use one permissive play model

- Good, because one type represents both saved forms.
- Bad, because incomplete entries would also be accepted in the completed-play collection.

### Model the full document with separate play states

- Good, because each saved form has an explicit contract and metadata remains typed.
- Bad, because the package must maintain models for the observed export descriptors as well as football data.

## More Information

The source of this decision is the structure in `data/GridIronCustomPlays.json`. No binary save parser, file-loading API, CLI changes, or conversion to a separate football domain format is part of this change.
