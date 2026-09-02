# Dinner Rush

## Objective

Build a complete, polished, browser-native 3D kitchen coordination game called **Dinner Rush** with Three.js. Its shared gameplay reference is the familiar station-to-station ingredient preparation, cooking, plating, order timing, mistakes, and score loop of **Overcooked**. Use original names, chefs, kitchen layout, recipes, food models, sounds, icons, and interface assets.

The player controls two chefs in one compact restaurant kitchen, switching between them at any time. During a four-minute service, prepare and deliver five valid dishes drawn from three recipe types. Victory requires five accepted deliveries before closing, with each chef making a visible preparation or transport contribution to at least one accepted dish. The run is lost when time expires with fewer than five deliveries; burned food and wrong dishes cost time or score but remain recoverable.

## Operational completion contract

Implement the game described below. The Goal is complete when `npm run build` succeeds and emits `dist/`.

Do not write or run browser automation, automated runtime checks, autopilots, or full playthroughs. Runtime behavior, responsiveness, feature completeness, balance, polish, and game feel are evaluated after submission. Report only the build you actually ran.

## Target game systems

- An angled 3D kitchen camera that keeps stations and both chefs legible, with collision-aware chef movement and a clear active-chef indicator.
- Instant switching between two independently positioned chefs. Each chef carries at most one ingredient, tool, plate, or prepared item, and each must contribute a real preparation or transport action to at least one dish that is eventually accepted.
- Ingredient bins, at least two counters, chopping board, pot or pan station, plate stack, serving window, trash, and sink. Interaction targets must be highlighted or otherwise unambiguous.
- Three recipes with visible step requirements:
  - garden salad: chopped tomato plus chopped leaf on a plate;
  - mushroom soup: three chopped mushrooms cooked in a pot and plated;
  - skillet plate: chopped fish plus chopped potato cooked together and plated.
- Timed chopping, timed cooking with progress, a burn window after cooking completes, disposal of ruined food, dirty plates returned after delivery, and timed washing before reuse.
- A deterministic order queue showing recipe, remaining patience, next orders, accepted delivery, rejected dish, tip or score, combo, and service time.
- Five-delivery victory, time-expired loss, pause, restart, and no unrecoverable state caused by depleted plates or discarded ingredients.
- Desktop keyboard controls plus usable phone movement, switch-chef, pickup/place/interact, and action controls.
- Minimum input convention: forward movement must respond to either W or Up Arrow on desktop, and the primary phone movement surface must occupy the lower-left control region.

## Execution checkpoints

1. Establish kitchen layout, camera, two chefs, collision, switching, responsive input, carrying, counters, and station targeting.
2. Implement ingredient supply, chopping, cooking, burning, plating, washing, trash, and all three recipe state machines.
3. Implement deterministic orders, patience, validation, delivery, scoring, combo, timer, five-order victory, failure, and restart.
4. Improve food and station readability, animations, progress feedback, kitchen lighting, effects, urgency cues, and UI hierarchy.
5. After the final relevant change, run `npm run build` once. If it succeeds and emits `dist/`, stop; post-submission evaluation handles runtime behavior.

## Quality targets

- The player can see what each chef carries and the state of every active cooking station.
- Wrong, incomplete, raw, or burned dishes are rejected consistently with a clear reason.
- Cooking progress and burn danger remain readable while controlling the other chef.
- All required orders remain achievable within the supplied stations, ingredients, plates, and time balance.
- Touch controls do not obscure active stations, order cards, or the controlled chef.

- At 1440 x 900 and 390 x 844, horizontal page overflow stays within 2 CSS pixels and the runtime emits no uncaught page exception or `console.error` output.

## Runtime inspection contract

Expose `window.__WEB3DGAMEBENCH__` as a JSON-serializable object updated during play. It must contain:

The object must be complete and schema-valid from the first rendered frame, reflect the initial playable state before start, and return to that state after restart except for `restartCount`. During play, `R` must restart immediately, and phone mode must expose a visible restart control whose text, `aria-label`, or title identifies it as Restart; either path increments `restartCount` exactly once.

- `phase`: `ready`, `playing`, `paused`, `won`, or `lost`;
- `score`: finite number;
- `activeChef`: `0` or `1`;
- `chefs`: two `{ x, y, z, carrying }` objects with finite positions and string or `null` carrying values;
- `serviceSecondsRemaining`: non-negative finite number;
- `ordersDelivered`: integer from 0 to 5;
- `chef0AcceptedContributions`: integer from 0 to 5, counting accepted dishes to which chef 0 contributed a real preparation or transport action, at most once per dish;
- `chef1AcceptedContributions`: integer from 0 to 5, with the same rule for chef 1;
- `activeOrders`: non-negative integer;
- `dirtyPlates`: non-negative integer;
- `burnedItems`: non-negative integer;
- `combo`: non-negative integer;
- `seed`: `104729`;
- `restartCount`: non-negative integer.

You may add fields. Do not expose evaluator-only shortcuts or callable functions.

## Constraints and final evidence

Use the supplied Three.js dependency and starter toolchain. Make no runtime network requests and fetch no packages or external assets. Keep all code and generated assets in the workspace. The static production build must be emitted to `dist/` by `npm run build`. Before completion, report only the production build result; do not create additional automated verification.
