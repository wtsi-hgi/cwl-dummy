# Based on https://github.com/common-workflow-language/cwl-upgrader/blob/master/cwlupgrader/main.py
#
# Copyright (C) 2018 Genome Research Ltd.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.


import argparse
import datetime
import difflib
import io
import os.path
import pathlib
import sys
import textwrap
# noinspection PyUnresolvedReferences
from typing import Any, List, Mapping, MutableMapping, MutableSequence, Sequence, TypeVar, cast, overload

import ruamel.yaml.scalarstring

from cwl_dummy.utils import (
    UnhandledCwlError, ensure_list, ensure_sequence_form, format_error, mapping_to_sequence,
    strip_references
)


class Arguments:
    filenames: List[pathlib.Path]
    force: bool
    force_broken: bool
    diff: bool


args: Arguments


def main():
    global args
    parser = argparse.ArgumentParser()
    parser.add_argument("filenames", nargs="+", metavar="filename", type=pathlib.Path, help="a Workflow or CommandLineTool to mock")
    parser.add_argument("-f", "--force", action="store_true", help="write processed files even if they already exist")
    # Avoid overwriting files that have been fixed by hand.
    parser.add_argument("--force-broken", action="store_true", help="write unhandled files even if they already exist")
    parser.add_argument("--diff", action="store_true", help="show a diff for each updated file")
    # The typeshed signature for parse_args currently does not account
    # for custom namespaces, so we have to cast to get typechecking.
    args = cast(Arguments, parser.parse_args(namespace=Arguments()))
    for filename in args.filenames:
        mock_file(filename)


def mock_file(filename: pathlib.Path) -> None:
    print(f"Mocking file: {filename}")

    with open(filename, "r") as f:
        cwl = ruamel.yaml.round_trip_load(f)

    if cwl.get("cwlVersion") != "v1.0":
        raise UnhandledCwlError("Can't process CWL versions other than v1.0")

    top_comment = ""
    try:
        cwl = mock_document(cwl, filename.parent)
    except UnhandledCwlError as e:
        err_str = format_error(e, filename)
        print(err_str)
        top_comment = textwrap.indent(err_str, "# ")
        # Since most things mutate `cwl` in-place, we can carry on and
        # write the file to make it easier to fix it by hand.

    outfile = filename.with_suffix(filename.suffix + ".dummy")
    if args.diff and outfile.exists():
        with open(outfile, "r") as f:
            existing_lines = f.readlines()
        # Get the new CWL as a list of strings.
        new_file = io.StringIO()
        ruamel.yaml.round_trip_dump(cwl, new_file, default_flow_style=False)
        new_file.seek(0)
        new_lines = new_file.readlines()
        existing_time = datetime.datetime.fromtimestamp(os.path.getmtime(outfile), tz=datetime.timezone.utc)
        new_time = datetime.datetime.now(tz=datetime.timezone.utc)
        # If there's no difference, this won't print anything.
        print("".join(difflib.unified_diff(
            existing_lines,
            new_lines,
            fromfile=f"existing/{outfile}",
            tofile=f"modified/{outfile}",
            fromfiledate=existing_time.isoformat(),
            tofiledate=new_time.isoformat(timespec="microseconds" if existing_time.microsecond else "seconds"),
        )), end="")
    if top_comment and outfile.exists() and not args.force_broken:
        print(f"Not writing file because it already exists and could not be processed: {outfile}")
    elif outfile.exists() and not args.force:
        print(f"Not writing file because it already exists: {outfile}")
    else:
        with open(outfile, "w") as f:
            if top_comment:
                f.write(top_comment + "\n")
            ruamel.yaml.round_trip_dump(cwl, f, default_flow_style=False)
        print(f"Wrote mocked file: {outfile}")


def mock_document(cwl, directory: pathlib.Path):
    assert isinstance(cwl, MutableMapping)  # was an if, but why wouldn't it be?
    cls = cwl.get("class")
    if cls == "Workflow":
        cwl = mock_workflow(cwl, directory)
    elif cls == "CommandLineTool":
        cwl = mock_command_line_tool(cwl)
    elif cls == "ExpressionTool":
        print(">>> Warning: ignoring ExpressionTool <<<")
    else:
        raise UnhandledCwlError(f"Unknown document class {cls!r}")
    return cwl


