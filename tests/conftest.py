import pytest
from tadris.db.connection import connect
from tadris.db.migrate import migrate

@pytest.fixture
def conn():
    c = connect(":memory:")
    migrate(c)
    yield c
    c.close()