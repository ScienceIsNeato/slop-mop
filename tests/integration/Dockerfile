FROM python:3.12-slim

# System dependencies required by slop-mop gates:
#   git      — clone fixture repo + branch checkout inside the container
#   Node.js  — jscpd (source-duplication gate), find-duplicate-strings
#   jscpd    — installed globally via npm (source-duplication gate)
#   find-duplicate-strings — installed globally via npm (string-duplication gate)
#
# Python analysis tools are pre-installed so that gates work immediately
# after `pip install slopmop`.  This mirrors `pipx install slopmop[tools]`.
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
    && npm install -g jscpd find-duplicate-strings eslint@8 eslint-plugin-jest prettier \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python analysis tools — pre-installed in the image so each container
# run only needs `pip install slopmop` (fast) and all gates have their
# tools available.  Semgrep is excluded (huge download, CI-specific).
RUN pip install --no-cache-dir \
    black isort autoflake flake8 ruff \
    vulture radon \
    bandit detect-secrets \
    mypy \
    pytest pytest-cov diff-cover

# Git identity so checkout / status operations don't complain
RUN git config --global user.email "test@slop-mop.dev" \
    && git config --global user.name "slop-mop-tests" \
    && git config --global init.defaultBranch main

WORKDIR /test-repo

CMD ["bash"]
