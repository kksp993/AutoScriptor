from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.webui.security import (
    grant_credential_unlock,
    revoke_credential_unlock,
    validate_credential_unlock,
)


class TestCredentialUnlock(unittest.TestCase):
    def test_grant_validate_revoke(self):
        token = grant_credential_unlock()
        self.assertTrue(validate_credential_unlock(token))
        revoke_credential_unlock(token)
        self.assertFalse(validate_credential_unlock(token))

    def test_empty_token_invalid(self):
        self.assertFalse(validate_credential_unlock(None))
        self.assertFalse(validate_credential_unlock(""))


if __name__ == "__main__":
    unittest.main()
