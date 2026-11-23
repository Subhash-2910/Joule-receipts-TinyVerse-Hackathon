import os
import tempfile
import unittest
from pathlib import Path


class TempDataTest(unittest.TestCase):
    """Each test gets its own data dir + database and an SLM URL that is guaranteed unreachable."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._env = {k: os.environ.get(k) for k in ("JOULE_DATA", "JOULE_DB", "JOULE_LLM_BASE_URL")}
        os.environ["JOULE_DATA"] = str(self.tmp)
        os.environ["JOULE_DB"] = str(self.tmp / "test.db")
        os.environ["JOULE_LLM_BASE_URL"] = "http://127.0.0.1:9"   # discard port: nothing listens
        from joule import db
        self.db_path = self.tmp / "test.db"
        self.conn = db.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()
