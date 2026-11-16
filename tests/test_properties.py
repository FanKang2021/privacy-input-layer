"""不变量性质测试：restore(mask(x)) == x 对任意文本成立。

本轮历史 bug 全为 span/overlap 类（截断、userinfo、优先级），
手工用例抓不住回归，用 hypothesis 守护引擎核心不变量。
"""

import tempfile

from hypothesis import given, settings, strategies as st

from pilayer.engine import MappingStore, TextMasker

SECRETS = [
    "13800138000",
    "11010519491231002X",
    "4111111111111111",
    "zhangsan@example.com",
    "10.0.0.5",
    "2001:db8::1",
    'pwd: "x#y z"',
    "bare_pwd: ab#cd ef",
    "postgres://u:p w@db.public.com/x",
    "postgres://u:p@10.0.0.5/x",
    "-----BEGIN OPENSSH PRIVATE KEY-----\nQUJD\n-----END OPENSSH PRIVATE KEY-----",
    "sk_live_" + "a" * 24,
    "http://nexus.{{ region }}.corp.example.cn:8081/x",
]

RULES = {
    "phone": True, "idcard": True, "bankcard": True, "email": True,
    "privkey": True, "ip": True, "token": True, "secret": True, "url": True,
    "internal_domains": ["corp.example.cn"],
}


@settings(max_examples=80, deadline=None)
@given(st.lists(st.sampled_from(SECRETS), max_size=4), st.text(max_size=30))
def test_restore_mask_roundtrip(secrets, prose):
    with tempfile.TemporaryDirectory() as d:
        store = MappingStore(d + "/m.db")
        masker = TextMasker(store, RULES, [])
        text = prose + " " + " ".join(secrets)
        masked = masker.mask(text)
        assert masker.restore(masked.text).text == text
        store.close()