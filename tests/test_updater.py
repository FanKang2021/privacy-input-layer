from pilayer.updater import newer


def test_newer():
    assert newer("v0.4.11", "0.4.10")
    assert newer("0.5.0", "0.4.99")
    assert not newer("v0.4.10", "0.4.10")
    assert not newer("0.4.9", "0.4.10")
