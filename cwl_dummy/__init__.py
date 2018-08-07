# Based on https://github.com/common-workflow-language/cwl-upgrader/blob/master/cwlupgrader/main.py


import argparse
import shlex
import sys
import textwrap
import traceback
# noinspection PyUnresolvedReferences
from typing import Any, List, Mapping, MutableMapping, MutableSequence, TypeVar, overload

import ruamel.yaml

from cwl_dummy.utils import ensure_sequence_form, mapping_to_sequence


T = TypeVar("T")


class UnhandledCwlError(Exception):
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", nargs="+", help="a Workflow or CommandLineTool to mock")
    args = parser.parse_args()
    for filename in args.filename:
        mock_file(filename)


def mock_file(filename: str) -> None:
    print(f"Mocking file {filename}")

    with open(filename, "r") as f:
        cwl = ruamel.yaml.safe_load(f)

    if cwl.get("cwlVersion") != "v1.0":
        raise Exception("can't process CWL versions other than v1.0")

    try:
        cwl = mock_document(cwl)
    except UnhandledCwlError as e:
        print("=" * 32 + " Unhandled CWL " + "=" * 32)
        print(f"  Could not handle CWL file at {filename}")
        print(f"  You must create the .dummy file yourself, or the workflow will not run.")
        print(f"  Reason for failure:")
        print(f"    {e!s}")
        while hasattr(e, "__cause__") and e.__cause__ is not None:
            e = e.__cause__
            print("  because:")
            if isinstance(e, UnhandledCwlError):
                print(f"    {e!s}")
            else:
                print(f"    {traceback.format_exception_only(type(e), e)}")
        if hasattr(e, "__context__") and e.__context__ is not None:
            e = e.__context__
            print(f"  caused by the following exception:")
            print(textwrap.indent("".join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip(), "    "))
        print("=" * 79)

    with open(filename + ".dummy", "w") as f:
        ruamel.yaml.round_trip_dump(cwl, f, default_flow_style=False)

    print(f"Wrote mocked file to {filename}.dummy")


def mock_document(cwl):
    assert isinstance(cwl, MutableMapping)  # was an if, but why wouldn't it be?
    cls = cwl.get("class")
    if cls == "Workflow":
        cwl = mock_workflow(cwl)
    elif cls == "CommandLineTool":
        cwl = mock_command_line_tool(cwl)
    elif cls == "ExpressionTool":
        print(">>> Warning: ignoring ExpressionTool <<<")
    else:
        raise UnhandledCwlError(f"Unknown document class {cls!r}")
    return cwl


def mock_workflow(cwl):
    assert cwl["class"] == "Workflow"
    assert all(x in cwl for x in {"inputs", "outputs", "steps"})
    cwl["steps"] = ensure_sequence_form(cwl["steps"])

    for step in cwl["steps"]:
        if isinstance(step["run"], str):
            # got a filename -- recurse into it
            # NB: CWL workflows are not allowed to refer to themselves
            # (even indirectly), so we don't need to keep track of which
            # files we've seen.
            mock_file(step["run"])
            step["run"] += ".dummy"
        else:
            # probably a nested CWL document
            try:
                step["run"] = mock_document(step["run"])
            except UnhandledCwlError as e:
                raise UnhandledCwlError(f"Unhandled workflow step with id {step['id']}") from e

    return cwl


SAFE_REQUIREMENTS = {
    "InlineJavascriptRequirement", "SchemaDefRequirement", "InitialWorkDirRequirement", "ResourceRequirement"
}


