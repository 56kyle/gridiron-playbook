# Usage

## Validate custom plays

```python
from pathlib import Path

from gridiron_playbook.playbook import GridironPlaybook

playbook = GridironPlaybook.model_validate_json(
    Path("data/GridIronCustomPlays.json").read_text(encoding="utf-8")
)
play = playbook.root.properties.custom_plays[0]
print(play.formation_name, play.play_name)

exported_json = playbook.model_dump_json(by_alias=True, exclude_unset=True, indent=2)
```

The models preserve the save header, schema registry, play data, and trailing bytes.
Use `by_alias=True` to retain exported keys such as `CustomPlays_0` and `X_0`.
Use `exclude_unset=True` to preserve omitted fields in the last drawn play.
Unknown fields raise a Pydantic `ValidationError`.

## Command line

```{eval-rst}
.. typer:: gridiron_playbook.__main__:main
    :prog: gridiron-playbook
    :nested: full
```
