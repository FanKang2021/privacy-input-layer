import sqlite3
import time

from pilayer.engine.rules import find_matches
from pilayer.engine.store import MappingStore

ALL = {"phone": True, "idcard": True, "bankcard": True, "email": True,
       "privkey": True, "ip": True, "token": True, "secret": True, "url": True,
       "internal_domains": []}


def kinds(text, **over):
    cfg = dict(ALL, **over)
    return [(m.kind, m.text) for m in find_matches(text, cfg, [])]


def test_h1_bare_secret_with_hash_and_space():
    assert kinds("pwd: ab#cd ef\nnext: 1") == [("SECRET", "ab#cd ef")]


def test_h2_uri_userinfo_password():
    assert kinds("postgres://u:secretpw@db.public.com/x") == [("SECRET", "secretpw")]


def test_h2_internal_uri_whole_url_wins():
    ms = kinds("postgres://u:p@10.0.0.5/x")
    assert ms == [("URL", "postgres://u:p@10.0.0.5/x")]


def test_m2_pgp_block():
    pgp = "-----BEGIN PGP PRIVATE KEY BLOCK-----\nabc\n-----END PGP PRIVATE KEY BLOCK-----"
    assert kinds(pgp) == [("PRIVKEY", pgp)]


def test_m2_stripe_underscore_and_google():
    assert kinds("sk_live_" + "a" * 24)[0][0] == "TOKEN"
    assert kinds("AIza" + "b" * 35)[0][0] == "TOKEN"


def test_m2_bearer_opaque():
    assert kinds("Authorization: Bearer abcDEF1234567890xyz") == [("SECRET", "abcDEF1234567890xyz")]


def test_m2_ipv6():
    assert kinds("addr 2001:0db8:85a3:0000:0000:8a2e:0370:7334") == [("IP", "2001:0db8:85a3:0000:0000:8a2e:0370:7334")]
    assert kinds("loop ::1") == [("IP", "::1")]


def test_m2_entropy_opt_in():
    tok = "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lz"
    assert kinds(tok) == []
    assert kinds(tok, entropy=True) == [("ENTROPY", tok)]


def test_h3_ciphertext_at_rest(tmp_path):
    p = tmp_path / "m.db"
    s = MappingStore(p)
    ph = s.get_or_create("SECRET", "plain-secret-value")
    s.close()
    raw = sqlite3.connect(str(p)).execute(
        "SELECT original FROM mappings WHERE placeholder=?", (ph,)
    ).fetchone()[0]
    assert isinstance(raw, bytes)
    assert b"plain-secret-value" not in raw
    s2 = MappingStore(p)
    assert s2.lookup(ph) == "plain-secret-value"
    s2.close()


def test_h3_plaintext_migration(tmp_path):
    p = tmp_path / "old.db"
    db = sqlite3.connect(str(p))
    db.executescript(
        """
        CREATE TABLE mappings(placeholder TEXT PRIMARY KEY, kind TEXT, original TEXT,
                              created_at REAL, last_used REAL);
        CREATE TABLE counters(kind TEXT PRIMARY KEY, value INTEGER);
        INSERT INTO mappings VALUES ('[SECRET_1]','SECRET','legacy-plain',1,1);
        """
    )
    db.commit()
    db.close()
    s = MappingStore(p)
    assert s.lookup("[SECRET_1]") == "legacy-plain"
    raw = sqlite3.connect(str(p)).execute("SELECT original FROM mappings").fetchone()[0]
    assert isinstance(raw, bytes)
    s.close()


def test_m3_purge_expired(tmp_path):
    s = MappingStore(tmp_path / "m.db")
    ph = s.get_or_create("SECRET", "old-secret")
    with s._lock:
        s._db.execute("UPDATE mappings SET created_at=?", (time.time() - 40 * 86400,))
        s._db.commit()
    assert s.purge_expired(30) == 1
    assert s.lookup(ph) is None
    s.close()