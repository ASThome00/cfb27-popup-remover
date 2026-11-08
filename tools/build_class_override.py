#!/usr/bin/env python3
r"""
build_class_override.py - "CFB 27 Popup Remover": define a patched copy of an
APT class from a file other mods don't ship, so the fix survives mods that
replace the class's own file.

    python build_class_override.py offline-warning       <main.ast>      <hub_corenode.ast> <out.AST> [--growth-only]
    python build_class_override.py skill-upgrade-success <scriptpod.ast> <cfm_corenode.ast> <out.AST> [--growth-only]

  <host>   the file that gets the class:   common/ui/node_com/main.ast or
           common/ui/node_com/scriptpod.ast. Pass scriptpod.ast AFTER the
           account-error patch (build_patch.py output); main.ast as exported.
  <donor>  ORIGINAL file the class is copied from, same title update (read only):
           common/ui/node_cfm/hub/corenode.ast or common/ui/node_cfm/corenode.ast.

Presets
  offline-warning        art_control.button.DynastyPlayButton (hub) -> node_com/main.ast,
                         run right after widget.core.Widget (its superclass).
                         Patch: offline check 0x73 -> 0x74 (same as build_patch.py).
  skill-upgrade-success  logic_cfm.model.manageplayer.Skills (node_cfm/corenode) ->
                         node_com/scriptpod.ast, run right after the first scriptpod
                         class that extends fb_logic_com.model.BaseModel (Skills'
                         superclass, defined in frameworkscriptpod), which proves the
                         superclass exists there. Patch: the 27-byte success-branch
                         rewrite (same as build_patch.py).

Why
  MMC replaces whole legacy files, so a mod that ships the class's file at higher
  priority (AIO Dynasty ships both node_cfm/hub/corenode.ast and node_cfm/corenode.ast)
  drops the in-place fix there. Each class is defined behind a guard:
      if (!art_control.button.DynastyPlayButton) { ...define the class... }
  so whichever archive defines it FIRST wins. node_com/main.ast and scriptpod.ast load
  at boot, long before the Dynasty files, so the copy defined there wins and the
  original (vanilla or another mod's) skips itself. offline-warning verified in-game
  2026-11-08 (October 29, 2026 title update), alone and with AIO Dynasty v1.4.1 at
  priority 1.

How (every site is found structurally, never by offset)
  1. Donor: find the frame-0 InitAction whose guard is the class path. Copy that action
     block up to its End and apply the preset's patch inside it (exactly one hit).
  2. Host Apt1: append the pool strings the host doesn't already have to the constant
     table (entries grow, string area shifts, existing indices unchanged).
  3. Host Apt Data: append [anchor block minus End][stack-neutral filler]
     [donor block incl. End], then a new pool array (donor constant indices remapped
     to the host's) and fresh copies of the function names and argument records, and
     repoint every ConstantPool / DefineFunction(2) operand in the copied block at
     them. The copied anchor code still points at its original strings/arrays, which
     stay where they were. The filler keeps the donor block at its original address
     mod 8, so aligned operands (and the patch) stay valid.
  4. Redirect frame 0's anchor InitAction (8-byte action pointer, in place) to the
     combined block. The combined block is linear and End-terminated, so a loader that
     walks the bytecode to fix up pointers reaches all of it.
  The donor block must not contain PushData/PushString-style pointer operands
  (0x96 / 0xa1) or more than one constant pool; the tool stops if one ever appears.

  The archive is rebuilt with astbuild (entries grow, so unlike build_patch.py the
  layout changes). --growth-only writes the same file without step 4 (everything
  appended but unreferenced): the load test that proved grown entries are accepted.

Needs astbuild.py next to this script (the repo's tools\) or in ..\..\tools.
"""
import argparse, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "..", "tools")):
    if os.path.exists(os.path.join(_p, "astbuild.py")):
        sys.path.insert(0, os.path.abspath(_p))
        break
import astbuild  # noqa: E402

