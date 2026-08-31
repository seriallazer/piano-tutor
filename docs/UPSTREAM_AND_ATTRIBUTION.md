# Upstream and attribution

## Project lineage

Piano Tutor is an independently maintained fork of
[Graditone](https://github.com/graditone/graditone). This checkout was based on
Graditone commit
[`c3425d49e28e32e857587b006197a29763aa7950`](https://github.com/graditone/graditone/commit/c3425d49e28e32e857587b006197a29763aa7950),
tagged `v0.1.235` in the local checkout.

Graditone provides the original Rust/WASM score model and layout engine, React
renderer, playback system, plugin architecture, PWA shell, score catalogue,
tests, specifications, and most of the repository's documentation. Its MIT
license and 2026 Graditone copyright notice are preserved verbatim in
[`../LICENSE`](../LICENSE).

## Work specific to this fork

The fork-specific work begins after base commit `c3425d4`. At the time this
document was written, that work was represented by the commit whose subject is
`feat: add MIDI piano practice and score intake`. It includes:

- an 88-key multi-touch practice piano and practice-engine integration;
- Web MIDI plumbing and a macOS Core MIDI hardware diagnostic;
- a learner-focused landing/practice experience and Piano Tutor branding;
- local sheet-music intake and verification tools, including deterministic
  MusicXML event checks and tests; and
- a private-catalogue integration point. No private catalogue content is part
  of the intended public release.

This is a statement about the Git boundary, not a claim that every line after
the fork point was written without tooling or assistance. `git diff c3425d4..main`
is the authoritative review surface.

## License obligations

The Graditone software is MIT-licensed. Any copy or substantial portion must
retain the copyright and permission notice in `LICENSE`.

Bundled third-party assets may have separate terms. The Salamander Grand Piano
samples are credited in
[`../frontend/public/audio/salamander/CREDITS.txt`](../frontend/public/audio/salamander/CREDITS.txt)
as CC BY 3.0. Font and score licensing is not established by the top-level MIT
license alone and should be checked before redistribution.

Two inherited items need explicit resolution before describing the whole asset
bundle as cleared for public redistribution:

1. `scores/star-sky-two-steps-from-hell.mxl` represents a contemporary
   copyrighted composition. Repository planning notes describe it as all
   rights reserved, while the implemented UI credit labels it CC BY-SA. Do not
   rely on the latter without primary-source evidence from the rights holders.
2. `frontend/public/audio/violin/` contains samples without an adjacent source
   or license record in this checkout.

These two issues came from the upstream tree and are not fork-specific work,
but a fork still redistributes them. Remove them from the distributable tree or
obtain and document the required permissions before a public release.
