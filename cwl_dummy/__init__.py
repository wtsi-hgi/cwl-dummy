# Based on https://github.com/common-workflow-language/cwl-upgrader/blob/master/cwlupgrader/main.py


import argparse
import pathlib
import sys
import textwrap
# noinspection PyUnresolvedReferences
from typing import Any, List, Mapping, MutableMapping, MutableSequence, TypeVar, cast, overload

import ruamel.yaml.scalarstring

from cwl_dummy.utils import (
    UnhandledCwlError, ensure_list, ensure_sequence_form, format_error, mapping_to_sequence,
    strip_references
)


class Arguments:
    filename: List[str]
    force: bool


args: Arguments


def main():
    global args
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", nargs="+", help="a Workflow or CommandLineTool to mock")
    parser.add_argument("-f", "--force", action="store_true", help="write files even if they already exist")
    # The typeshed signature for parse_args currently does not account
    # for custom namespaces, so we have to cast to get typechecking.
    args = cast(Arguments, parser.parse_args(namespace=Arguments()))
    for filename in args.filename:
        mock_file(filename)


def mock_file(filename: str) -> None:
    print(f"Mocking file: {filename}")

    with open(filename, "r") as f:
        cwl = ruamel.yaml.round_trip_load(f)

    if cwl.get("cwlVersion") != "v1.0":
        raise Exception("can't process CWL versions other than v1.0")

    top_comment = ""
    try:
        cwl = mock_document(cwl)
    except UnhandledCwlError as e:
        err_str = format_error(e, filename)
        print(err_str)
        top_comment = textwrap.indent(err_str, "# ")
        # Since most things mutate `cwl` in-place, we can carry on and
        # write the file to make it easier to fix it by hand.

    outfilename = filename + ".dummy"
    if pathlib.Path(outfilename).exists() and not args.force:
        print(f"Not writing file because it already exists: {outfilename}")
    else:
        with open(outfilename, "w") as f:
            if top_comment:
                f.write(top_comment + "\n")
            ruamel.yaml.round_trip_dump(cwl, f, default_flow_style=False)
        print(f"Wrote mocked file: {outfilename}")


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


# This must not contain any shell metacharacters (including spaces).
MODE_SWITCH_FLAG = "cwl-dummy-mode-switch"


def mock_command_line_tool(cwl):
    assert cwl["class"] == "CommandLineTool"
    assert all(x in cwl for x in {"inputs", "outputs"})
    for x in {"requirements", "hints"} & cwl.keys():
        seq = ensure_sequence_form(cwl[x], key_key="class")
        for req in seq:
            if ":" in req["class"] or "#" in req["class"]:
                print(f">>> Warning: unknown {x[:-1]} {req['class']!r} <<<")
        cwl[x] = [
            req for req in seq if req["class"] in SAFE_REQUIREMENTS
        ]
    if any(x in cwl for x in {"stdin", "stdout", "stderr"}):
        raise UnhandledCwlError("Cannot handle stdin/stdout/stderr references automatically")

    cwl["inputs"] = ensure_sequence_form(cwl["inputs"])
    cwl["outputs"] = ensure_sequence_form(cwl["outputs"])

    output_files = []
    output_dirs = []
    for output in ensure_sequence_form(cwl["outputs"]):
        try:
            output_binding = output["outputBinding"]
        except KeyError:
            raise UnhandledCwlError("CommandLineTool has output without outputBinding (does it use cwl.output.json?)") from None
        if output_binding.get("loadContents", False):
            print(">>> Warning: output file contents may be checked <<<")
        if "glob" in output_binding:
            globs = ensure_list(output_binding["glob"])
            for glob in (strip_references(g) for g in globs):
                if any(c in glob for c in "*?["):
                    # "may" because JS expressions aren't removed.
                    print(">>> Warning: glob may contain glob characters <<<")
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
    cwl["baseCommand"] = ["sh", "-c", ruamel.yaml.scalarstring.PreservedScalarString(textwrap.dedent(f"""\
    sleep 10
    mode=pre
    for arg in "$@"; do
        if [ "$mode" = pre ]; then
            if [ "$arg" = {MODE_SWITCH_FLAG} ]; then
                mode=dir
            fi
        elif [ "$mode" = dir ]; then
            if [ "$arg" = {MODE_SWITCH_FLAG} ]; then
                mode=file
            else
                mkdir -p -- "$arg"
            fi
        elif [ "$mode" = file ]; then
            if [ "$arg" = {MODE_SWITCH_FLAG} ]; then
                mode=post
            else
                touch -- "$arg"
            fi
        fi
    done
    """))]
    cwl["arguments"] = [MODE_SWITCH_FLAG, *output_dirs, MODE_SWITCH_FLAG, *output_files, MODE_SWITCH_FLAG]

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


if __name__ == "__main__":
    sys.exit(main())