def mock_command_line_tool(cwl):
    assert cwl["class"] == "CommandLineTool"
    assert all(x in cwl for x in {"inputs", "outputs"})
    if any(x in cwl for x in {"stdin", "stdout", "stderr"}):
        raise UnhandledCwlError("Cannot handle stdin/stdout/stderr references automatically")
    cwl["baseCommand"] = ["sh", "-c"]
    for x in {"requirements", "hints"} & cwl.keys():
        seq = ensure_sequence_form(cwl[x], key_key="class")
        cwl[x] = [
            req for req in seq if req["class"] in SAFE_REQUIREMENTS
        ]
        for req in seq:
            if ":" in req["class"] or "#" in req["class"]:
                print(f">>> Warning: unknown requirement/hint {req['class']!r} <<<")

    cwl["inputs"] = ensure_sequence_form(cwl["inputs"])
    cwl["outputs"] = ensure_sequence_form(cwl["outputs"])

    output_files = []
    output_dirs = []
    for output in ensure_sequence_form(cwl["outputs"]):
        try:
            output_binding = output["outputBinding"]
        except KeyError:
            raise UnhandledCwlError("CommandLineTool has output without outputBinding (does it use cwl.output.json?)") from None
        if type_contains(output["type"], "File"):
            if "secondaryFiles" in output:
                secondary_files = ensure_list(output["secondaryFiles"])
                # FIXME: this is not correct!
                output_files.extend(secondary_files)
            if "glob" in output_binding:
                # FIXME: globs can contain glob characters
                output_files.extend(ensure_list(output_binding["glob"]))
        elif type_contains(output["type"], "Directory"):
            if "glob" in output_binding:
                # FIXME: globs can contain glob characters
                output_dirs.extend(ensure_list(output_binding["glob"]))
        else:
            pass  # ignore non-files

    # This uses the following behaviour described in the CWL spec:
    #
    #     If the value of a field has no leading or trailing
    #     non-whitespace characters around a parameter reference, the
    #     effective value of the field becomes the value of the
    #     referenced parameter, preserving the return type.
    #
    # In other words, as long as we pass each expression as a separate
    # argument, the CWL runner will quote them for us (and also expand
    # them properly if the value is an array).
    #
    # This is POSIX-compatible; see the pages for `touch` and `mkdir`:
    # http://pubs.opengroup.org/onlinepubs/9699919799/utilities/touch.html
    # http://pubs.opengroup.org/onlinepubs/9699919799/utilities/mkdir.html
    # and also (for "--" support):
    # http://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap12.html#tag_12_02
    cwl["arguments"] = ["""
    sleep 10
    mode=dir
    for arg in "$@"; do
        if [ "$mode" = dir ]; then
            if [ "$arg" = -- ]; then
                mode=file
            else
                mkdir -p -- "$arg"
            fi
        elif [ "$mode" = file ]; then
            if [ "$arg" = -- ]; then
                mode=none
            else
                touch -- "$arg"
            fi
        fi
    done
    """] + output_dirs + ["--"] + output_files + ["--"]

    for arg in output_dirs + output_files:
        if arg.count("$") > 1:
            raise UnhandledCwlError(f"Multiple parameter references in field: {arg}")
        if "$" in arg and (arg.strip()[0] != "$" or arg.strip()[-1] not in ")}"):
            raise UnhandledCwlError(f"Leading or trailing characters in field with parameter reference: {arg}")

    return cwl


def type_contains(typ, needle):
    """(haystack, needle) -> bool

    NOTE: this is unlikely to work if the type you're searching for is
    anything but one of the simple CWL types (int, File, ...).
    """
    if isinstance(typ, str):
        if typ.endswith("?"):
            return needle == "null" or type_contains(typ[:-1], needle)
        if typ.endswith("[]"):
            return type_contains({"type": "array", "items": typ[:-2]}, needle)
        return isinstance(needle, str) and needle == typ
    assert isinstance(typ, dict)
    if typ["type"] == "array":
        assert "items" in typ
        if isinstance(typ["items"], str):
            return type_contains(typ["items"], needle)
        return any(type_contains(item, needle) for item in typ["items"])
    if typ["type"] == "record":
        return any(
            type_contains(field["type"], needle) for field in (
                typ["fields"] if isinstance(typ["fields"], list) else typ["fields"].values()
            )
        )
    if typ["type"] == "enum":
        return needle.get("type") == "enum" and set(needle["symbols"]) == set(typ["symbols"])
    raise TypeError(f"Invalid (or unknown) type: {typ!r}")


def attempt_to_quote(s: str) -> str:
    """Try to quote a string for use in `arguments`."""
    if "$(" not in s and "${" not in s:
        # easy case -- it definitely doesn't contain any expression
        return shlex.quote(s)
    # TODO
    return "'" + s + "'"


def normalise_type(frag):
    assert False, "do not use this function"
    # TODO: this is very bad, we should use schema-salad for this
    # (which would also take care of $import)
    # Nevertheless, this is actually more capable than schema-salad --
    # "File[][]" will work here, but not in cwltool.
    assert frag, "zero-length type not allowed"
    if isinstance(frag, str):
        if frag in {"stdout", "stderr"}:
            raise ValueError("can't handle stdout or stderr types")
        if frag.endswith("?"):
            return normalise_type([frag[:-1], "null"])
        if frag.endswith("[]"):
            return {
                "type": "array",
                "items": normalise_type(frag[:-2]),
            }
        return frag
    if isinstance(frag, MutableSequence):
        ts = []
        for type in frag:
            ntype = normalise_type(type)
            if isinstance(ntype, list):
                ts.extend(ntype)
            elif ntype not in ts:
                ts.append(ntype)
        return ts
    assert isinstance(frag, MutableMapping)
    if "inputBinding" in frag:
        frag.pop("inputBinding")
    # Recurse over arrays
    if "items" in frag:
        frag["items"] = [normalise_type(t) for t in frag["items"]]
    # Recurse over records
    if "fields" in frag:
        frag["fields"] = [normalise_type(t) for t in frag["fields"]]
    return frag


@overload
def ensure_list(x: List[T]) -> List[T]: ...


def ensure_list(x: T) -> List[T]:
    if isinstance(x, list):
        return x
    return [x]


if __name__ == "__main__":
    sys.exit(main())
