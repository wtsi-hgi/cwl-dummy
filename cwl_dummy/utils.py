"""Awful junk that doesn't fit anywhere else."""


import re
import textwrap
import traceback
from typing import Any, List, Mapping, Sequence, TypeVar, Union, overload


T = TypeVar("T")
K = TypeVar("K")


class UnhandledCwlError(Exception):
    pass


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


def format_error(e, filename) -> str:
    lines = [
        "=" * 32 + " Unhandled CWL " + "=" * 32,
        f"  Could not handle CWL file at {filename}",
        f"  You must fix the .dummy file yourself, or the workflow will not run.",
        f"  Reason for failure:",
        f"    {e!s}"
    ]
    while hasattr(e, "__cause__") and e.__cause__ is not None:
        e = e.__cause__
        lines.append("  because:")
        if isinstance(e, UnhandledCwlError):
            lines.append(f"    {e!s}")
        else:
            lines.append(f"    {traceback.format_exception_only(type(e), e)}")
    if hasattr(e, "__context__") and e.__context__ is not None:
        e = e.__context__
        lines.append(f"  caused by the following exception:")
        lines.append(textwrap.indent("".join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip(), "    "))
    lines.append("=" * 79)
    return "\n".join(lines)
