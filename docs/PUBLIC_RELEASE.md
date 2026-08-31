# Public release checklist

This repository is **not safe to push publicly in its current history**. The
latest local commit contains a scanned sheet-music PDF, a derived family score,
and provenance containing absolute local filesystem paths. A deletion commit
would leave all of those blobs downloadable from older commits.

## Preserve useful history while removing private blobs

History filtering changes the IDs of affected commits; there is no way to keep
an affected commit's SHA and also remove one of its blobs. It does preserve the
commit graph, messages, authors, and timestamps. Because the private paths were
introduced only after the Graditone base commit, a path-limited rewrite can
leave the upstream commits and their IDs unchanged while rewriting the
fork-specific commit and any descendants.

The checkout is currently shallow and has a linked worktree containing
untracked score-conversion material. Preserve that worktree and complete the
upstream history before filtering or publishing:

```bash
git status --short --branch
git remote rename origin upstream
git fetch --unshallow upstream main --tags
git merge-base --is-ancestor c3425d49e28e32e857587b006197a29763aa7950 main
git rev-parse --is-shallow-repository
```

The final command must print `false`. Commit the public-preparation changes,
make a private backup, and create a fresh single-branch release clone. Running
the rewrite in that clone avoids modifying the private linked worktree:

```bash
git clone --no-local --single-branch --branch main \
  /absolute/path/to/piano_tutor /absolute/path/to/piano_tutor-public
cd /absolute/path/to/piano_tutor-public
```

Install `git-filter-repo`, then filter only the branch intended for
publication in the release clone:

```bash
git filter-repo --force --refs main --invert-paths \
  --path docs/pdfs/piano-songs.pdf \
  --path scores/family/ \
  --path frontend/src/data/familyScores.json \
  --path frontend/src/data/familyScores.private.json
```

Do not use `git push --mirror` or `git push --all`: the source checkout also has
local branches and untracked linked-worktree content that are not part of the
portfolio release. The fresh clone's `origin` initially points to the private
local source path; rename or remove it, add the new personal repository as
`origin`, and push `main` explicitly.

## Verify the rewritten branch

```bash
python3 scripts/check_public_tree.py --history
git log main -- docs/pdfs/piano-songs.pdf scores/family frontend/src/data/familyScores.json frontend/src/data/familyScores.private.json
git rev-list --objects main | rg '(^| )(docs/pdfs/|scores/family/|frontend/src/data/familyScores(\.private)?\.json$)'
git diff --check
```

The last two history checks must produce no private paths. A normal push sends
reachable objects, not local unreachable garbage, but do not distribute or
archive the `.git` directory from the pre-filter checkout.

Also decide whether the public commit should retain the author's personal email
address. If not, rewrite the fork-specific commit once—during the same planned
rewrite—to use the GitHub account's verified `@users.noreply.github.com`
address. That changes only the affected fork commit and is compatible with
preserving its original author and committer timestamps.

## Remaining release gates

- Resolve or exclude the inherited `Star Sky` score and unlicensed violin
  samples described in [`UPSTREAM_AND_ATTRIBUTION.md`](UPSTREAM_AND_ATTRIBUTION.md).
- Run `python3 scripts/check_public_tree.py --history` after filtering.
- Run `python3 -m unittest discover -s tests/score_intake`.
- From `frontend/`, run `npm ci`, `npm run typecheck`, `npm run lint`,
  `npm test -- --run`, and `npm run build`.
- From `backend/`, run `cargo fmt -- --check`, `cargo clippy -- -D warnings`,
  and `cargo test --all-features`.
- Create a GitHub fork when possible so GitHub displays the Graditone lineage;
  otherwise retain the prominent fork disclosure and upstream link in the
  README.
