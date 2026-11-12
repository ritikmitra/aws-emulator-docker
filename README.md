# aws-emulator-docker

[![Build and test](https://github.com/ritikmitra/aws-emulator-docker/actions/workflows/build.yml/badge.svg)](https://github.com/ritikmitra/aws-emulator-docker/actions/workflows/build.yml)

Community-built Docker images for [AWS Emulator](https://github.com/aws/aws-emulator): pinned to a specific version, verified against AWS's package-signing key, and built for both ARM64 and AMD64 from one Dockerfile.

> [!IMPORTANT]
> This is a community project. It is not affiliated with, endorsed by, or supported by Amazon Web Services. AWS Emulator is built and published by AWS; this repository only packages AWS's official release into a container image. If the emulator itself behaves differently from AWS, report it [upstream](https://github.com/aws/aws-emulator/issues).

## Why this project exists

AWS doesn't publish a prebuilt container image for AWS Emulator. On macOS and Windows, the [official instructions](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-docker.html) have every user build their own image from a short Dockerfile. That works, but it leaves some gaps:

| | Official Dockerfile | This project |
|---|---|---|
| Version | Always `latest` | Pinned to a specific version |
| Package signature | Not checked | Verified with GnuPG; the build fails if it's bad |
| Signing key | Not checked | Fingerprint pinned; the build fails if it changes |
| ARM64 and AMD64 | Edit the file by hand | Picked automatically |
| Prebuilt image | No, every user builds it | Planned (see [Roadmap](#roadmap)) |

## Supported platforms

| Architecture | Typical machines |
|---|---|
| ARM64 (`aarch64`) | Apple silicon Macs, AWS Graviton, other Arm servers |
| AMD64 (`x86_64`) | Intel and AMD PCs, most CI runners |

The same Dockerfile builds both, and Docker picks the right one for your machine automatically. Prebuilt images are on the [roadmap](#roadmap); for now, you build the image yourself with one command.

## Quick start

### Prerequisites

- Docker (Docker Desktop on macOS and Windows)
- AWS CLI version 2, for the examples below

### 1. Build the image

```bash
git clone https://github.com/ritikmitra/aws-emulator-docker.git
cd aws-emulator-docker
docker build -t aws-emulator-local -f docker/Dockerfile docker/
```

Docker picks the right architecture for your machine automatically.

### 2. Start the emulator

Create the folder that the container shares with your machine. The emulator writes its credentials and certificate there, so your tools can read them.

macOS and Linux:

```bash
mkdir -p ~/.aws/emulator

docker run --rm --memory=2g --memory-swap=2g \
  -p 127.0.0.1:9297:9297 \
  -e HOME="$HOME" -v "$HOME/.aws/emulator:$HOME/.aws/emulator" \
  aws-emulator-local -p 9297
```

On Linux, also add `--user "$(id -u):$(id -g)"` after `docker run` so the files the emulator creates belong to you.

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.aws\emulator"

docker run --rm --memory=2g --memory-swap=2g -p "127.0.0.1:9297:9297" `
  -v "$env:USERPROFILE\.aws\emulator:/home/emulator/.aws/emulator" `
  aws-emulator-local -p 9297
```

> [!WARNING]
> Always publish the port as `-p 127.0.0.1:9297:9297`, never `-p 9297:9297`. The short form exposes the emulator to your whole network, so other computers could reach it.

The emulator runs in the foreground. Press Ctrl+C to stop it. It keeps all resources in memory, so they're deleted when it stops.

### 3. Point the AWS CLI at the emulator

Use a separate terminal for this. These variables redirect the AWS CLI away from real AWS, so keep them out of the shell you use for real work.

```bash
export AWS_ENDPOINT_URL=https://127.0.0.1:9297
export AWS_SHARED_CREDENTIALS_FILE=~/.aws/emulator/9297/emulator_credentials
export AWS_CONFIG_FILE=~/.aws/emulator/9297/config
export AWS_CA_BUNDLE=~/.aws/emulator/9297/ca.pem
export AWS_EC2_METADATA_DISABLED=true
export AWS_DISABLE_HOST_PREFIX_INJECTION=true
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1

# Make sure no real AWS credentials are active
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE
```

For Windows and for SDKs other than the AWS CLI, see AWS's guide [Pointing your AWS SDK at AWS Emulator](https://docs.aws.amazon.com/emulator/latest/userguide/point-sdk-to-emulator.html).

### 4. Check that you're talking to the emulator

```bash
aws sts get-caller-identity
```

The account must be `000000000000`. If you see your own account ID, your requests are going to real AWS. Stop and check the variables above.

### 5. Try it

```bash
aws s3api create-bucket --bucket my-test-bucket
echo "hello emulator" > hello.txt
aws s3 cp hello.txt s3://my-test-bucket/hello.txt
aws s3 cp s3://my-test-bucket/hello.txt -
```

The last command prints `hello emulator`.

To check that the emulator is up, use its health route. It returns `ok`:

```bash
curl --cacert ~/.aws/emulator/9297/ca.pem https://127.0.0.1:9297/__admin/health
```

## Telemetry

By default, AWS Emulator sends anonymous usage and error data to AWS. According to AWS, this never includes the contents of your requests or responses, your code, your credentials, or personal data. For details, see [Telemetry in AWS Emulator](https://docs.aws.amazon.com/emulator/latest/userguide/telemetry.html). This image doesn't change AWS's default.

To turn telemetry off, either add `--telemetry off` at the end of the `docker run` command, or pass `-e EMULATOR_TELEMETRY=off` to `docker run`. Setting `EMULATOR_TELEMETRY` in your own shell doesn't reach the container.

## Building a specific version

AWS lists the published versions in [`versions.json`](https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/versions.json). An entry such as `1.0.322.1` splits into `VERSION=1.0.322` and `RELEASE=1`:

```bash
docker build \
  --build-arg VERSION=1.0.322 \
  --build-arg RELEASE=1 \
  -t aws-emulator-local:1.0.322.1 \
  -f docker/Dockerfile docker/
```

AWS publishes security fixes only in the latest release, so prefer the newest version unless you need to pin an older one.

### Build arguments

| Argument | Default | Description |
|---|---|---|
| `VERSION` | `1.0.322` | Emulator version: the first three parts of a `versions.json` entry |
| `RELEASE` | `1` | Package release: the last part of a `versions.json` entry |
| `SIGNER_FINGERPRINT` | `98BCF336A3BE53B734E967C52E5BF49BD940F624` | Expected fingerprint of AWS's package-signing key |
| `TARGETARCH` | Set by Docker | `amd64` or `arm64` |

## How the image is built and verified

Every step must succeed, or the build stops:

1. **Map the architecture.** Docker's name is translated to AWS's package name (`amd64` → `x86_64`, `arm64` → `aarch64`). Any other architecture fails immediately.
2. **Check the signing key.** The build downloads AWS's public key and compares its fingerprint with `SIGNER_FINGERPRINT`, the value AWS publishes in its [Linux install guide](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html). This runs before the large package download, so a wrong key fails within seconds.
3. **Download the pinned package** and its detached `.sig` signature file.
4. **Verify the signature** with GnuPG, trusting only the pinned key.
5. **Install the package**, then delete the downloaded files and keyring.
6. **Run as an unprivileged user** (UID 1000), listening on `0.0.0.0` inside the container so that Docker can forward the port.

## Things to know

- **For testing only.** As AWS advises, don't use the emulator for production workloads or to test security, such as IAM policies. See [Security in AWS Emulator](https://docs.aws.amazon.com/emulator/latest/userguide/security.html).
- **State lives in memory.** Stopping the container deletes all emulated resources. Restart it for a clean slate.
- **One account, one Region.** The emulator acts as account `000000000000`. Use one Region per emulator.
- **Memory.** The emulator uses about 160 MiB when idle and grows as you create resources. The `--memory=2g` option caps it; if it goes over, the container stops with exit code 137.
- **Image size.** The package installs to roughly 900 MB, so expect an image of about 1 GB.

## Roadmap

- [x] Pinned, signature-verified image
- [x] Signing-key fingerprint pinning
- [x] One Dockerfile for ARM64 and AMD64
- [ ] Automated smoke tests (S3, DynamoDB)
- [ ] GitHub Actions builds for both architectures
- [ ] Multi-architecture images published to GitHub Container Registry
- [ ] Daily detection of new AWS Emulator releases
- [ ] Docker Compose example

## Licensing

- The files in this repository are licensed under the terms in [LICENSE](LICENSE).
- AWS Emulator is licensed by AWS under CC0 1.0 Universal, except the code in its `vendor/` directory, which is under the Apache License 2.0. The image keeps the license and notice files that AWS ships with the package, including `/opt/aws-emulator/THIRD_PARTY_LICENSES`.
- AWS and Amazon Web Services are trademarks of Amazon.com, Inc. or its affiliates. They're used here only to describe what this project packages.

## Contributing and support

- **Problems with this image or Dockerfile:** open an issue in this repository.
- **The emulator behaves differently from AWS:** report it in the [upstream repository](https://github.com/aws/aws-emulator/issues). It doesn't accept pull requests.
- **Security issues in the emulator itself:** don't open a public issue. Report them to AWS as described in [Security in AWS Emulator](https://docs.aws.amazon.com/emulator/latest/userguide/security.html).

## Related links

- [AWS Emulator on GitHub](https://github.com/aws/aws-emulator)
- [AWS Emulator User Guide](https://docs.aws.amazon.com/emulator/latest/userguide/what-is-service.html)
- [Releases and fidelity scores](https://github.com/aws/aws-emulator/releases)
- [Published versions (`versions.json`)](https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/versions.json)