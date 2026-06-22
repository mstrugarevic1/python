import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backup import copy_stable


class CopyStableTest(unittest.TestCase):
    def test_retries_a_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.write_text("first")
            real_copy = __import__("shutil").copy2
            calls = 0

            def changing_copy(src: Path, dst: Path) -> None:
                nonlocal calls
                real_copy(src, dst)
                calls += 1
                if calls == 1:
                    src.write_text("second version")

            with patch("backup.shutil.copy2", changing_copy):
                copy_stable(source, target)

            self.assertEqual((calls, target.read_text()), (2, "second version"))


if __name__ == "__main__":
    unittest.main()
