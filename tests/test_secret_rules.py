from pilayer.engine.rules import find_matches

ALL = {"phone": True, "idcard": True, "bankcard": True, "email": True,
       "privkey": True, "ip": True, "token": True, "secret": True, "url": True,
       "internal_domains": ["example.cn"]}

SAMPLE = '''postgresql_passwd: "FakePass123!"
redis_passwd: FakeBare456
powerdns_pwd: "{{ base_pwd }}"
nexus_admin_password: "zuFake-123"
empty_pwd: ""
zetyun_apt_repo_url: "http://10.0.0.5:8081/repository/zetyun/"
nexus_url: "http://nexus.{{ region }}.example.cn:8081/raw/x.tar.gz"
internal_host_url: "https://nexus.region.example.cn:8081/x"
public_url: "https://github.com/foo"
'''


def kinds(text):
    return [m.kind for m in find_matches(text, ALL, [])]


def test_secret_values_masked_keys_kept():
    ms = find_matches(SAMPLE, ALL, [])
    secrets = [m.text for m in ms if m.kind == "SECRET"]
    assert secrets == ["FakePass123!", "FakeBare456", "zuFake-123"]


def test_jinja_and_empty_skipped():
    assert "base_pwd" not in [m.text for m in find_matches(SAMPLE, ALL, [])]


def test_internal_urls():
    urls = [m.text for m in find_matches(SAMPLE, ALL, []) if m.kind == "URL"]
    assert len(urls) == 3
    assert "https://github.com/foo" not in urls


def test_secret_roundtrip(masker):
    r = masker.mask(SAMPLE)
    assert "FakePass123!" not in r.text
    assert "postgresql_passwd: " in r.text
    assert masker.restore(r.text).text == SAMPLE


def test_secret_priority_over_inner_ip():
    text = 'pwd: "10.0.0.5"'
    assert kinds(text) == ["SECRET"]


def test_templated_bare_domain():
    assert kinds('domain: "{{ region }}.corp.example.cn"') == ["URL"]


def test_configured_bare_domain():
    cfg = dict(ALL, internal_domains=["zetyun.cn"])
    ms = find_matches("k8s_zone: k8s.zetyun.cn\npub: github.com", cfg, [])
    assert [m.text for m in ms] == ["k8s.zetyun.cn"]