PRESETS = {
    "offline-warning": dict(
        cls="art_control.button.DynastyPlayButton",
        anchor=("defines", "widget.core.Widget"),
        # same pattern/index/bytes as the offline-warning entry in build_patch.py
        pattern=bytes.fromhex("49124cb8000000100000001773b901af225ab901af86a2eb524912b8"),
        index=12, old=b"\x73", new=b"\x74",
    ),
    "skill-upgrade-success": dict(
        cls="logic_cfm.model.manageplayer.Skills",
        anchor=("extends", "fb_logic_com.model.BaseModel"),
        # same pattern/bytes as the skill-upgrade-success entry in build_patch.py
        pattern=bytes.fromhex(
            "b906b9039d000010000000ad037b83d99900000000000005000000"
            "ad037b83daad0501030405dbb503b901af29a2dc5287000000000000070000001759b907b2ad"
            "b901a226744f"),
        index=0,
        old=bytes.fromhex("b906b9039d000010000000ad037b83d99900000000000005000000"),
        new=bytes.fromhex("b9 03 9d 00 00 00 00 36 00 00 00 b9 06 ad 03 7b 83 d9 99 00 00 00 00 05 00 00 00"),
    ),
}

ONE_BYTE_OPERAND = {0xa2, 0xaf, 0xb9, 0xb5, 0xae, 0xb0, 0xb1, 0xb2, 0xb3, 0xa4, 0xa5, 0xa6, 0xa7, 0x9f, 0x9a}
ALIGNED4 = {0x99, 0x9d, 0xb8, 0x87, 0xb4, 0xb7, 0x94}


def fail(msg):
    raise SystemExit("ERROR: " + msg)


def q(d, o):
    return struct.unpack_from("<Q", d, o)[0]


def al8(p):
    return (p + 7) & ~7


def cstr(d, p):
    return bytes(d[p:d.index(b"\0", p)])


def walk(d, start):
    """Linear walk of one action block from `start` to its top-level End.
    Yields (op_addr, op, operand_addr, depth). Function bodies are walked inline (they
    are contiguous), and the walk ends at the End that follows the outermost code."""
    p = start
    fn_ends = []                         # end addresses of open function bodies
    while True:
        while fn_ends and p >= fn_ends[-1]:
            if p != fn_ends[-1]:
                fail(f"function body overrun at {p}")
            fn_ends.pop()
        op = d[p]
        a = p
        depth = len(fn_ends)
        p += 1
        if op == 0x00 and not fn_ends:
            yield a, op, None, depth
            return
        if op < 0x80:
            yield a, op, None, depth
            continue
        if op == 0x88:
            o = al8(p); p = o + 16
        elif op in (0x8e, 0x9b):
            o = al8(p); size = q(d, o + 24); p = o + 48
            if not (q(d, o + 32) == 0x98765432 and q(d, o + 40) == 0x12345678):
                fail(f"function canary missing at {a}")
            fn_ends.append(p + size)
        elif op in ALIGNED4:
            o = al8(p); p = o + 4
        elif op in (0x96, 0xa1):
            fail(f"op {op:#x} at {a} carries a pointer this tool doesn't relocate")
        elif op in ONE_BYTE_OPERAND:
            o = p; p += 1
        elif op in (0xa3, 0xb6):
            o = p; p += 2
        elif op in (0xac, 0xad):
            o = p; p += 1 + d[p]
        else:
            fail(f"unknown opcode {op:#x} at {a}")
        yield a, op, o, depth


def parse_apt1(a):
    if a[:4] != b"Apt1" or q(a, 0x28) != 48:
        fail("unexpected Apt1 layout")
    cnt = q(a, 0x20)
    return cnt, [struct.unpack_from("<QQ", a, 48 + 16 * i) for i in range(cnt)]


def const_strings(apt1):
    _, ents = parse_apt1(apt1)
    return [cstr(apt1, v) if t == 1 else None for t, v in ents]


def entry_by_head(arch, head):
    es = [e for e in arch.entries if e.dec.startswith(head)]
    if len(es) != 1:
        fail(f"expected one {head!r} entry, found {len(es)}")
    return es[0]


