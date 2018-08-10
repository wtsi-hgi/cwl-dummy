# cwl-dummy

Generates CWL files that do nothing.

## Usage

Install via Pip:

```
python3.6 -m venv venv
source venv/bin/activate
pip install git+https://github.com/wtsi-hgi/cwl-dummy
```

then run `cwl-dummy -h` for usage instructions.

## Limitations

cwl-dummy does not use schema-salad to preprocess documents, so it's not
able to cope with documents that make use of more complex schema-salad
features (`$graph`, `$import`, `$include`, relative identifiers, etc.).

## License

Copyright (C) 2018 Genome Research Ltd.

cwl-dummy is distributed under the terms of the MIT license, a copy of
which can be found in the file `LICENSE`.

cwl-dummy is based on [cwl-upgrader][], which is used under the terms of
the Apache license, version 2.0; a copy of the Apache license is
available in the file `LICENSE.APACHE`.

[cwl-upgrader]: https://github.com/common-workflow-language/cwl-upgrader
