cwlVersion: v1.0
class: CommandLineTool
requirements:
- class: InlineJavascriptRequirement
baseCommand: touch
inputs:
  tool_input:
    type: string
    inputBinding:
      position: 1
outputs:
  tool_output:
    type: File
    outputBinding:
      glob: $(inputs.tool_input)
  string_output:
    type: string
    outputBinding:
      outputEval: ${return "abc"}
