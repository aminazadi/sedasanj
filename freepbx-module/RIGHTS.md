# Module rights and release integrity

## Current license

`module.xml` identifies this module as GPLv3+. Anyone may copy and redistribute the module when they follow that license. A copyright notice identifies authorship; it does not cancel permissions granted by the GPL. Do not add a no-copy or proprietary restriction to this GPL release.

The project publisher in module metadata is Seda Sanj. The repository history records individual contributors, but the publisher field and Git history alone do not establish who owns the transferable economic rights. Before making a registration or enforcement claim, reconcile the named rights holder with contributor, employment, and contractor agreements and retain those agreements with the release records.

## Third-party material

- `tests/fixtures/callrecording-*.functions.inc.php` contains FreePBX `callrecording` source excerpts and retains the upstream copyright notices. It is test material, not Seda Sanj-authored source.
- `assets/fonts/` includes font assets with their own license notice (`assets/fonts/OFL.txt`). Keep that notice in source and release archives.
- `engine/bin/` release binaries are third-party products. `release-binaries.json` records their upstream source and SHA-256 digest; keep the applicable upstream license and attribution with every distributed binary. Verify those license texts before each release.
- FreePBX APIs and runtime components are external dependencies; this module does not claim ownership of them.

## Protection that fits the GPL release

- Keep Git history, signed release artifacts, release manifests, and the matching source for every distributed version. Never publish the signing seed; rotate it if exposed.
- The automatic updater already verifies Ed25519 signatures and a signed release manifest. The bundled key at `assets/release-signing.pub` is currently a placeholder, so automatic update verification is disabled until the real public key is installed in a release and the matching private seed is configured in the API.
- Do not encrypt or obfuscate the PHP source shipped to customers. This module is distributed under GPLv3+, which requires corresponding source when conveying object code, and encryption would prevent customers from inspecting and modifying the distributed program. PHP source encoding also cannot prevent a determined recipient from extracting or replacing code on a PBX they administer.
- Secrets such as API credentials and signing seeds belong in protected runtime configuration or a secrets manager, not in the source archive. Release signing protects artifact authenticity; it does not stop GPL-permitted copying.

## Separate brand protection

The Seda Sanj name and logo can be assessed separately for trademark registration. Use the exact legal owner and goods/services scope chosen by the business, and retain dated examples of public use. Trademark registration does not prevent redistribution of the GPL code under another name.

For Iranian software registration or a dispute, confirm the current filing process and evidence requirements with the competent registration authority and an intellectual-property lawyer. This repository record is not proof of title or a registration certificate.