def frame0(d):
    """(frame_struct_addr, count, items_ptr) of the frame holding the InitActions."""
    cands = []
    for o in range(16, len(d) - 16, 8):
        c, p = q(d, o), q(d, o + 8)
        if 5 <= c < 5000 and p % 8 == 0 and 16 <= p and p + 8 * c <= len(d):
            try:
                ts = [q(d, q(d, p + 8 * k)) for k in range(c)]
            except (struct.error, OverflowError):
                continue
            if sum(t == 8 for t in ts) >= 5 and all(1 <= t <= 12 for t in ts):
                cands.append((o, c, p))
    if len(cands) != 1:
        fail(f"frame 0 not found unambiguously: {cands}")
    return cands[0]


def init_actions(d):
    _, c, p = frame0(d)
    for k in range(c):
        it = q(d, p + 8 * k)
        if q(d, it) == 8:
            yield k, it, q(d, it + 16)


def block_pool(d, act):
    if d[act] != 0x88:
        return None
    cnt, ptr = struct.unpack_from("<QQ", d, al8(act + 1))
    return list(struct.unpack_from("<%dQ" % cnt, d, ptr))


class Block:
    """One InitAction block: its ops, pool names and what it defines/extends."""

    def __init__(self, d, consts, act):
        self.act = act
        self.ops = list(walk(d, act))
        self.end = self.ops[-1][0] + 1                         # one past End
        pool = block_pool(d, act) or []
        names = [consts[g] if g < len(consts) else None for g in pool]

        def path(op, o):
            idx = d[o + 1:o + 1 + d[o]]
            try:
                return ".".join(names[i].decode("latin1") for i in idx)
            except (IndexError, AttributeError):
                return None
        top = [(a, op, o) for a, op, o, depth in self.ops if depth == 0]
        self.defines = None
        last_pop = top[-2][0] if len(top) >= 2 and top[-2][1] == 0x17 else None
        # the class guard: `<chain>; BranchIfTrue -> <final Pop>` (namespace guards
        # before it branch to their own Pop, so they don't match)
        for i, (a, op, o) in enumerate(top):
            if (op == 0x9d and i and top[i - 1][1] in (0xac, 0xad)
                    and o + 4 + struct.unpack_from("<i", d, o)[0] == last_pop):
                self.defines = path(top[i - 1][1], top[i - 1][2])
                break
        self.extends = {path(op, o) for (_, op, o), (_, nop, _) in zip(top, top[1:])
                        if op in (0xac, 0xad) and nop == 0x69}


def blocks(d, consts):
    """Every InitAction block this walker can parse. Blocks using opcodes it doesn't
    know (EA extensions such as 0xbc/0xd8, never in the classes we copy) are skipped:
    they can't be the donor (it must be fully walkable to relocate) or the anchor."""
    for k, it, act in init_actions(d):
        if d[act] == 0x88:
            try:
                b = Block(d, consts, act)
            except SystemExit:
                continue
            yield k, it, b


