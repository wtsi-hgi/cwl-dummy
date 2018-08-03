# Based on https://github.com/common-workflow-language/cwl-upgrader/blob/master/cwlupgrader/main.py


import argparse
import shlex
import sys
import textwrap
import traceback
# noinspection PyUnresolvedReferences
from typing import MutableMapping, MutableSequence, Any, overload, TypeVar, List, Dict

import cwlgen.command_line_tool
import cwlgen.import_cwl
import ruamel.yaml


T = TypeVar("T")


class UnhandledCwlError(Exception):
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", help="a Workflow or CommandLineTool to mock")
    args = parser.parse_args()
    try:
        mock_file(args.filename)
    except UnhandledCwlError as e:
        display_error(e, args.filename)


def display_error(err: UnhandledCwlError, filename: str):
    print("=" * 32 + " Unhandled CWL " + "=" * 32)
    print(f"  Could not handle CWL file at {filename}")
    print(f"  You must create the .dummy file yourself, or the workflow will not run.")
    print(f"  Reason for failure:")
    print(f"    {err!s}")
    while hasattr(err, "__cause__") and err.__cause__ is not None:
        err = err.__cause__
        print("  because:")
        if isinstance(err, UnhandledCwlError):
            print(f"    {err!s}")
        else:
            print(f"    {traceback.format_exception_only(type(err), err)}")
    if hasattr(err, "__context__") and err.__context__ is not None:
        err = err.__context__
        print(f"  caused by the following exception:")
        print(textwrap.indent("".join(filter(None, traceback.format_exception(type(err), err, err.__traceback__))).rstrip(), "    "))
    print("=" * 79)


def mock_file(filename: str) -> None:
    """Read a file, mock it, and write the mocked version."""
    print(f"Mocking file {filename}")

    # TODO: improve cwlgen so we don't have to read the file twice
    with open(filename, "r") as f:
        cwl_dict = ruamel.yaml.safe_load(f)

    if cwl_dict["cwlVersion"] != "v1.0":
        raise Exception("can't process CWL versions other than v1.0")

    if cwl_dict["class"] == "CommandLineTool":
        cwl = cwlgen.import_cwl.CWLToolParser().import_cwl(filename)
        cwl = mock_command_line_tool(cwl)
    elif cwl_dict["class"] == "Workflow":
        cwl = cwlgen.import_cwl.CWLWorkflowParser(expand_run=False).import_cwl(filename)
        cwl = mock_workflow(cwl)
    elif cwl_dict["class"] == "ExpressionTool":
        # This is super ugly, since ExpressionTools can't be represented with cwlgen
        print("ignoring ExpressionTool")
        return
    else:
        raise UnhandledCwlError(f"Cannot handle CWL with class {cwl_dict['class']}")

    cwl.export(filename + ".dummy")

    print(f"Wrote mocked file to {filename}.dummy")


def mock_workflow(cwl: cwlgen.Workflow) -> cwlgen.Workflow:
    for step in cwl.steps:
        if isinstance(step["run"], str):
            # got a filename -- recurse into it
            # NB: CWL workflows are not allowed to refer to themselves
            # (even indirectly), so we don't need to keep track of which
            # files we've seen.
            try:
                mock_file(step["run"])
            except UnhandledCwlError as e:
                # The other steps need to be checked, so don't raise.
                display_error(e, step["run"])
            # We don't want to accidentally run a live file, so update
            # the filename even if it couldn't be processed.
            step["run"] += ".dummy"
        else:
            # probably a nested CWL document
            # FIXME: cwlgen may or may not be able to handle these
            try:
                step["run"] = mock_document(step["run"])
            except UnhandledCwlError as e:
                raise UnhandledCwlError(f"Unhandled workflow step with id {step['id']}") from e

    return cwl


def mock_command_line_tool(cwl: cwlgen.command_line_tool.CommandLineTool) -> cwlgen.command_line_tool.CommandLineTool:
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
                output_files.extend(secondary_files)
            if "glob" in output_binding:
                output_files.append(output_binding["glob"])
        elif typ == "Directory":
            if "glob" in output_binding:
                output_dirs.append(output_binding["glob"])
        else:
            pass  # ignore non-files

    # FIXME: the quoting situation here is very broken
    # If you use an expression like this in your CWL:
    #
    #   $(inputs['abc']])
    #
    # then shlex.quote will transform it into this:
    #
    #   '$(inputs['"'"'abc'"'"']])'
    #
    # so the CWL runner won't expand it and everything will break.
    args = ["sleep 10"]
    if output_dirs:
        args.append("mkdir -p " + " ".join(map(attempt_to_quote, output_dirs)))
    if output_files:
        args.append("touch " + " ".join(map(attempt_to_quote, output_files)))
    cwl["arguments"] = ["; ".join(args)]

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
    # Relevant code:
    # https://github.com/common-workflow-language/schema_salad/blob/b27b64a26bb1940c5bff92c979f9e29d32d7e6a9/schema_salad/python_codegen_support.py#L259
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
