## What changed

<!-- One paragraph. Link the issue if there is one. -->

## Type

- [ ] Documentation
- [ ] Tooling / script
- [ ] HAL / C code
- [ ] DiPlay patch
- [ ] Other

## Tested on

- Head unit:
- Android / ROM:
- DiPlay version:

## Safety

- [ ] This change cannot write to `/system`
- [ ] If it can, it backs up before writing and documents the rollback
- [ ] No secrets, MAC addresses, SSIDs, or signing keys are included

## Checklist

- [ ] `python tools/check_secrets.py` passes
- [ ] `python -m compileall .` passes
- [ ] CHANGELOG updated
