"""Per-vendor source extractors.

Each module in this package owns the ETL for one vendor source
format (CMSIS-SVD, ATDF, MCUXpresso headers, Zephyr DTS, etc.)
and exposes a consistent ``extract_device(...)`` entry point
that returns a canonical-IR-compatible dict ready for YAML
emission.

The proof-of-life extractor in this initial commit is
``cmsis_svd`` (covers ST + any community-SVD vendor).  Other
extractors are migrated incrementally from alloy-codegen's
``src/alloy_codegen/sources/*.py`` as separate changes per
vendor — see the alloy-codegen OpenSpec queue.
"""
