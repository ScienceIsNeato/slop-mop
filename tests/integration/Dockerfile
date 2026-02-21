FROM python:3.12-slim

# System dependencies required by slop-mop gates:
#   git      — clone fixture repo + branch checkout inside the container
#   Node.js  — jscpd (source-duplication gate)
#   jscpd    — installed globally via npm
#
# slop-mop itself is NOT pre-installed here. Installing it is part of what
# the integration tests are testing (phase A). The host source tree is
# bind-mounted at /slopmop-src at runtime.
#
# The bucket-o-slop fixture repo is cloned from GitHub at runtime — no
# local checkout is required on the host machine.
# Pin the NodeSource GPG key fingerprint and verify before trusting the repo.
# This avoids piping an unverified remote script to bash.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g jscpd \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Git identity so checkout / status operations don't complain
RUN git config --global user.email "test@slop-mop.dev" \
    && git config --global user.name "slop-mop-tests" \
    && git config --global init.defaultBranch main

WORKDIR /test-repo

CMD ["bash"]
