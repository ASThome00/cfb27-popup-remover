#!/usr/bin/env python3
"""
build_patch.py - rebuild the "CFB 27 Popup Remover" patches from ORIGINAL legacy
.AST files exported from MMC Editor (Legacy Explorer -> Export).

    python build_patch.py <original.AST> <patched.AST>

Finds each known patch site by byte pattern in the decompressed "Apt Data"
bytecode, applies the change, recompresses (zlib level 9, falling back to
zopfli if a few bytes over: pip install zopfli), zero-pads to the original
slot, verifies the round trip and writes an archive with the ORIGINAL
header/TOC/layout untouched. Refuses to write if a site is missing or ambiguous.

Patches
  skill-upgrade-success  common/ui/node_cfm/corenode.ast   (added v1.0, tu0926)
        logic_cfm.model.manageplayer.Skills._HandlePlayerDetailsAdapterEvents:
        on NOTIFY_COMMANDCOMPLETE for COMMAND_UPGRADESKILLBUCKET the handler
        refreshes the card, then always does
            MakeOKPopup(UPGRADE_RESULT_POPUP, success ? SUCCESS : ERROR, msg).Open()
        and finally clears mIsProcessingUpgrade.
        The ternary is rewritten so success branches straight to
        `mIsProcessingUpgrade = false`; failures still build the ERROR popup.
        27-byte in-place rewrite (13 bytes differ), same length, stack balanced:
          old: PushRegister msg; PushRegister success; BranchIfTrue ->SUCCESS;
               VarPath loc.Main.ERROR; BranchAlways ->make
          new: PushRegister success; BranchIfTrue ->clearFlag;
               PushRegister msg; VarPath loc.Main.ERROR; BranchAlways ->make
        The two branch operands are 8-byte aligned, so the new bytes are only
        valid at this alignment and branch distance: the pattern therefore
        covers everything from the site through the branch target
        (`b9 01 a2 26 74 4f` = this.mIsProcessingUpgrade = false). Any TU that
        moves the site by a non-multiple of 8 or edits the popup block makes
        the pattern miss -> re-derive, never patch blind.
"""

import argparse, importlib.util, os, struct, sys, zlib

PATCHES = [
    dict(
        name="skill-upgrade-success popup (node_cfm/corenode.ast)",
        # 348217 b9 06 | b9 03 | 9d 00 00 [10 00 00 00]          PushRegister msg; PushRegister success; BranchIfTrue +16
        # 348228 ad 03 7b 83 d9 | 99 00..00 [05 00 00 00]         VarPath loc.Main.ERROR; BranchAlways +5
        # 348244 ad 03 7b 83 da                                  VarPath loc.Main.SUCCESS
        # 348249 ad 05 .. db | b5 03 | b9 01 af 29 | a2 dc 52 | 87 .. 07 | 17 | 59 b9 07 b2 ad
        #        MakeOKPopup(UPGRADE_RESULT_POPUP, title, msg) -> r7; r7.Open()
        # 348282 b9 01 a2 26 74 4f                               this.mIsProcessingUpgrade = false   <- new branch target
        pattern=bytes.fromhex(
            "b906b9039d000010000000ad037b83d99900000000000005000000"
            "ad037b83daad0501030405dbb503b901af29a2dc5287000000000000070000001759b907b2ad"
            "b901a226744f"),
        index=0,
        old=bytes.fromhex("b906b9039d000010000000ad037b83d99900000000000005000000"),
        new=bytes.fromhex("b9 03 9d 00 00 00 00 36 00 00 00 b9 06 ad 03 7b 83 d9 99 00 00 00 00 05 00 00 00"),
        known_offset=348217,  # tu0926 (September 26, 2026 title update)
    ),
]


def _normalize(table):
    for pt in table:
        if isinstance(pt["old"], int):
            pt["old"] = bytes([pt["old"]]); pt["new"] = bytes([pt["new"]])
        assert len(pt["old"]) == len(pt["new"]), pt["name"]
        pt.setdefault("known_offset", None)
    return table


_normalize(PATCHES)


