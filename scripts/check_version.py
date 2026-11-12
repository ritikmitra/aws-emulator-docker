import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path

URL = "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/versions.json"
REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"


def fetch_lts_versions(url: str) -> list[str]:
    """Download versions.json and return the LTS version strings, e.g. ["1.0.322.1", ...]."""
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)

    # Validate before using: fail loudly if AWS changes the format.
    if not isinstance(data, dict) or not isinstance(data.get("versions"), list):
        raise TypeError(
            f"unexpected format in {url}: expected an object with a 'versions' list"
        )

    lts_versions = [
        entry["version"]
        for entry in data["versions"]
        if entry.get("productId") == "aws-emulator"
        and entry.get("releaseStream") == "LTS"
    ]

    # An empty result is as suspicious as a missing key.
    if not lts_versions:
        raise ValueError(f"no aws-emulator LTS versions found in {url}")

    return lts_versions


def parse_version(version: str) -> tuple[int, ...]:
    splitted = version.split(".")

    if len(splitted) != 4:
        raise ValueError(f"invalid version {version!r}: expected 4 dot-separated parts")

    if not all((part.isascii() and part.isdigit()) for part in splitted):
        raise ValueError("Version components must contain only non-negative integers")

    return tuple(int(part) for part in splitted)


def newest_version(versions: list[str]) -> str:
    return max(versions, key=parse_version)


def read_dockerfile_version(path: Path) -> str:
    version = None
    release = None

    pattern = re.compile(r"^ARG\s+(VERSION|RELEASE)=(\S+)\s*$")

    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                match = pattern.match(line.strip())

                if not match:
                    continue

                key, value = match.groups()

                if key == "VERSION":
                    if version is not None:
                        raise ValueError("Duplicate VERSION declaration")
                    version = value

                elif key == "RELEASE":
                    if release is not None:
                        raise ValueError("Duplicate RELEASE declaration")
                    release = value

    except OSError as exc:
        raise RuntimeError(f"Unable to read Dockerfile: {path}") from exc

    if version is None or release is None:
        raise ValueError("VERSION or RELEASE is missing from Dockerfile")

    return f"{version}.{release}"


def update_docker_version(path: Path, version: str, release: str) -> None:

    # 1. Validate version
    if not re.fullmatch(r"\d+(?:\.\d+){2}", version):
        raise ValueError("Invalid version. Expected format: X.Y.Z")

    # 2. Validate release
    if not re.fullmatch(r"\d+", release):
        raise ValueError("Release must be a non-negative integer")

    # 3. Compile regex
    pattern = re.compile(r"^(\s*ARG\s+)(VERSION|RELEASE)=[^\r\n]*$", re.MULTILINE)

    try:
        # 4. Read Dockerfile
        content = path.read_text(encoding="utf-8")

        # 5. Define replacements
        replacements = {"VERSION": version, "RELEASE": release}

        # 6. Track declarations
        counts = {"VERSION": 0, "RELEASE": 0}

        # 7. Replace matching ARG declarations
        def replace_arg(match: re.Match[str]) -> str:
            prefix, key = match.groups()
            counts[key] += 1
            return f"{prefix}{key}={replacements[key]}"

        updated_content = pattern.sub(replace_arg, content)

        # 8. Verify exactly one declaration each
        for key, count in counts.items():
            if count != 1:
                raise ValueError(
                    f"Expected exactly one {key} declaration, found {count}"
                )

        # 9. Skip unnecessary writes
        if updated_content == content:
            return

        # 10. Write to temporary file and replace original
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temp_file:
            temp_file.write(updated_content)
            temp_path = Path(temp_file.name)

        try:
            os.chmod(temp_path, path.stat().st_mode)
            os.replace(temp_path, path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise

    except OSError as exc:
        raise RuntimeError(f"Unable to update Dockerfile: {path}") from exc


def main() -> None:
    try:
        current = read_dockerfile_version(DOCKERFILE)
        latest = newest_version(fetch_lts_versions(URL))

        current_parsed = parse_version(current)
        latest_parsed = parse_version(latest)

        print(f"Dockerfile: {current}")
        print(f"Newest:     {latest}")

        if latest_parsed > current_parsed:
            print("Update available")

            version, release = latest.rsplit(".", 1)

            update_docker_version(path=DOCKERFILE, version=version, release=release)

            print(f"Dockerfile updated to: {latest}")

        else:
            print("Up to date")

    except (ValueError, RuntimeError, OSError, TypeError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
