---
description: Regenerate the public dashboard, commit and push (handles the CI rebase and merges generated files)
---

Rebuild `docs/index.html` with live data and publish it to GitHub Pages. CI commits
its own daily build at 17:00 UTC, so the push usually needs a rebase over commits that
touch the same generated files.

Steps:

1. Pull first, then build:

   ```
   git pull -q --rebase
   python3 alerts/dashboard.py
   ```

   Check the output for `Error:` rows in `docs/index.html` (`grep -o 'Error: [^<]*'`).
   A transient yfinance failure drops a ticker from every table; if one appears,
   rebuild once more before committing.

2. Commit and push:

   ```
   git add docs/index.html alerts/iv_history.json
   git commit -m "Update dashboard $(date +%Y-%m-%d)"
   git push
   ```

   Only those two generated files belong in this commit. Never add
   `local-dashboard.html`, `alerts/leap_positions.json` or `alerts/.env`.

3. If the push is rejected, CI has pushed meanwhile. Rebase and resolve the two
   generated files:
   - `docs/index.html`: keep ours — the fresh build (`git checkout --theirs` during a
     rebase refers to the commit being replayed, i.e. ours).
   - `alerts/iv_history.json`: **merge**, don't pick a side — load both versions
     (`git show :2:…` upstream, `git show :3:…` ours), union the per-ticker date maps,
     write the result. Losing CI's snapshots breaks the IV rank history.
   - `alerts/cycle_state.json` should not conflict (this commit doesn't touch it); if
     it does, keep upstream's.
   Then `git rebase --continue` and push again.

4. Report in one or two lines: the commit hash, and whether CI commits were rebased
   over. Mention that GitHub Pages takes a minute or two to serve the new build.
