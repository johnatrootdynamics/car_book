import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_APP_HOST = "carbook.root-dynamics.com"
CANONICAL_APP_ORIGIN = "https://www.trackops.tech"


class ProductionUrlTests(unittest.TestCase):
    def test_retired_application_host_is_not_in_runtime_sources(self):
        source_roots = [
            ROOT / ".env.example",
            ROOT / "README.md",
            ROOT / "deploy",
            ROOT / "mobile",
            ROOT / "racetrack",
        ]
        matches = []
        for source_root in source_roots:
            files = [source_root] if source_root.is_file() else source_root.rglob("*")
            for path in files:
                if not path.is_file() or any(
                    part in {"node_modules", ".expo", "build", "ios", "__pycache__"}
                    for part in path.parts
                ):
                    continue
                try:
                    contents = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if LEGACY_APP_HOST in contents:
                    matches.append(str(path.relative_to(ROOT)))
        self.assertEqual(matches, [])

    def test_mobile_and_server_share_the_canonical_origin(self):
        self.assertIn(
            CANONICAL_APP_ORIGIN,
            (ROOT / "mobile" / "lib" / "config.ts").read_text(encoding="utf-8"),
        )
        self.assertIn(
            CANONICAL_APP_ORIGIN,
            (ROOT / "racetrack" / "__init__.py").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
