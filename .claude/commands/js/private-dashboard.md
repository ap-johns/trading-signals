---
description: Build the private dashboard with Trading 212 holdings (local only, never committed)
---

Generate the **private** dashboard — the normal OTT/DCA dashboard plus a Trading 212
holdings overlay (dry-powder balance, open P/L, `HELD` badges on owned names, and a
"favoured, not held" vs "already held" split in the DCA Buy Levels table).

This is for local use only. The output goes to a git-ignored file and must never be
committed — it contains the user's account balances and positions.

Steps:

1. Build and open it:

   ```
   cd alerts && python3 dashboard.py --private
   ```

   This writes `local-dashboard.html` at the repo root (git-ignored) and requires
   `T212_KEY_ID` and `T212_API_SECRET` in `alerts/.env`. Then open it:

   ```
   open local-dashboard.html
   ```

2. If the run prints `no Trading 212 data`, the API credentials are missing or the
   request failed — check `alerts/.env` has both `T212_KEY_ID` and `T212_API_SECRET`
   (Basic auth: `base64(KEY_ID:SECRET)` against the live endpoint). Do **not** print
   the secret; just confirm the keys are present.

3. Safety guardrails — never violate these:
   - Do **not** write account data into `docs/` (that's the public GitHub Pages site).
   - Do **not** commit `local-dashboard.html` or paste balances/positions into chat
     beyond a brief confirmation the build succeeded.
   - The public `python3 dashboard.py` (no `--private`) stays untouched and account-free.

4. Report briefly: confirm the private dashboard was built and opened, and note the
   free-cash / dry-powder figure only if the user asks — keep account details minimal.
