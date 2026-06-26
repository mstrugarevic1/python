from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from log_analyzer import analyze


class AnalyzeAccessLogsTest(unittest.TestCase):
    def test_common_and_combined_access_logs(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "access.log"
            log_path.write_text(
                "\n".join(
                    [
                        '192.0.2.1 - - [26/Jun/2026:12:00:00 +0200] "GET / HTTP/1.1" 200 10',
                        '192.0.2.2 - - [26/Jun/2026:12:00:01 +0200] "POST /login HTTP/1.1" 404 - "-" "curl/8.0"',
                        "not an access log",
                    ]
                ),
                encoding="utf-8",
            )

            total, parsed, bytes_served, statuses, paths, ips, methods, problem_paths = analyze(log_path)

        self.assertEqual(total, 3)
        self.assertEqual(parsed, 2)
        self.assertEqual(bytes_served, 10)
        self.assertEqual(statuses["200"], 1)
        self.assertEqual(statuses["404"], 1)
        self.assertEqual(paths["/login"], 1)
        self.assertEqual(ips["192.0.2.1"], 1)
        self.assertEqual(methods["POST"], 1)
        self.assertEqual(problem_paths["404 /login"], 1)


if __name__ == "__main__":
    unittest.main()
