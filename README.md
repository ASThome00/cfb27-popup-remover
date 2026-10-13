# Popup Remover (College Football 27)

Removes popups in **EA Sports College Football 27 (PC)** that interrupt you without asking you to decide anything. Since v1.1.0 this mod also contains everything from **[No Offline Warning](https://github.com/ASThome00/cfb27-no-offline-warning)**, which is no longer updated on its own. If you used No Offline Warning, switch to this mod and disable the old one.

Popups removed:

| Popup | Where you saw it | Since |
|---|---|---|
| **OFFLINE WARNING** ("You will be ineligible to earn trophy and mascot rewards when you are not logged in...") | Before every Dynasty / Road to Glory game while signed out | v1.1.0 (No Offline Warning v1.0) |
| **ACCOUNT ERROR** (with MMC: "Mods require being offline...") | At boot and on every Dynasty / Road to Glory entry while signed out | v1.1.0 (No Offline Warning v1.1) |
| **SUCCESS** ("... upgraded the ... Skill Group to Level N!") | After every player skill-group upgrade in Dynasty | v1.0 |

Popups that ask you to decide something (spend points, not enough points, exit confirmations, and so on) are left alone on purpose, and a skill upgrade that actually **fails** still shows its ERROR popup.

Made by **ASThome**.

## Install

1. Import `PopupRemover_v<version>.fbmod` in **MMC Mod Manager**.
2. **Disable or remove No Offline Warning** if you have it. It ships two of the same files, so keeping both does nothing useful and only gives MMC a conflict to resolve.
3. Enable Popup Remover, then use **Delete ModData and Launch** once after changing versions.

## What it patches

Three legacy UI script archives (EA APT, Flash-style ActionScript 2 bytecode), patched in place without changing their size:

| File | Function | Change | Effect |
|---|---|---|---|
| `common/ui/node_cfm/hub/corenode.ast` | `art_control.button.DynastyPlayButton` press handler | 1 byte, `0x73 → 0x74` | Skips the Offline Warning |
| `common/ui/node_com/scriptpod.ast` | `madden.online.module.Login._ShowLoginFailedPopup` | 1 byte, `0x49 → 0x48` | Never opens the login-failed popup |
| `common/ui/node_cfm/corenode.ast` | `logic_cfm.model.manageplayer.Skills._HandlePlayerDetailsAdapterEvents` | 13 bytes (27-byte rewrite) | Skips the upgrade SUCCESS popup |

**Offline Warning.** The Play button runs `if (!IsLoggedIn() && !IsPopupShowing(EXIT_POPUP)) showOfflineWarning(); else startGame();`. A `push true` becomes `push false` in the second condition, so offline the check fails and the normal start path runs. Online, the first condition already short-circuits, so the patched byte is never reached.

**Account Error.** Every front-end login failure ends in `_ShowLoginFailedPopup`, which first calls the failure callback (so the waiting screen carries on), then opens the popup `if (mShowLoginFailedPopup == true)`. The comparison becomes `true < mShowLoginFailedPopup`, which is never true. The callback is untouched, so the game behaves as if you had pressed OK. Side effect: any login-failure popup from this module is suppressed, including a genuine "servers unavailable" one. Mods require playing offline anyway.

**Skill upgrade SUCCESS.** After an upgrade the handler always built `MakeOKPopup(UPGRADE_RESULT_POPUP, success ? SUCCESS : ERROR, msg).Open()`. The ternary is rewritten so success jumps straight to clearing the "upgrade in progress" flag (which the next upgrade needs), and failure builds the same ERROR popup as before. The card refresh runs exactly as in the unmodded game.

No strings or other UI is changed, and login state is not spoofed.

## Known limitations

* The Offline Warning on **Play Now** (main menu → Play → Play Now) comes from the game's native code, not the UI scripts, so it is not removed.
* Road to Glory upgrades use a different screen and are not changed.
* Any other mod that replaces one of the three files above conflicts with this one; whichever loads last wins.
* Every title update needs a rebuild from **fresh exports** of all three files. MMC replaces whole files, so an out-of-date build rolls EA's changes in them back.

## Building it yourself

1. In MMC Editor → Legacy Explorer, export the three files above from a project that doesn't modify them.
2. `python tools\build_patch.py <exported.AST> <patched.AST>` on each one (`pip install zopfli`; the scriptpod and corenode streams need it to fit their original slots). The script finds each site by byte pattern, refuses to write if a pattern is missing or ambiguous, recompresses, zero-pads to the original slot and verifies the round trip.
3. Import the three patched files into `PopupRemover.fbproject`, save, **File → Export to Mod**.

## Changelog

See `CHANGELOG.md`.

## Disclaimer

Not affiliated with or endorsed by EA. Use mods offline only. Use at your own risk.

## License

[MIT](LICENSE)
