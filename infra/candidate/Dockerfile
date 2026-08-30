FROM node:24-bookworm

ARG CODEX_VERSION=0.149.1
ARG CLAUDE_VERSION=2.1.243
ARG PI_VERSION=0.84.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 git ca-certificates chromium \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g \
      @openai/codex@${CODEX_VERSION} \
      @anthropic-ai/claude-code@${CLAUDE_VERSION} \
      @earendil-works/pi-coding-agent@${PI_VERSION} \
    && npm cache clean --force

ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    CHROME_PATH=/usr/bin/chromium \
    CI=1

RUN useradd --create-home --uid 10001 candidate
USER candidate
WORKDIR /workspace
