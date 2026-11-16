from pilayer.engine.rules import find_matches

ALL = {"phone": True, "idcard": True, "bankcard": True, "email": True,
       "privkey": True, "ip": True, "token": True}

FAKE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5YWJjZGVmZ2hpamtsbW5vcHFy\n"
    "c3R1dnd4eXowMTIzNDU2Nzg5QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def kinds(text):
    return [m.kind for m in find_matches(text, ALL, [])]


def test_privkey_block_single_placeholder():
    assert kinds("登录用：\n" + FAKE_KEY) == ["PRIVKEY"]


def test_privkey_mask_restore_roundtrip(masker):
    r = masker.mask(FAKE_KEY)
    assert r.count == 1
    assert "BEGIN" not in r.text
    assert masker.restore(r.text).text == FAKE_KEY


def test_ipv4():
    assert kinds("服务器 192.0.2.10 上线") == ["IP"]


def test_invalid_ipv4_rejected():
    assert kinds("地址 999.1.1.1") == []


def test_version_string_not_ip():
    assert kinds("版本 1.2.3 发布") == []


def test_api_tokens():
    assert kinds("key=sk-abcdefghijklmnopqrstuvwxyz123456") == ["TOKEN"]
    assert kinds("ghp_" + "a" * 36) == ["TOKEN"]
    assert kinds("AKIA" + "A" * 16) == ["TOKEN"]


def test_jwt():
    jwt = "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12
    assert kinds(jwt) == ["TOKEN"]


def test_privkey_priority_over_inner_matches():
    # 私钥块内部可能偶然出现数字串/邮箱样文本，整块优先
    text = FAKE_KEY.replace("b3BlbnNzaC1rZXktdjE", "13800138000")
    assert kinds(text) == ["PRIVKEY"]