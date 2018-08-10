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


import pytest

from cwl_dummy import type_contains


CWL_TYPES = ["Any", "null", "boolean", "int", "long", "float", "double", "string", "File", "Directory"]


def test_type_contains():
    assert type_contains("int[]", {"type": "array", "items": "int"})
    assert type_contains("int?", "null")
    assert type_contains({"type": "array", "items": "int?"}, "null")


@pytest.mark.parametrize("typ", CWL_TYPES)
def test_type_contains_param(typ):
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
