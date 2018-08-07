import pytest

from cwl_dummy import type_contains


CWL_TYPES = ["Any", "null", "boolean", "int", "long", "float", "double", "string", "File", "Directory"]


@pytest.mark.parametrize("typ", CWL_TYPES)
def test_type_contains(typ):
    assert type_contains(typ, typ)
    assert type_contains(f"{typ}?", typ)
    assert type_contains(f"{typ}[]", typ)
    assert type_contains(f"{typ}[]?", typ)
    assert not type_contains(typ, "a")
    assert not type_contains(f"{typ}?", "a")
    assert not type_contains(f"{typ}[]", "a")
    assert not type_contains(f"{typ}[]?", "a")
    assert type_contains({"type": "array", "items": typ}, typ)
    assert not type_contains({"type": "array", "items": typ}, "a")
