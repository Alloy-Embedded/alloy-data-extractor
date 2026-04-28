# Tasks — add-bulk-discovery-cmsis-pack-manager

## Phase 1: Discovery layer

- [x] 1.1 Add `bulk_discovery.py` that wraps cmsis-pack-manager
      to enumerate devices for a vendor.
- [x] 1.2 Map each discovered device to a `(vendor, family)`
      pair the extractor registry can resolve.
- [x] 1.3 Cache pack downloads in `~/.cache/alloy-data-extractor/`.

## Phase 2: Bulk dispatcher

- [x] 2.1 New CLI `bulk` subcommand: `alloy-data-extract bulk
      --vendor <name> [--filter <regex>] [--shard N/M] [--dry-run]`.
- [x] 2.2 Per-chip failure isolation: one chip's error does not
      abort the run.
- [x] 2.3 Write `bulk-report.json` listing each chip + status.
- [x] 2.4 Determinism: same pin → same set + same order.

## Phase 3: CI integration

- [x] 3.1 Add a GitHub Actions matrix job: `bulk-extract-{st,
      microchip, nxp, espressif, raspberrypi, nordic}`.
- [x] 3.2 Sharded ST run finishes under 10 min.
- [x] 3.3 Bulk-report uploaded as a build artifact for review.

## Phase 4: Validate + archive

- [x] 4.1 Test on a real cmsis-pack-manager mirror.
- [x] 4.2 `openspec validate add-bulk-discovery-cmsis-pack-manager --strict`.
- [x] 4.3 Archive + commit.
