FROM reconbench-candidate:0.147.0

ARG CODEX_VERSION=0.149.1
ARG CLAUDE_VERSION=2.1.258
ARG PI_VERSION=0.84.4

USER root
RUN npm install -g \
      @openai/codex@${CODEX_VERSION} \
      @anthropic-ai/claude-code@${CLAUDE_VERSION} \
      @earendil-works/pi-coding-agent@${PI_VERSION} \
    && npm cache clean --force

COPY pi-goal-benchmark/ /usr/lib/node_modules/@earendil-works/pi-coding-agent/web3dgamebench-goal/

COPY codex_goal_runner.py /usr/local/bin/web3dgamebench-codex-goal

RUN useradd --create-home --uid 10001 candidate

ENV CI=1

USER candidate
WORKDIR /workspace
