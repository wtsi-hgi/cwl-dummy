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
from typing import Any, List, Mapping, MutableMapping, MutableSequence, Set, cast

import ruamel.yaml.scalarstring

from cwl_dummy.utils import (
    UnhandledCwlError, coloured_diff, ensure_list, ensure_sequence_form, error, format_error, mapping_to_sequence,
    strip_references, warn,
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
    parser.add_argument(
        "filenames", nargs="+", metavar="filename", type=pathlib.Path, help="a Workflow or CommandLineTool to mock"
    )
    parser.add_argument("-f", "--force", action="store_true", help="write processed files even if they already exist")
    # Avoid overwriting files that have been fixed by hand.
    parser.add_argument("--force-broken", action="store_true", help="write unhandled files even if they already exist")
    parser.add_argument("--diff", action="store_true", help="show a diff for each updated file")
    # The typeshed signature for parse_args currently does not account
    # for custom namespaces, so we have to cast to get typechecking.
    args = cast(Arguments, parser.parse_args(namespace=Arguments()))
    for filename in args.filenames:
        try:
            mock_file(filename)
        except UnhandledCwlError as e:
            error(e, filename)


mocked_files: Set[pathlib.Path] = set()


def mock_file(filename: pathlib.Path) -> None:
    """Mock a CWL file, given a path."""
    global mocked_files
    if filename in mocked_files:
        print(f"Already mocked file this run, ignoring: {filename}")
        return
    mocked_files.add(filename)
    print(f"Mocking file: {filename}")

    with open(filename, "r") as f:
        cwl = ruamel.yaml.round_trip_load(f)

    if cwl.get("cwlVersion") != "v1.0":
        raise UnhandledCwlError("Can't process CWL versions other than v1.0")

    comment = exception = None
    try:
        cwl = mock_document(cwl, filename.parent)
    except UnhandledCwlError as e:
        # Since most things mutate `cwl` in-place, we can carry on and
        # write the file to make it easier to fix it by hand.
        comment = textwrap.indent(format_error(e, filename), "# ")
        # Python automatically deletes `e` at the end of the block, so
        # it has to be assigned to another name to access it later.
        exception = e

    outfile = filename.with_suffix(filename.suffix + ".dummy")
    if args.diff and outfile.exists():
        with open(outfile, "r") as f:
            existing_lines = f.readlines()
        # Get the new CWL as a list of strings.
        new_file = io.StringIO()
        if comment:
            new_file.write(comment + "\n")
        ruamel.yaml.round_trip_dump(cwl, new_file, default_flow_style=False)
        new_file.seek(0)
        new_lines = new_file.readlines()
        existing_time = datetime.datetime.fromtimestamp(os.path.getmtime(outfile), tz=datetime.timezone.utc)
        new_time = datetime.datetime.now(tz=datetime.timezone.utc)
        # If there's no difference, this won't print anything.
        print("".join(coloured_diff(difflib.unified_diff(
            existing_lines,
            new_lines,
            fromfile=f"existing/{outfile}",
            tofile=f"modified/{outfile}",
            fromfiledate=existing_time.isoformat(),
            tofiledate=new_time.isoformat(timespec="microseconds" if existing_time.microsecond else "seconds"),
        ))), end="")
    if comment and outfile.exists() and not args.force_broken:
        print(f"Not writing file because it already exists and could not be processed: {outfile}")
    elif outfile.exists() and not args.force:
        print(f"Not writing file because it already exists: {outfile}")
    else:
        with open(outfile, "w") as f:
            if comment:
                f.write(comment + "\n")
            ruamel.yaml.round_trip_dump(cwl, f, default_flow_style=False)
        print(f"Wrote mocked file: {outfile}")

    if exception:
        raise exception


def mock_document(cwl, directory: pathlib.Path):
    """Mock a CWL document represented as a Python object."""
    assert isinstance(cwl, MutableMapping)  # Guard against implicit $graph
    cls = cwl.get("class")
    if cls == "Workflow":
        cwl = mock_workflow(cwl, directory)
    elif cls == "CommandLineTool":
        cwl = mock_command_line_tool(cwl)
    elif cls == "ExpressionTool":
        warn("ignoring ExpressionTool")
    else:
        raise UnhandledCwlError(f"Unknown document class {cls!r}")
    return cwl


def mock_workflow(cwl, directory: pathlib.Path):
    """Mock a CWL workflow represented as a Python object."""
    assert cwl["class"] == "Workflow"
    assert all(x in cwl for x in {"inputs", "outputs", "steps"})
    for x in {"requirements", "hints"} & cwl.keys():
        cwl[x] = rewrite_requirements(ensure_sequence_form(cwl[x], key_key="class"))

    cwl["steps"] = ensure_sequence_form(cwl["steps"])
    for step in cwl["steps"]:
        if isinstance(step["run"], str):
            # got a filename -- recurse into it
            # NB: CWL workflows are not allowed to refer to themselves
            # (even indirectly), so we don't need to keep track of which
            # files we've seen.
            filename = directory / pathlib.Path(step["run"])
            try:
                mock_file(filename)
            except UnhandledCwlError as e:
                error(e, filename)
            step["run"] += ".dummy"
        else:
            # probably a nested CWL document
            try:
                step["run"] = mock_document(step["run"], directory)
            except UnhandledCwlError as e:
                raise UnhandledCwlError(f"Unhandled workflow step with id {step['id']}") from e

    return cwl


def mock_command_line_tool(cwl):
    """Mock a CWL command line tool represented as a Python object."""
    assert cwl["class"] == "CommandLineTool"
    assert all(x in cwl for x in {"inputs", "outputs"})
    for x in {"requirements", "hints"} & cwl.keys():
        cwl[x] = rewrite_requirements(ensure_sequence_form(cwl[x], key_key="class"))
    return cwl


def rewrite_requirements(requirements: MutableSequence[Mapping[str, Any]]) -> MutableSequence:
    for i, r in enumerate(requirements):
        if r["class"] == "DockerRequirement":
            requirements[i] = {
                "class": "DockerRequirement",
                "dockerPull": "mercury/cwl-scheduler-tests",
            }
    return requirements


def type_contains(typ, needle):
    """(haystack, needle) -> bool

    NOTE: this is unlikely to work if the type you're searching for is
    anything but one of the simple CWL types (int, File, ...).

    To maximise the chances of correctly detecting the type, use the
    fully-expanded form of the type, i.e.
    `{"type": "array", "items": "int"}` rather than `"int[]"`.
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
