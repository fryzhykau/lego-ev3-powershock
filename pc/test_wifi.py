import hashlib
import unittest

import ev3_brick


class SsidTest(unittest.TestCase):
    def test_plain_name_unchanged(self):
        self.assertEqual(ev3_brick._wpa_bytes("HomeNetwork"), b"HomeNetwork")

    def test_hex_escapes_become_bytes(self):
        # wpa_cli shows "Café" as Caf\xc3\xa9
        self.assertEqual(ev3_brick._wpa_bytes(r"Caf\xc3\xa9"), "Café".encode("utf-8"))

    def test_quote_backslash_and_controls(self):
        self.assertEqual(ev3_brick._wpa_bytes(r'a\"b\\c\td'), b'a"b\\c\td')

    def test_broken_escape_kept_as_text(self):
        self.assertEqual(ev3_brick._wpa_bytes(r"x\xZ1"), b"x\\xZ1")

    def test_key_uses_real_bytes(self):
        # same key as `wpa_passphrase Café password1`
        raw = ev3_brick._wpa_bytes(r"Caf\xc3\xa9")
        key = hashlib.pbkdf2_hmac("sha1", b"password1", raw, 4096, 32).hex()
        self.assertEqual(key, hashlib.pbkdf2_hmac("sha1", b"password1", "Café".encode(), 4096, 32).hex())


if __name__ == "__main__":
    unittest.main()
