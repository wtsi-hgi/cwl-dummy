# Based on https://github.com/common-workflow-language/cwl-upgrader/blob/master/cwlupgrader/main.py


import argparse
import shlex
import sys
import textwrap
import traceback
# noinspection PyUnresolvedReferences
from typing import MutableMapping, MutableSequence, Any, overload, TypeVar, List

import ruamel.yaml


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
    # Convert mapping form to sequence form
    if isinstance(cwl["steps"], MutableMapping):
        cwl["steps"] = [{"id": k, **v} for k, v in cwl["steps"].items()]
    assert isinstance(cwl["steps"], MutableSequence)

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


def mock_command_line_tool(cwl):
    assert cwl["class"] == "CommandLineTool"
    assert all(x in cwl for x in {"inputs", "outputs"})
    if any(x in cwl for x in {"stdin", "stdout", "stderr"}):
        raise UnhandledCwlError("Cannot handle stdin/stdout/stderr references automatically")
    cwl["baseCommand"] = ["sh", "-c"]

    # Convert mapping form:
    #
    #   inputs:
    #     my_input:
    #       doc: "an input"
    #
    # to sequence form:
    #
    #   inputs:
    #   - id: my_input
    #     doc: "an input"
    #
    # TODO: this can fail if the value is just a type
    # i.e. in the form: map<CommandOutputParameter.id, CommandOutputParameter.type>
    # which is allowed by the CWL spec
    #
    #   outputs:
    #     my_output: string
    if isinstance(cwl["inputs"], MutableMapping):
        cwl["inputs"] = [{"id": k, **v} for k, v in cwl["inputs"].items()]
    assert isinstance(cwl["inputs"], MutableSequence)
    if isinstance(cwl["outputs"], MutableMapping):
        cwl["outputs"] = [{"id": k, **v} for k, v in cwl["outputs"].items()]
    assert isinstance(cwl["outputs"], MutableSequence)

    for input in cwl["inputs"]:
        if "inputBinding" in input:
            input.pop("inputBinding")

    output_files = []
    output_dirs = []
    for output in cwl["outputs"]:
        typ = normalise_type(output["type"])
        try:
            output_binding = output["outputBinding"]
        except KeyError:
            raise UnhandledCwlError("CommandLineTool has output without outputBinding (does it use cwl.output.json?)") from None
        if typ == "File" or isinstance(type, dict) and typ.get("items") == "File":
            if "secondaryFiles" in output:
                secondary_files = ensure_list(output["secondaryFiles"])
                # FIXME: this is not correct!
                output_files.extend(secondary_files)
            if "glob" in output_binding:
                # FIXME: globs can contain glob characters
                output_files.append(output_binding["glob"])
        elif typ == "Directory":
            if "glob" in output_binding:
                # FIXME: globs can contain glob characters
                output_dirs.append(output_binding["glob"])
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


def attempt_to_quote(s: str) -> str:
    """Try to quote a string for use in `arguments`."""
    if "$(" not in s and "${" not in s:
        # easy case -- it definitely doesn't contain any expression
        return shlex.quote(s)
    # TODO
    return "'" + s + "'"


def normalise_type(frag):
    # TODO: this is very bad, we should use schema-salad for this
    # (which would also take care of $import/$include)
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
    return frag  # TODO: handle stuff like enums


@overload
def ensure_list(x: List[T]) -> List[T]: ...


def ensure_list(x: T) -> List[T]:
    if isinstance(x, list):
        return x
    return [x]


if __name__ == "__main__":
    sys.exit(main())
