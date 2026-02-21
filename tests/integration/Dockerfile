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
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
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
