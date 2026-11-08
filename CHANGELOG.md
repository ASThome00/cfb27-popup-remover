# Changelog

## 1.2.0 – 2026-11-08
- **The OFFLINE WARNING fix now survives mods that replace `common/ui/node_cfm/hub/corenode.ast`** (for example AIO Dynasty). Before this, any such mod loaded at a higher priority brought the popup back. Popup Remover now also ships **`common/ui/node_com/main.ast`**, which defines the Dynasty Play button's class with the offline check already patched, before the hub loads. The game defines that class only if it doesn't exist yet, so the hub's copy (ours or another mod's) skips itself. Tested in-game alone and with AIO Dynasty v1.4.1 at priority 1.
- **The skill-upgrade SUCCESS fix now survives mods that replace `common/ui/node_cfm/corenode.ast`** (AIO Dynasty ships that too). Same technique: `common/ui/node_com/scriptpod.ast` now also defines the `Skills` class with the SUCCESS fix applied, right after the first class there that shares its parent class, so it's defined before Dynasty loads. Tested in-game with AIO Dynasty v1.4.1 at priority 1.
- The in-place fixes in `hub/corenode.ast` and `node_cfm/corenode.ast` stay, so each popup also stays gone if another mod replaces `main.ast` or `scriptpod.ast` instead.
- New build tool `tools/build_class_override.py` (plus `tools/astbuild.py`). `main.ast` grows by about 11 KB and `scriptpod.ast` by about 6 KB, so those can't be patched in place.
- Built for the **October 29, 2026 title update**. `hub/corenode.ast` and `node_cfm/corenode.ast` are unchanged from 1.1.1.

## 1.1.1 – 2026-10-29
- Rebuilt for the **October 29, 2026 title update**. EA changed `common/ui/node_cfm/corenode.ast` (3 bytes of script data) and `common/ui/node_com/scriptpod.ast` (2 bytes), away from the patch sites; `common/ui/node_cfm/hub/corenode.ast` changed only in its archive header. All three re-exported from the update and re-patched; same edits at the same offsets (346401 / 145869 / 1052596). No functional changes.

## 1.1.0 – 2026-10-13
- **Merged [No Offline Warning](https://github.com/ASThome00/cfb27-no-offline-warning)**: now also removes the OFFLINE WARNING popup before Dynasty/RTG games (`common/ui/node_cfm/hub/corenode.ast`, 1 byte @145869) and the ACCOUNT ERROR login-failure popup (`common/ui/node_com/scriptpod.ast`, 1 byte @1052596). Same patches as No Offline Warning 1.1.6; disable that mod when using this one.
- Built for the **October 13, 2026 title update**. EA did not change any of the three files in this update (byte-identical to October 1); patched outputs are byte-identical to No Offline Warning 1.1.6 / Popup Remover 1.0.1.
- Build table: one `PATCHES` table for all three assets; known-offset fallback disabled so a missed pattern stops the build instead of patching the wrong archive.

## 1.0.1 – 2026-10-02
- Rebuilt for the **October 1, 2026 title update**. Same 13-byte patch, re-applied to the new `common/ui/node_cfm/corenode.ast` (site moved 348217 → 346401 in the export; EA changed the script). No functional changes.
- Exported with MMC v1.1.0.6.

## 1.0 – 2026-09-27
- Initial release, built against the **September 26, 2026 title update**.
- Removes the SUCCESS popup shown after every Dynasty player skill-group upgrade. Failed-upgrade (ERROR) popups are kept.
