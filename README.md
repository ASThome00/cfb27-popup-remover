# Popup Remover (College Football 27)

Removes popups that interrupt you just to confirm something already happened. The first one covered is the **SUCCESS** box that says "... upgraded the ... Skill Group to Level N!" after every player skill-group upgrade in Dynasty. With the mod on, the upgrade applies and the player card updates right away with no popup. If an upgrade actually **fails**, you still get the ERROR popup. More popups will be added over time.

Not changed yet: Road to Glory upgrades use a different screen. Popups that ask you to decide something (spend points, not enough points, and so on) are left alone on purpose. For the offline nag popups, see [No Offline Warning](https://github.com/ASThome00/cfb27-no-offline-warning). The two mods don't touch the same files and can be used together.

## Install

Import `PopupRemover_v<version>.fbmod` in MMC Mod Manager, enable it, launch through the Mod Manager. After changing versions use **Delete ModData and Launch** once.

## What it patches

- `common/ui/node_cfm/corenode.ast` — `logic_cfm.model.manageplayer.Skills`, skill-group upgrade result handler. After a successful upgrade the code now skips building the result popup and goes straight to finishing the upgrade (the card refresh and "ready for the next upgrade" flag run exactly as before). Failed upgrades take the original path. 13 bytes changed in place.

Any other mod that replaces `common/ui/node_cfm/corenode.ast` will conflict with this one. Whichever loads last wins.

## Building it yourself

`python tools\build_patch.py <vanilla corenode.ast> out.AST` (export `common/ui/node_cfm/corenode.ast` from MMC Editor's Legacy Explorer, from a project that doesn't modify it). Needs `pip install zopfli` (the patched stream is recompressed with zopfli to fit the original slot).

## Changelog

See `CHANGELOG.md`.
