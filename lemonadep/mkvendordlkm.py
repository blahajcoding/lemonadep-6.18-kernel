#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build lemonadep's small post-first-stage vendor_dlkm image."""

import argparse
import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path

VENDOR_MODULE_ROOT = "/vendor/lib/modules"


def die(msg):
    raise SystemExit(f"error: {msg}")


def read_names(path):
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def module_name(name):
    return name[:-3] if name.endswith(".ko") else name


def parse_dep(text):
    deps = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        left, sep, right = line.partition(":")
        if not sep:
            continue
        deps[os.path.basename(left.strip())] = [os.path.basename(x) for x in right.split()]
    return deps


def topo_order(modules, deps):
    selected = set(modules)
    result = []
    state = {}

    def visit(mod, stack):
        mark = state.get(mod)
        if mark == "done":
            return
        if mark == "visiting":
            die(f"dependency cycle among vendor_dlkm modules: {' -> '.join(stack + [mod])}")
        state[mod] = "visiting"
        for dep in deps.get(mod, []):
            if dep in selected:
                visit(dep, stack + [mod])
        state[mod] = "done"
        result.append(mod)

    for mod in modules:
        visit(mod, [])
    return result


def write_tar(root, tar_path):
    with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            info = tar.gettarinfo(str(path), arcname=str(rel))
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            if path.is_file():
                with path.open("rb") as f:
                    tar.addfile(info, f)
            else:
                tar.addfile(info)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules-dir", type=Path, required=True)
    ap.add_argument("--modules-list", type=Path, required=True)
    ap.add_argument("--first-stage-load", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--size-mib", type=int, default=32)
    ap.add_argument("--work-dir", type=Path)
    args = ap.parse_args()

    src = args.modules_dir
    dep_path = src / "modules.dep"
    if not dep_path.is_file():
        die(f"missing {dep_path}")

    all_modules = [module_name(x) + ".ko" for x in read_names(args.modules_list)]
    first_stage = {module_name(x) + ".ko" for x in read_names(args.first_stage_load)}
    deferred = [x for x in all_modules if x not in first_stage]
    if "qca_cld3_wlan.ko" not in deferred or "cnss2.ko" not in deferred:
        die(f"unexpected vendor_dlkm module set: {deferred}")

    deps = parse_dep(dep_path.read_text())
    missing = [x for x in deferred if not (src / x).is_file()]
    if missing:
        die(f"missing module files: {' '.join(missing)}")

    # The boot-ramdisk modules are already loaded when crDroid modprobes WLAN.
    # Keep the vendor image small and retain only dependency edges within this
    # deferred set; absent edges therefore cannot make modprobe look for files
    # that disappeared with the first-stage ramdisk.
    order = topo_order(deferred, deps)
    selected = set(order)
    external = {dep for mod in order for dep in deps.get(mod, []) if dep not in selected}
    not_first_stage = sorted(external - first_stage)
    if not_first_stage:
        die("wireless dependencies missing from first-stage modules.load: " + " ".join(not_first_stage))

    tmp_ctx = tempfile.TemporaryDirectory(prefix="vendor-dlkm-") if args.work_dir is None else None
    work = Path(tmp_ctx.name) if tmp_ctx else args.work_dir
    root = work / "root"
    modroot = root / "lib" / "modules"
    shutil.rmtree(root, ignore_errors=True)
    modroot.mkdir(parents=True)

    for name in order:
        shutil.copy2(src / name, modroot / name)
        os.chmod(modroot / name, 0o644)

    lines = []
    for name in order:
        left = f"{VENDOR_MODULE_ROOT}/{name}"
        internal = [x for x in deps.get(name, []) if x in set(order)]
        right = "".join(f" {VENDOR_MODULE_ROOT}/{x}" for x in internal)
        lines.append(f"{left}:{right}\n")
    (modroot / "modules.dep").write_text("".join(lines))

    selected_names = {x[:-3] for x in order}
    if (src / "modules.alias").is_file():
        aliases = []
        for line in (src / "modules.alias").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "alias" and parts[-1] in selected_names:
                aliases.append(line + "\n")
        (modroot / "modules.alias").write_text("".join(aliases))

    if (src / "modules.softdep").is_file():
        softdeps = []
        for line in (src / "modules.softdep").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "softdep" and parts[1] in selected_names:
                softdeps.append(line + "\n")
        (modroot / "modules.softdep").write_text("".join(softdeps))

    load_order = [x for x in order if x != "qca_cld3_wlan.ko"]
    (modroot / "modules.load").write_text("".join(f"{x}\n" for x in load_order))
    blocklist = src / "modules.blocklist"
    shutil.copy2(blocklist, modroot / "modules.blocklist") if blocklist.is_file() else (modroot / "modules.blocklist").write_text("")
    options = src / "modules.options"
    shutil.copy2(options, modroot / "modules.options") if options.is_file() else (modroot / "modules.options").write_text("")

    for path in modroot.iterdir():
        if path.is_file():
            os.chmod(path, 0o644)
    os.chmod(root / "lib", 0o755)
    os.chmod(modroot, 0o755)

    contexts = work / "file_contexts"
    contexts.write_text(
        "/(vendor_dlkm|vendor/vendor_dlkm|system/vendor/vendor_dlkm)(/.*)? "
        "u:object_r:vendor_file:s0\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.unlink(missing_ok=True)
    subprocess.run(
        [
            "mkfs.erofs",
            "-zlz4hc",
            "-T0",
            "--all-root",
            "--mount-point=/vendor_dlkm",
            f"--file-contexts={contexts}",
            str(args.output),
            str(root),
        ],
        check=True,
    )

    used = sum((modroot / x).stat().st_size for x in order)
    print(f"vendor_dlkm: {len(order)} modules, {used / 1048576:.1f} MiB of modules, image {args.output}")
    print("modules: " + " ".join(x[:-3] for x in order))


if __name__ == "__main__":
    main()
