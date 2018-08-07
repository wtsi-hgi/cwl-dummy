import pytest

from cwl_dummy.utils import mapping_to_sequence


@pytest.mark.parametrize("mapping, expected", [
    ({
        "my_input": {"doc": "an input"},
        "another_input": {"doc": "another input"},
    }, [
        {"id": "my_input", "doc": "an input"},
        {"id": "another_input", "doc": "another input"},
    ]),

    ({}, []),

    ({
        "simple_input": "string",
        "input2": {"doc": "second input", "type": "int"},
    }, [
        {"id": "simple_input", "type": "string"},
        {"id": "input2", "doc": "second input", "type": "int"},
    ]),

    ({
        "my_input": "string",
        "another_input": "int",
    }, [
        {"id": "my_input", "type": "string"},
        {"id": "another_input", "type": "int"},
    ]),
])
def test_mapping_to_sequence(mapping, expected):
    actual = mapping_to_sequence(mapping)
    assert actual == expected
