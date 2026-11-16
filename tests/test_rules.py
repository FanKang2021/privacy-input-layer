from pilayer.engine.rules import find_matches

ALL = {"phone": True, "idcard": True, "bankcard": True, "email": True}


def kinds(text, keywords=None):
    return [m.kind for m in find_matches(text, ALL, keywords or [])]


def test_phone():
    assert kinds("打给我 13800138000 谢谢") == ["PHONE"]


def test_phone_not_part_of_longer_number():
    assert kinds("订单号 201380013800012345") == []


def test_idcard_valid():
    assert kinds("身份证 11010519491231002X") == ["IDCARD"]


def test_idcard_bad_checksum_rejected():
    assert kinds("身份证 110105194912310021") == []


def test_bankcard_luhn():
    assert kinds("卡号 4111111111111111") == ["BANKCARD"]


def test_bankcard_bad_luhn_rejected():
    assert kinds("卡号 4111111111111112") == []


def test_email():
    assert kinds("发到 zhangsan@example.com 吧") == ["EMAIL"]


def test_keyword():
    assert kinds("张三的电话", ["张三"]) == ["KEYWORD"]


def test_idcard_priority_over_bankcard():
    # 18 位身份证同时落在银行卡 16-19 位区间，应判为身份证
    assert kinds("11010519491231002X") == ["IDCARD"]


def test_mixed():
    text = "张三 13800138000 11010519491231002X 4111111111111111 a@b.co"
    assert kinds(text, ["张三"]) == ["KEYWORD", "PHONE", "IDCARD", "BANKCARD", "EMAIL"]


def test_disabled_rule():
    matches = find_matches("13800138000", {"phone": False}, [])
    assert matches == []