# Signal Drift

Build a complete, polished, browser-native 3D game called **Signal Drift** using Three.js.

The player pilots a compact courier craft through a storm-damaged relay field suspended above an endless cloud layer. Restore three relay gates in order, collect enough charge to keep the craft alive, avoid moving hazards, and cross the extraction ring to win.

## Required experience

- A first viewport that immediately establishes the title, setting, objective, and a clear way to begin.
- A coherent playable loop with steering, forward motion, collisions, charge management, ordered relay progress, victory, failure, and a fast restart.
- A legible spatial course rather than disconnected objects on an empty plane.
- Strong motion feedback: the craft and camera should communicate speed, turning, impact, danger, and success.
- A deliberate visual identity made from procedural geometry, materials, lighting, particles, and post-processing where useful.
- A compact HUD that shows charge, restored relays, and current objective without covering the playfield.
- Keyboard controls on desktop and usable pointer or touch controls on a 390 x 844 phone.
- Pause when the page loses visibility. Audio is optional and must begin only after user interaction.
- Frame-rate-independent motion, robust resize behavior, and no runtime network requests.

## Fairness and deployment constraints

- Use the supplied Three.js dependency and starter toolchain. Do not fetch packages, images, fonts, audio, models, or data from the network.
- The production build must be static and emitted by `npm run build` into `dist/`.
- Keep all game code and generated assets inside this workspace.
- Do not use production services, analytics, remote APIs, or account state.
- Do not embed model or harness names in the game.

## Runtime inspection contract

Expose `window.__AETHERPLAY__` as a JSON-serializable object updated during play. It must contain:

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: number;
- `player`: `{ x, y, z }` with finite numbers;
- `relaysRestored`: integer from 0 to 3;
- `charge`: finite number;
- `seed`: `94721`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or functions through this object.

Before finishing, build the game and play it in a browser at desktop and phone sizes. Leave the workspace in a production-buildable state.
