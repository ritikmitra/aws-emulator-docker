FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal

ARG TARGETARCH
ARG VERSION=1.0.341
ARG RELEASE=1
ARG SIGNER_FINGERPRINT=98BCF336A3BE53B734E967C52E5BF49BD940F624

RUN cd /tmp && \
    case "$TARGETARCH" in \
        amd64) ARCH="x86_64" ;; \
        arm64) ARCH="aarch64" ;; \
        *) echo "ERROR: unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac && \
    PACKAGE="aws-emulator-${VERSION}-${RELEASE}-${ARCH}.rpm" && \
    BASE_URL="https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS" && \
    curl -fsSLo aws-publishing.asc https://downloads.aws.com/keys/gpg/current.asc && \
    ACTUAL=$(gpg --show-keys --with-colons aws-publishing.asc | grep '^fpr' | head -n1 | cut -d: -f10) && \
    if [ "$ACTUAL" != "$SIGNER_FINGERPRINT" ]; then echo "ERROR: key fingerprint mismatch. Expected $SIGNER_FINGERPRINT, got $ACTUAL" >&2; exit 1; fi && \
    curl -fsSLO "${BASE_URL}/${PACKAGE}" && \
    curl -fsSLO "${BASE_URL}/${PACKAGE}.sig" && \
    gpg -o aws-publishing.gpg --dearmor aws-publishing.asc && \
    gpg --no-default-keyring --keyring ./aws-publishing.gpg --verify "${PACKAGE}.sig" "${PACKAGE}" && \
    rpm -i "${PACKAGE}" && \
    rm -rf /tmp/aws-emulator-*.rpm* /tmp/aws-publishing.asc /tmp/aws-publishing.gpg /root/.gnupg

RUN mkdir -p /home/emulator && \
    chown -R 1000:1000 /home/emulator

USER 1000

ENV HOME=/home/emulator

EXPOSE 9297

ENTRYPOINT ["aws-emulator", "-b", "0.0.0.0"]