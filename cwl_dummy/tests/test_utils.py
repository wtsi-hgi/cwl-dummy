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