def build(preset, host_path, donor_path, out_path, growth_only=False):
    P = PRESETS[preset]

    # 1. donor: the class block, patched
    donor = astbuild.Archive.read(donor_path)
    dd = bytearray(entry_by_head(donor, b"Apt Data").dec)
    dconsts = const_strings(entry_by_head(donor, b"Apt1").dec)
    found = [b for _, _, b in blocks(dd, dconsts) if b.defines == P["cls"]]
    if len(found) != 1:
        fail(f"{P['cls']} InitAction not found unambiguously in {donor_path}: {[b.act for b in found]}")
    blk = found[0]
    src, src_end, ops = blk.act, blk.end, blk.ops
    pools = {struct.unpack_from("<QQ", dd, o) for _, op, o, _ in ops if op == 0x88}
    if len(pools) != 1:
        fail(f"{P['cls']} block has {len(pools)} different constant pools; this tool relocates one")
    hits = []
    i = dd.find(P["pattern"], src, src_end)
    while i >= 0:
        hits.append(i); i = dd.find(P["pattern"], i + 1, src_end)
    if len(hits) != 1:
        fail(f"{preset} pattern hits {hits} inside the {P['cls']} block (want exactly one)")
    site = hits[0] + P["index"]
    old, new = P["old"], P["new"]
    if bytes(dd[site:site + len(old)]) != old or len(new) != len(old):
        fail(f"{preset} bytes at donor {site} are not the expected original")
    dd[site:site + len(new)] = new
    print(f"donor: {P['cls']} block {src}..{src_end} ({src_end - src} B, {len(ops)} ops), "
          f"{preset} patch @{site} ({sum(x != y for x, y in zip(old, new))} B differ)")

    # 2. host: anchor block and constant table
    host = astbuild.Archive.read(host_path)
    md_e = entry_by_head(host, b"Apt Data")
    ma_e = entry_by_head(host, b"Apt1")
    md, ma = md_e.dec, ma_e.dec
    mcnt, ments = parse_apt1(ma)
    mconsts = const_strings(ma)
    hblocks = list(blocks(md, mconsts))
    if any(b.defines == P["cls"] for _, _, b in hblocks):
        fail(f"{host_path} already defines {P['cls']} - already patched, or EA moved the class")
    kind, want = P["anchor"]
    anchors = [(k, it, b) for k, it, b in hblocks
               if (b.defines == want if kind == "defines" else want in b.extends)]
    if kind == "defines" and len(anchors) != 1:
        fail(f"{want} InitAction not found unambiguously in {host_path}: {[b.act for _, _, b in anchors]}")
    if not anchors:
        fail(f"no InitAction in {host_path} extends {want}")
    wk, witem, wb = anchors[0]                                 # first in frame order
    wact, wend = wb.act, wb.end - 1                            # wend = address of its End
    if sum(act == wact for _, _, act in init_actions(md)) != 1:
        fail("anchor block is shared by several InitActions")
    print(f"host: anchor InitAction #{wk} item@{witem} ({kind} {want}"
          f"{', defines ' + wb.defines if kind == 'extends' else ''}) block {wact}..{wend} ({wend - wact} B)")

    # 3. remap the pool; strings the host lacks are appended to Apt1
    pcnt, _ = pools.pop()
    dpool = block_pool(dd, src)
    index = {}
    for i, s in enumerate(mconsts):
        if s is not None and s not in index:
            index[s] = i
    new_strings, newpool = [], []
    for g in dpool:
        s = dconsts[g]
        if s is None:
            fail(f"non-string constant {g} in the {P['cls']} pool")
        if s not in index:
            index[s] = mcnt + len(new_strings)
            new_strings.append(s)
        newpool.append(index[s])
    n = len(new_strings)
    shift = 16 * n
    old_str_start = 48 + 16 * mcnt
    body = bytearray(ma[old_str_start:])
    new_ents = [(t, v + shift) for t, v in ments]
    base = old_str_start + shift
    for s in new_strings:
        body += b"\0" * ((-len(body)) % 8)
        new_ents.append((1, base + len(body)))
        body += s + b"\0"
    na = bytearray(ma[:48])
    struct.pack_into("<Q", na, 0x20, mcnt + n)
    for t, v in new_ents:
        na += struct.pack("<QQ", t, v)
    assert len(na) == base
    na += body
    chk = const_strings(bytes(na))
    if chk[:mcnt] != mconsts or chk[mcnt:] != new_strings:
        fail("Apt1 rebuild check failed")
    print(f"pool: {pcnt} strings, {pcnt - n} already in host, {n} appended to Apt1 ({mcnt} -> {mcnt + n})")

    # 4. append the combined block and its relocated pointers to Apt Data
    out = bytearray(md)
    out += b"\0" * ((-len(out)) % 8)
    region = len(out)
    assert len(out) % 8 == 0
    out += b"\0" * (wact % 8)                                  # keep the anchor block's alignment
    c0 = len(out)
    out += md[wact:wend]
    gap = (src - len(out)) % 8
    out += {0: b"", 1: bytes.fromhex("591217" * 3), 2: b"\x59\x17",
            3: b"\x59\x12\x17", 4: b"\x59\x17\x59\x17", 5: b"\x59\x17\x59\x12\x17",
            6: b"\x59\x12\x17\x59\x12\x17", 7: b"\x59\x17\x59\x17\x59\x12\x17"}[gap]  # push0;Pop / push0;Not;Pop
    assert len(out) % 8 == src % 8
    c1 = len(out)
    out += dd[src:src_end]
    delta = c1 - src

    def put(b):
        out.extend(b"\0" * ((-len(out)) % 8))
        at = len(out)
        out.extend(b)
        return at

    new_pool_ptr = put(struct.pack("<%dQ" % pcnt, *newpool))
    relocs = 0
    for a, op, o, _ in ops:
        if op == 0x88:
            struct.pack_into("<Q", out, o + delta + 8, new_pool_ptr); relocs += 1
        elif op in (0x8e, 0x9b):
            name = cstr(dd, q(dd, o))
            argp = q(dd, o + 16)
            nargs = struct.unpack_from("<I", dd, o + 8)[0] if op == 0x8e else q(dd, o + 8)
            name_at = put(name + b"\0")
            args = []
            for k in range(nargs):
                r0, r1 = struct.unpack_from("<QQ", dd, argp + 16 * k)
                if op == 0x8e:                                 # (register, name*)
                    args.append((r0, cstr(dd, r1)))
                else:                                          # (name*, 0)
                    if r1 != 0:
                        fail(f"DefineFunction arg record layout at {argp}")
                    args.append((None, cstr(dd, r0)))
            ptrs = [put(nm + b"\0") for _, nm in args]
            recs = bytearray()
            for (reg, _), p in zip(args, ptrs):
                recs += struct.pack("<QQ", reg, p) if op == 0x8e else struct.pack("<QQ", p, 0)
            argp_at = put(bytes(recs))
            struct.pack_into("<Q", out, o + delta, name_at)
            struct.pack_into("<Q", out, o + delta + 16, argp_at)
            relocs += 1
    out += b"\0" * ((-len(out)) % 8)
    if list(walk(out, c0))[-1][0] != c1 + (src_end - 1 - src):
        fail("combined block does not end at the copied End")
    if bytes(out[site + delta:site + delta + len(new)]) != new:
        fail("patch not carried into the copy")
    print(f"appended {region}..{len(out)} ({len(out) - region} B): combined block @{c0}, "
          f"{P['cls'].rsplit('.', 1)[1]} @{c1}, filler {gap} B, {relocs} relocated ops, pool @{new_pool_ptr}")

    # 5. redirect frame 0's anchor InitAction to the combined block
    if growth_only:
        print("--growth-only: anchor InitAction left pointing at the original block")
    else:
        if q(out, witem + 16) != wact:
            fail("anchor InitAction pointer moved")
        struct.pack_into("<Q", out, witem + 16, c0)
        print(f"anchor InitAction item@{witem}+16: {wact} -> {c0}")
    ma_e.dec = bytes(na)
    md_e.dec = bytes(out)
    host.write(out_path)
    print(f"wrote {out_path} ({os.path.getsize(out_path)} B)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("preset", choices=sorted(PRESETS))
    ap.add_argument("host", help="node_com/main.ast (offline-warning) or patched node_com/scriptpod.ast (skill-upgrade-success)")
    ap.add_argument("donor", help="original node_cfm/hub/corenode.ast or node_cfm/corenode.ast (same title update)")
    ap.add_argument("out", help="patched host file to write")
    ap.add_argument("--growth-only", action="store_true",
                    help="append everything but don't redirect the InitAction (load test)")
    a = ap.parse_args(argv)
    build(a.preset, a.host, a.donor, a.out, a.growth_only)


if __name__ == "__main__":
    main()
