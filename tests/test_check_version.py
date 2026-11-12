"""Unit tests for scripts/check_version.py.

Run from the project root:
    python3 -m unittest discover -s tests -v

No network or Docker needed: fake versions.json files and Dockerfiles
are written to a temporary folder for each test.
"""

from check_version import (  # pyright: ignore[reportMissingImports]
    fetch_lts_versions,
    newest_version,
    parse_version,
    read_dockerfile_version,
    update_docker_version,
)
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make scripts/ importable, so the tests can use our functions.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# A small Dockerfile shaped like the real one, used by the Dockerfile tests.
SAMPLE_DOCKERFILE = """\
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal

ARG TARGETARCH
ARG VERSION=1.0.322
ARG RELEASE=1
ARG SIGNER_FINGERPRINT=98BCF336A3BE53B734E967C52E5BF49BD940F624

RUN echo "build steps"

USER 1000
ENTRYPOINT ["aws-emulator", "-b", "0.0.0.0"]
"""


def entry(version: str, stream="LTS", product="aws-emulator") -> dict[str, str]:
    """One entry of versions.json, with LTS and aws-emulator as defaults."""
    return {"productId": product, "releaseStream": stream, "version": version}


class TempDirTestCase(unittest.TestCase):
    """Gives each test a fresh temporary folder in self.dir, deleted afterwards."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestParseVersion(unittest.TestCase):
    def test_valid_version(self):
        self.assertEqual(parse_version("1.0.336.1"), (1, 0, 336, 1))

    def test_rejects_letters(self):
        with self.assertRaises(ValueError):
            parse_version("1.0.abc.1")

    def test_rejects_three_parts(self):
        with self.assertRaises(ValueError):
            parse_version("1.0.336")

    def test_rejects_empty_string(self):
        with self.assertRaises(ValueError):
            parse_version("")


class TestNewestVersion(unittest.TestCase):
    def test_numeric_not_text_comparison(self):
        # The trap: as text, "1.0.99.1" > "1.0.322.1".
        self.assertEqual(newest_version(
            ["1.0.99.1", "1.0.322.1"]), "1.0.322.1")

    def test_unsorted_list(self):
        self.assertEqual(
            newest_version(["1.0.336.1", "1.0.191.1", "1.0.322.1"]),
            "1.0.336.1",
        )


class TestFetchLtsVersions(TempDirTestCase):
    def write_json(self, data) -> str:
        path = self.dir / "versions.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path.as_uri()  # e.g. file:///tmp/abc/versions.json

    def test_keeps_only_aws_emulator_lts(self):
        url = self.write_json(
            {
                "versions": [
                    entry("1.0.322.1"),
                    entry("1.0.400.1", stream="PREVIEW"),
                    entry("1.0.500.1", product="something-else"),
                    entry("1.0.336.1"),
                ]
            }
        )
        self.assertEqual(fetch_lts_versions(url), ["1.0.322.1", "1.0.336.1"])

    def test_missing_versions_key_fails_loudly(self):
        url = self.write_json({"releases": []})
        with self.assertRaises(TypeError):
            fetch_lts_versions(url)

    def test_top_level_list_fails_loudly(self):
        url = self.write_json([])
        with self.assertRaises(TypeError):
            fetch_lts_versions(url)

    def test_no_matching_entries_fails_loudly(self):
        # A renamed stream must not look like "no new version".
        url = self.write_json({"versions": [entry("1.0.336.1", stream="lts")]})
        with self.assertRaises(ValueError):
            fetch_lts_versions(url)


class TestReadDockerfileVersion(TempDirTestCase):
    def write_dockerfile(self, text: str) -> Path:
        path = self.dir / "Dockerfile"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_version_and_release(self):
        path = self.write_dockerfile(SAMPLE_DOCKERFILE)
        self.assertEqual(read_dockerfile_version(path), "1.0.322.1")

    def test_missing_release_fails(self):
        path = self.write_dockerfile(
            SAMPLE_DOCKERFILE.replace("ARG RELEASE=1\n", ""))
        with self.assertRaises(ValueError):
            read_dockerfile_version(path)

    def test_duplicate_version_fails(self):
        path = self.write_dockerfile(SAMPLE_DOCKERFILE + "ARG VERSION=9.9.9\n")
        with self.assertRaises(ValueError):
            read_dockerfile_version(path)

    def test_missing_file_fails(self):
        with self.assertRaises(RuntimeError):
            read_dockerfile_version(self.dir / "does-not-exist")


class TestUpdateDockerVersion(TempDirTestCase):
    def write_dockerfile(self, text: str) -> Path:
        path = self.dir / "Dockerfile"
        path.write_text(text, encoding="utf-8")
        return path

    def test_updates_version_and_release(self):
        path = self.write_dockerfile(SAMPLE_DOCKERFILE)
        update_docker_version(path, "1.0.336", "2")
        self.assertEqual(read_dockerfile_version(path), "1.0.336.2")

    def test_leaves_other_lines_unchanged(self):
        path = self.write_dockerfile(SAMPLE_DOCKERFILE)
        update_docker_version(path, "1.0.336", "1")

        before = SAMPLE_DOCKERFILE.splitlines()
        after = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(after), len(before))

        changed = [(b, a) for b, a in zip(before, after) if b != a]
        self.assertEqual(
            changed, [("ARG VERSION=1.0.322", "ARG VERSION=1.0.336")])

    def test_same_version_changes_nothing(self):
        # Idempotence: running the update twice gives the same result as once.
        path = self.write_dockerfile(SAMPLE_DOCKERFILE)
        update_docker_version(path, "1.0.322", "1")
        self.assertEqual(path.read_text(encoding="utf-8"), SAMPLE_DOCKERFILE)

    def test_duplicate_version_fails_and_leaves_file_unchanged(self):
        original = SAMPLE_DOCKERFILE + "ARG VERSION=9.9.9\n"
        path = self.write_dockerfile(original)
        with self.assertRaises(ValueError):
            update_docker_version(path, "1.0.336", "1")
        # "Check before writing": a failed update must not touch the file.
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_rejects_invalid_version(self):
        path = self.write_dockerfile(SAMPLE_DOCKERFILE)
        with self.assertRaises(ValueError):
            update_docker_version(
                path, "1.0.336.1", "1"
            )  # 4 parts, but VERSION takes 3
        self.assertEqual(path.read_text(encoding="utf-8"), SAMPLE_DOCKERFILE)

    def test_rejects_invalid_release(self):
        path = self.write_dockerfile(SAMPLE_DOCKERFILE)
        with self.assertRaises(ValueError):
            update_docker_version(path, "1.0.336", "one")
        self.assertEqual(path.read_text(encoding="utf-8"), SAMPLE_DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
