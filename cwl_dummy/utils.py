"""Awful junk that doesn't fit anywhere else."""


from typing import Any, List, Mapping, Sequence, TypeVar, Union


K = TypeVar("K")


def mapping_to_sequence(
    mapping: Mapping,
    key_key: K = "id",
    single_value_key: K = "type",
) -> List[Mapping[K, Any]]:
    """Convert mapping form to sequence form.

    This turns something that looks like this:

        inputs:
          my_input:
            doc: "an input"

    into something that looks like this:

        inputs:
        - id: my_input
          doc: "an input"

    Alternatively, it can turn something that looks like this:

        inputs:
          my_input: string

    into this:

        inputs:
        - id: my_input
          type: string

    Both "id" and "type" are configurable via the `key_key` and
    `single_value_key` parameters. For example, the requirements and
    hints sections should have `key_key` set to "class".
    """
    assert isinstance(mapping, Mapping)
    return [
        {
            key_key: k,
            **(v if isinstance(v, Mapping) else {single_value_key: v})
        }
        for k, v in mapping.items()
    ]


def ensure_sequence_form(mapping_or_sequence: Union[Mapping, Sequence], **kwargs) -> Sequence:
    """Ensure the argument is in sequence form."""
    if isinstance(mapping_or_sequence, Mapping):
        return mapping_to_sequence(mapping_or_sequence, **kwargs)
    assert isinstance(mapping_or_sequence, Sequence)
    return mapping_or_sequence
