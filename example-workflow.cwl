cwlVersion: v1.0
class: Workflow
inputs:
  filename:
    type: string
steps:
  step_one:
    run: example-tool.cwl
    in:
      tool_input: filename
    out: [tool_output]
outputs:
  file:
    type: File
    outputSource: step_one/tool_output