def mock_workflow(cwl, directory: pathlib.Path):
    assert cwl["class"] == "Workflow"
    assert all(x in cwl for x in {"inputs", "outputs", "steps"})
    for x in {"requirements", "hints"} & cwl.keys():
        cwl[x] = filter_requirements(ensure_sequence_form(cwl[x], key_key="class"), kind=x[:-1])
    cwl["steps"] = ensure_sequence_form(cwl["steps"])

    for step in cwl["steps"]:
        if isinstance(step["run"], str):
            # got a filename -- recurse into it
            # NB: CWL workflows are not allowed to refer to themselves
            # (even indirectly), so we don't need to keep track of which
            # files we've seen.
            mock_file(directory / pathlib.Path(step["run"]))
            step["run"] += ".dummy"
        else:
            # probably a nested CWL document
            try:
                step["run"] = mock_document(step["run"], directory)
            except UnhandledCwlError as e:
                raise UnhandledCwlError(f"Unhandled workflow step with id {step['id']}") from e

    return cwl


# This must not contain any shell metacharacters (including spaces).
MODE_SWITCH_FLAG = "cwl-dummy-mode-switch"


def mock_command_line_tool(cwl):
    assert cwl["class"] == "CommandLineTool"
    assert all(x in cwl for x in {"inputs", "outputs"})
    for x in {"requirements", "hints"} & cwl.keys():
        cwl[x] = filter_requirements(ensure_sequence_form(cwl[x], key_key="class"), kind=x[:-1])
    if any(x in cwl for x in {"stdin", "stdout", "stderr"}):
        raise UnhandledCwlError("Cannot handle stdin/stdout/stderr references automatically")

    cwl["inputs"] = ensure_sequence_form(cwl["inputs"])
    cwl["outputs"] = ensure_sequence_form(cwl["outputs"])

    output_files = []
    output_dirs = []
    for output in ensure_sequence_form(cwl["outputs"]):
        if "secondaryFiles" in output:
            secondary_files = ensure_list(output["secondaryFiles"])
            # FIXME: this is not correct!
            output_files.extend(secondary_files)
        try:
            output_binding = output["outputBinding"]
        except KeyError:
            raise UnhandledCwlError("CommandLineTool has output without outputBinding (does it use cwl.output.json?)")
        if output_binding.get("loadContents", False):
            print(">>> Warning: output file contents may be checked <<<")
        if "glob" in output_binding:
            globs = ensure_list(output_binding["glob"])
            for glob in (strip_references(g) for g in globs):
                if any(c in glob for c in "*?["):
                    # "may" because JS expressions aren't removed.
                    print(">>> Warning: glob may contain glob characters <<<")
            # FIXME: globs can contain glob characters
            for i, glob in enumerate(globs):
                globs[i] = glob.replace("*", "s").replace("?", "q")
            if type_contains(output["type"], "Directory"):
                output_dirs.extend(globs)
            else:
                if not type_contains(output["type"], "File"):
                    print(">>> Warning: glob found, but output type does not allow globs <<<")
                output_files.extend(globs)

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
    """)), "cwl_dummy_runner"]  # This is $0
    cwl["arguments"] = [MODE_SWITCH_FLAG, *output_dirs, MODE_SWITCH_FLAG, *output_files, MODE_SWITCH_FLAG]

    for arg in output_dirs + output_files:
        if arg.count("$") > 1:
            raise UnhandledCwlError(f"Multiple parameter references in field: {arg}")
        if "$" in arg and (arg.strip()[0] != "$" or arg.strip()[-1] not in ")}"):
            raise UnhandledCwlError(f"Leading or trailing characters in field with parameter reference: {arg}")

    return cwl


REMOVE_REQUIREMENTS = {
    "DockerRequirement", "SoftwareRequirement", "ShellCommandRequirement",
}


ALL_REQUIREMENTS = REMOVE_REQUIREMENTS | {
    "InlineJavascriptRequirement", "SchemaDefRequirement", "InitialWorkDirRequirement", "EnvVarRequirement",
    "ResourceRequirement", "SubworkflowFeatureRequirement", "ScatterFeatureRequirement",
    "MultipleInputFeatureRequirement", "StepInputExpressionRequirement",
}


def filter_requirements(requirements: Sequence[Mapping[str, Any]], kind="requirement") -> List:
    filtered = []
    for r in requirements:
        if r["class"] not in REMOVE_REQUIREMENTS:
            if r["class"] not in ALL_REQUIREMENTS:
                print(f">>> Warning: unknown {kind} (not removing) {r['class']!r} <<<")
            filtered.append(r)
    return filtered


def type_contains(typ, needle):
    """(haystack, needle) -> bool

    NOTE: this is unlikely to work if the type you're searching for is
    anything but one of the simple CWL types (int, File, ...).
    """
    if typ == needle:
        return True
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
