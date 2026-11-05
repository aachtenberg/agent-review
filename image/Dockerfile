# The container the review agent runs in: OpenCode and git, nothing fetched
# at run time. Built and pushed by .github/workflows/image.yml; review.yml
# pins the result by digest.
#
# node:22-bookworm-slim, pinned by digest.
FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da
# Links the GHCR package to this repo.
LABEL org.opencontainers.image.source=https://github.com/aachtenberg/agent-review

# git for git-ro. apt checks the Debian archive signatures.
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory /work

# ripgrep, for OpenCode's grep, glob and list tools. Without rg on PATH,
# OpenCode downloads this same release from GitHub on every run, unverified.
ADD --checksum=sha256:1c9297be4a084eea7ecaedf93eb03d058d6faae29bbc57ecdaf5063921491599 \
    https://github.com/BurntSushi/ripgrep/releases/download/15.1.0/ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz /tmp/rg.tar.gz
RUN tar -xzf /tmp/rg.tar.gz -C /usr/local/bin --strip-components=1 ripgrep-15.1.0-x86_64-unknown-linux-musl/rg \
 && rm /tmp/rg.tar.gz \
 && rg --version

# OpenCode's standalone binary. npm ci checks it against the integrity hash in
# package-lock.json. The baseline x64 build runs with or without AVX2, so the
# image works on any x64 runner, not only on CPUs like the one that built it.
COPY package.json package-lock.json /opt/opencode/
RUN cd /opt/opencode \
 && npm ci --ignore-scripts --no-audit --no-fund --loglevel=error \
 && ln -s /opt/opencode/node_modules/opencode-linux-x64-baseline/bin/opencode /usr/local/bin/opencode \
 && opencode --version