def load_patches(path):
    spec = importlib.util.spec_from_file_location("patches", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    table = list(mod.PATCHES)
    for pt in table:  # normalize single-byte int entries to bytes
        if isinstance(pt["old"], int):
            pt["old"] = bytes([pt["old"]])
            pt["new"] = bytes([pt["new"]])
        assert len(pt["old"]) == len(pt["new"]), f"{pt['name']}: old/new length mismatch"
        pt.setdefault("known_offset", None)
    return table


def toc_entries(d):
    assert d[:8] == b"BGFA1.05", "not a BGFA1.05 archive"
    toc_off = struct.unpack_from("<i", d, 16)[0]
    toc_len = struct.unpack_from("<i", d, 24)[0]
    lens = [d[33 + i] for i in range(5)]          # unknown, id, start, size, extra
    shift, add, desc = d[38], d[40] * 4, d[44]
    entry_len = sum(lens) + desc + 1
    i, out = toc_off + add, []
    while i + entry_len <= toc_off + toc_len + add:
        e = d[i + 1:i + entry_len]
        p = lens[0]
        eid = e[p:p + lens[1]]; p += lens[1]
        start = int.from_bytes(e[p:p + lens[2]], "little") << shift; p += lens[2]
        size = int.from_bytes(e[p:p + lens[3]], "little")
        out.append((eid.hex(), start, size))
        i += entry_len
    return out


def find_sites(data):
    """Return [(patch, offset, how)] for every patch whose site is in this file.
    Different assets carry different (non-overlapping) sets of patches; every
    pattern that matches is applied. A pattern with multiple hits aborts."""
    found = []
    for pt in PATCHES:
        hits = []
        k = data.find(pt["pattern"])
        while k != -1:
            hits.append(k + pt["index"])
            k = data.find(pt["pattern"], k + 1)
        if len(hits) == 1:
            found.append((pt, hits[0], "pattern"))
        elif len(hits) > 1:
            sys.exit(f"{pt['name']}: pattern is ambiguous (hits={hits})")
        else:
            ko = pt["known_offset"]
            if ko is not None and len(data) >= ko + len(pt["old"]) and data[ko:ko + len(pt["old"])] == pt["old"]:
                found.append((pt, ko, "known offset"))
    if not found:
        for pt in PATCHES:
            ko = pt["known_offset"]
            if ko is not None and len(data) >= ko + len(pt["new"]) and data[ko:ko + len(pt["new"])] == pt["new"]:
                sys.exit(f"{pt['name']}: this file is already patched")
        sys.exit("could not locate any patch site in this file (is this an original export of a supported asset?)")
    return found


def main(src, dst):
    d = open(src, "rb").read()
    apt = None
    for eid, start, size in toc_entries(d):
        raw = d[start:start + size]
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            continue
        if dec.startswith(b"Apt Data"):
            apt = (eid, start, size, dec)
    if apt is None:
        sys.exit("no 'Apt Data' entry found")
    eid, start, size, data = apt
    print(f"Apt Data entry {eid}: archive offset {start}, compressed {size}, decompressed {len(data)}")

    sites = find_sites(data)
    patched = bytearray(data)
    expected_diffs = []
    for pt, off, how in sites:
        print(f"{pt['name']}: site found by {how} at offset {off}")
        cur = bytes(patched[off:off + len(pt["old"])])
        if cur == pt["new"]:
            print("  (already patched, skipping)")
            continue
        assert cur == pt["old"], f"unexpected bytes {cur.hex()} at {off}"
        patched[off:off + len(pt["new"])] = pt["new"]
        expected_diffs.extend(range(off, off + len(pt["new"])))
    if not expected_diffs:
        sys.exit("already patched")

    comp = zlib.compressobj(9, zlib.DEFLATED, 15, 8, zlib.Z_DEFAULT_STRATEGY)
    s = comp.compress(bytes(patched)) + comp.flush()
    print(f"zlib-9 recompressed size {len(s)} (slot {size})")
    if len(s) > size:
        # EA's own stream was zlib-9 and fits by construction, but one changed byte can
        # push our stream over by a few bytes. zopfli produces a smaller but still
        # standard zlib stream, so the loader can't tell the difference.
        try:
            import zopfli.zlib
        except ImportError:
            sys.exit(f"recompressed entry ({len(s)}) larger than original slot ({size}); "
                     f"install zopfli (pip install zopfli) so the entry can be shrunk to fit")
        s = zopfli.zlib.compress(bytes(patched), numiterations=15)
        print(f"zopfli recompressed size {len(s)}")
        if len(s) > size:
            sys.exit(f"zopfli output ({len(s)}) still larger than slot ({size}); layout would need rewriting")
    s = s + b"\0" * (size - len(s))          # zero-pad if smaller (inflate stops at end-of-stream)
    new = d[:start] + s + d[start + size:]
    assert len(new) == len(d)

    # verify round trip
    chk = zlib.decompress(new[start:start + size])
    diffs = [i for i in range(len(data)) if data[i] != chk[i]]
    assert diffs == sorted(i for i in expected_diffs if data[i] != patched[i]), diffs
    open(dst, "wb").write(new)
    print(f"wrote {dst}: {len(diffs)} byte(s) changed at {diffs}; header/TOC unchanged")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="same-size BGFA/APT byte patcher (see module docstring)")
    ap.add_argument("src", help="original .AST exported from MMC Editor")
    ap.add_argument("dst", help="patched .AST to write")
    ap.add_argument("--patches", help="optional external patches.py (default: the table embedded in this file)")
    a = ap.parse_args()
    if a.patches:
        PATCHES[:] = load_patches(a.patches)
    print(f"{len(PATCHES)} patch site(s) loaded")
    main(a.src, a.dst)
