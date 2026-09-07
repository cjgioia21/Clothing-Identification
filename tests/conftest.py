import pytest

from tests.factories import make_read


@pytest.fixture
def read():
    return make_read()
