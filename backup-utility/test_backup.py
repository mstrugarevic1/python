import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("backup.py")


class BackupTest(unittest.TestCase):
    def test_set_backup_and_restore_preserve_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, archives, restored = root / "source", root / "archives", root / "restored"
            source.mkdir()
            file = source / "private.txt"
            file.write_text("secret")
            file.chmod(0o640)
            (source / "ignored.log").write_text("ignore")
            (source / "link").symlink_to("private.txt")
            env = {**os.environ, "BACKUP_UTILITY_CONFIG": str(root / "sets.json")}

            subprocess.run([sys.executable, SCRIPT, "set", "server", source, archives,
                            "--exclude", "*.log"], check=True, env=env)
            subprocess.run([sys.executable, SCRIPT, "backup", "server"], check=True, env=env)
            archive = next(archives.glob("*.tar.gz"))
            subprocess.run([sys.executable, SCRIPT, "restore", archive, restored], check=True, env=env)

            self.assertEqual((restored / "private.txt").read_text(), "secret")
            self.assertEqual(stat.S_IMODE((restored / "private.txt").stat().st_mode), 0o640)
            self.assertTrue((restored / "link").is_symlink())
            self.assertFalse((restored / "ignored.log").exists())

    def test_restore_rejects_nonempty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "backup.tar.gz"
            with tarfile.open(archive, "w:gz"):
                pass
            destination = root / "restore"
            destination.mkdir()
            (destination / "keep").touch()
            result = subprocess.run([sys.executable, SCRIPT, "restore", archive, destination],
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not empty", result.stderr)


if __name__ == "__main__":
    unittest.main()
