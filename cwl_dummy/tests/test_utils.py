import pytest

from cwl_dummy.utils import strip_references


@pytest.mark.parametrize("a, b", [
    ("a", "a"),
    ("$(inputs)", ""),
    ("$(inputs.foo)", ""),
    ("$(inputs['foo'])", ""),
    ("$(inputs[\"foo\"])", ""),
    ("$(inputs.foo['bar'][\"baz\"][0])", ""),
    ("$()", "$()"),
    ("$(no spaces allowed)", "$(no spaces allowed)"),
    ("$(except['in quotes'])", "")
])
def test_strip_references(a, b):
    assert strip_references(a) == b
