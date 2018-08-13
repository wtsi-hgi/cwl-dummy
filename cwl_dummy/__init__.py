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
import shlex
import sys
import textwrap
from typing import Any, List, Mapping, MutableMapping, NamedTuple, Sequence, Set, cast

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
        cwl[x] = filter_requirements(ensure_sequence_form(cwl[x], key_key="class"), kind=x[:-1])
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


# This must not contain any shell metacharacters (including spaces).
MODE_SWITCH_FLAG = "cwl-dummy-mode-switch"


class CommandOutput(NamedTuple):
    glob: str
    secondary_files: List[str]


def mock_command_line_tool(cwl):
    """Mock a CWL command line tool represented as a Python object."""
    assert cwl["class"] == "CommandLineTool"
    assert all(x in cwl for x in {"inputs", "outputs"})
    for x in {"requirements", "hints"} & cwl.keys():
        cwl[x] = filter_requirements(ensure_sequence_form(cwl[x], key_key="class"), kind=x[:-1])
    if any(x in cwl for x in {"stdin", "stdout", "stderr"}):
        raise UnhandledCwlError("Cannot handle stdin/stdout/stderr references automatically")

    cwl["inputs"] = ensure_sequence_form(cwl["inputs"])
    cwl["outputs"] = ensure_sequence_form(cwl["outputs"])

    output_files: List[CommandOutput] = []
    output_dirs: List[CommandOutput] = []
    for output in ensure_sequence_form(cwl["outputs"]):
        try:
            output_binding = output["outputBinding"]
        except KeyError:
            raise UnhandledCwlError("CommandLineTool has output without outputBinding (does it use cwl.output.json?)")

        if output_binding.get("loadContents", False):
            warn("output file contents may be checked")

        if "glob" in output_binding:
            if not type_contains(output["type"], "File"):
                warn("glob found, but output type does not allow globs")
            globs = ensure_list(output_binding["glob"])
            for glob in (strip_references(g) for g in globs):
                if any(c in glob for c in "*?["):
                    # "may" because JS expressions aren't removed.
                    warn("glob may contain glob characters")
            # FIXME: globs can contain glob characters
            for i, glob in enumerate(globs):
                globs[i] = glob.replace("*", "s").replace("?", "q")
            secondary_files = ensure_list(output.get("secondaryFiles", []))
            if secondary_files and not type_contains(output["type"], "File"):
                warn("secondary files found, but output type does not allow secondary files")
            for glob in globs:
                command_output = CommandOutput(glob=glob, secondary_files=secondary_files)
                if type_contains(output["type"], "Directory"):
                    output_dirs.append(command_output)
                else:
                    output_files.append(command_output)

    file_cmds: List[str] = []
    for output in output_files:
        if any(s.startswith("^") for s in output.secondary_files):
            # Globs can be expressions, so we can't statically remove an
            # extension from them.
            raise UnhandledCwlError("secondary files with '^' cannot be handled automatically")
        if any("$(" in s or "${" in s for s in output.secondary_files):
            raise UnhandledCwlError("secondary file contains expression")
        extra_files = (f'"$arg"{shlex.quote(s)}' for s in output.secondary_files)
        file_cmds.append(f'touch -- {" ".join(extra_files)} "$arg"; shift')
    file_cmd_str: str = "\n".join(file_cmds)

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
    cwl["baseCommand"] = ["sh", "-c", ruamel.yaml.scalarstring.PreservedScalarString(textwrap.dedent(f"""\
    sleep 10
    while ! [ "$1" = {MODE_SWITCH_FLAG} ]; do
        shift
    done
    shift
    while ! [ "$1" = {MODE_SWITCH_FLAG} ]; do
        mkdir -p -- "$1"
        shift
    done
    shift
    {textwrap.indent(file_cmd_str, " " * 4).lstrip()}
    if ! [ "$1" = {MODE_SWITCH_FLAG} ]; then
        printf 'Extra file argument?\\n'
    fi
    """)), "cwl_dummy_runner"]  # This is $0
    output_dir_globs: List[str] = [o.glob for o in output_dirs]
    output_file_globs: List[str] = [o.glob for o in output_files]
    cwl["arguments"] = [MODE_SWITCH_FLAG, *output_dir_globs, MODE_SWITCH_FLAG, *output_file_globs, MODE_SWITCH_FLAG]

    for arg in output_dir_globs + output_file_globs:
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
    """Remove requirements that affect execution of a process.

    Unrecognised requirements are not removed.
    """
    filtered = []
    for r in requirements:
        if r["class"] not in REMOVE_REQUIREMENTS:
            if r["class"] not in ALL_REQUIREMENTS:
                warn(f"ignoring unknown {kind} {r['class']!r}")
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
