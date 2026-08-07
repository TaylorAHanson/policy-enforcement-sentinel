# Captured policy tests

Everything else in this directory is ignored by git.

A capture is a resource document taken from a real scan — the exact JSON the
Databricks API returned, with the expectations recording what the policies did
to it at the time. It is named after a real catalog, schema, volume or job.

That makes captures the most useful tests in the project and the ones that must
not be committed. Both facts have the same cause: they are real.

## Why they are useful

Hand-written tests drift from what the API actually returns, and a rule then
passes its tests while missing the real thing. Every one of those found in the
1.2.0 release came from reading captured output:

- `storage_type` arrives as `"VolumeType.MANAGED"`, and `SEC-VOL-001` compares
  it against `"dbfs"`. The rule cannot fire.
- `autotermination_minutes` arrives as `0`, not absent, so a rule checking for
  a missing key never fired.
- `access_mode` arrives as a `DataSecurityMode` enum, not the string the policy
  expected.

None of that is guessable. It has to be looked at.

## Why they are not committed

`captured_storage_scentre_group_raw_data.json` names a customer, a catalog and
a volume. Owner addresses are replaced at capture time, but nothing else is.

These used to live in `../synthetic/` alongside the committed tests, which left
them untracked in the git panel, one `git add .` away from being published, and
required judging each one by hand before every commit.

## Promoting one

Testing → Captures → Promote, or `synthetic_estate.promote(name)`.

Promotion keeps the shape and replaces the names, then checks its own work: it
collects the identifying words from the original and fails if any of them
survive anywhere in the result. That check exists because the list of
identifying keys is a guess that the next handler will outgrow, and the failure
should happen here rather than in a pull request.

The result lands in `../synthetic/` named for what it demonstrates
(`real_storage_sec_vol_001.json`) rather than for a resource, and ships to every
deployment from then on.
