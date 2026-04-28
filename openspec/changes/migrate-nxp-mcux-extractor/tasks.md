# Tasks — migrate-nxp-mcux-extractor

- [ ] 1.1 Port `nxp_mcux.py` into `extractors/nxp_mcux.py`,
      register `Extractor` for `(nxp, imxrt1060)`.
- [ ] 1.2 Re-extract mimxrt1062 + mimxrt1064; diff vs YAMLs
      SHALL be zero.
- [ ] 1.3 Confirm parity gate green; delete codegen-side
      parser + `_build_nxp_device_ir`.
- [ ] 1.4 `openspec validate migrate-nxp-mcux-extractor --strict`.
- [ ] 1.5 Archive + commit in both repos.
