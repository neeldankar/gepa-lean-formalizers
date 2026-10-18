import importlib.util

from src.config import ROOT

spec = importlib.util.spec_from_file_location("secret_scan", ROOT / "scripts/secret_scan.py")
secret_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secret_scan)


def test_env_values_tolerate_indentation(tmp_path):
    env = tmp_path / ".env"
    env.write_text("   FAKE_KEY=abcdefgh12345678\n# comment\nSHORT=x\n")
    assert secret_scan.env_values(env) == ["abcdefgh12345678"]


def test_flags_env_value_without_printing_it():
    found = secret_scan.find_secrets("+key = 'abcdefgh12345678'\n", ["abcdefgh12345678"])
    assert found == ["line 1: value of an .env key"]
    assert "abcdefgh" not in found[0]


def test_flags_known_key_formats():
    planted = "+token = 'ghp_" + "a" * 36 + "'\n+other = 'sk-" + "b" * 30 + "'"
    assert len(secret_scan.find_secrets(planted, [])) == 2


def test_clean_text_passes():
    assert secret_scan.find_secrets("+def f(x):\n+    return x\n", ["abcdefgh12345678"]) == []
