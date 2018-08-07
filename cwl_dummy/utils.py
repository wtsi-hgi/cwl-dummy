"""Awful junk that doesn't fit anywhere else."""


import re
from typing import Any, List, Mapping, Sequence, TypeVar, Union, overload


T = TypeVar("T")
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


def strip_references(s: str) -> str:
    """Remove parameter references from a string.

    NOTE: JavaScript expressions are not necessarily removed.
    """
    # This is lifted from section 3.4 "Parameter references" of the CWL
    # spec -- although it's represented as a BNF grammar, it doesn't
    # recurse, so it can be written as a regular expression.
    return re.sub(r"""\$\(\w+(\.\w+|\['([^']|\\')*'\]|\["([^"]|\\")*"\]|\[\d+\])*\)""", "", s)


@overload
def ensure_list(x: List[T]) -> List[T]: ...


def ensure_list(x: T) -> List[T]:
    if isinstance(x, list):
        return x
    return [x]
