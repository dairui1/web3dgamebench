FROM reconbench-candidate:0.147.0

ARG CODEX_VERSION=0.149.1
ARG CLAUDE_VERSION=2.1.243
ARG PI_VERSION=0.84.2

USER root
RUN npm install -g \
      @openai/codex@${CODEX_VERSION} \
      @anthropic-ai/claude-code@${CLAUDE_VERSION} \
      @earendil-works/pi-coding-agent@${PI_VERSION} \
    && npm cache clean --force

RUN useradd --create-home --uid 10001 candidate

ENV CI=1

USER candidate
WORKDIR /workspace
