import pytest

from pilayer.engine import MappingStore, TextMasker


@pytest.fixture
def store(tmp_path):
    s = MappingStore(tmp_path / "mappings.db")
    yield s
    s.close()


@pytest.fixture
def masker(store):
    return TextMasker(
        store,
        {"phone": True, "idcard": True, "bankcard": True, "email": True},
        ["张三"],
    )