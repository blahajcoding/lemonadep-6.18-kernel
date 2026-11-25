#!/usr/bin/env python3
"""Build offline crDroid-to-6.18 migration images for lemonadep.

The inputs are a dumped crDroid boot image and vendor_boot image.  The boot
image keeps its generic ramdisk and init, gains the versioned 6.18 module
directory used by Android first-stage init, and receives the 6.18 kernel.  The
vendor_boot image keeps every ramdisk fragment, bootconfig and cmdline, with
only its base DTB replaced by the concatenated 6.18 Lahaina DTBs.
"""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zlib

BOOT_IMAGE_LIMIT = 201326592
VENDOR_BOOT_IMAGE_LIMIT = 201326592
DTBO_IMAGE_LIMIT = 25165824

CPIO_MAGICS = (b"070701", b"070702")
GZIP_MAGIC = b"\x1f\x8b"
LZ4_LEGACY_MAGIC = b"\x02\x21\x4c\x18"
LZ4_FRAME_MAGIC = b"\x04\x22\x4d\x18"


def die(message):
    raise SystemExit(f"migrate618: error: {message}")


def run(argv, **kwargs):
    try:
        return subprocess.run([str(a) for a in argv], check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        die(f"command failed with status {exc.returncode}: {' '.join(str(a) for a in argv)}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def unpack_args(tools_dir, image, out_dir):
    result = run(
        [
            sys.executable,
            tools_dir / "unpack_bootimg.py",
            "--boot_img",
            image,
            "--out",
            out_dir,
            "--format=mkbootimg",
            "-0",
        ],
        stdout=subprocess.PIPE,
    )
    fields = result.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    return [field.decode() for field in fields]


def arg_value(args, option):
    for i, arg in enumerate(args[:-1]):
        if arg == option:
            return args[i + 1]
    return None


def header_version(args):
    value = arg_value(args, "--header_version")
    if value is None:
        die("unpack_bootimg did not report a header version")
    return int(value)


def replace_option(args, option, value, required=True):
    out = []
    replaced = False
    i = 0
    while i < len(args):
        if args[i] == option:
            if i + 1 >= len(args):
                die(f"{option} has no value in unpack_bootimg output")
            out.extend([option, str(value)])
            i += 2
            replaced = True
        else:
            out.append(args[i])
            i += 1
    if not replaced:
        if required:
            die(f"{option} was not present in unpack_bootimg output")
        out.extend([option, str(value)])
    return out


def append_extra_bootargs(args, extra):
    if not extra:
        return args
    out = list(args)
    for i, arg in enumerate(out[:-1]):
        if arg == "--cmdline":
            old = out[i + 1].strip()
            out[i + 1] = (old + " " + extra.strip()).strip()
            return out
    die("--cmdline was not present in the boot image arguments")


def compression_kind(path):
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic.startswith(GZIP_MAGIC):
        return "gzip"
    if magic.startswith(LZ4_LEGACY_MAGIC):
        return "lz4-legacy"
    if magic.startswith(LZ4_FRAME_MAGIC):
        return "lz4"
    if magic.startswith(CPIO_MAGICS):
        return "none"
    die(f"unsupported ramdisk compression magic {magic.hex()} in {path}")


def gunzip_concatenated(data):
    output = []
    rest = data
    while rest.startswith(GZIP_MAGIC):
        dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
        part = dec.decompress(rest)
        part += dec.flush()
        if not dec.eof:
            die("truncated gzip ramdisk")
        output.append(part)
        rest = dec.unused_data
    return b"".join(output)


def decompress_ramdisk(source, output):
    kind = compression_kind(source)
    if kind == "none":
        shutil.copyfile(source, output)
    elif kind == "gzip":
        output.write_bytes(gunzip_concatenated(source.read_bytes()))
    elif kind in ("lz4", "lz4-legacy"):
        with open(output, "wb") as out:
            run(["lz4", "-dc", source], stdout=out)
    with open(output, "rb") as f:
        if not f.read(6) in CPIO_MAGICS:
            die(f"decompressed ramdisk from {source} is not a newc/crc cpio archive")
    return kind


def cpio_verbose_listing(cpio_file):
    with open(cpio_file, "rb") as inp:
        result = run(["cpio", "-itv", "--quiet"], stdin=inp, stdout=subprocess.PIPE)
    return result.stdout.decode(errors="replace").splitlines()


def cpio_names(cpio_file):
    with open(cpio_file, "rb") as inp:
        result = run(["cpio", "-it", "--quiet"], stdin=inp, stdout=subprocess.PIPE)
    names = result.stdout.decode(errors="replace").splitlines()
    return [name[2:] if name.startswith("./") else name for name in names]


def extract_cpio(cpio_file, destination):
    special = [line for line in cpio_verbose_listing(cpio_file) if line[:1] in ("b", "c")]
    if special and os.geteuid() != 0:
        die(
            "the boot ramdisk contains device nodes and must be unpacked as root: "
            + special[0].split()[-1]
        )
    destination.mkdir(parents=True, exist_ok=True)
    with open(cpio_file, "rb") as inp:
        run(["cpio", "-id", "--quiet"], cwd=destination, stdin=inp)


def cpio_paths(root):
    paths = ["."]
    for current, dirs, files in os.walk(root):
        dirs.sort()
        files.sort()
        rel_current = Path(current).relative_to(root)
        for name in dirs + files:
            rel = rel_current / name
            paths.append("./" + rel.as_posix())
    return paths


def create_cpio(root, output):
    listing = "\n".join(cpio_paths(root)) + "\n"
    with open(output, "wb") as out:
        run(
            ["cpio", "-o", "-H", "newc", "-R", "0:0", "--quiet"],
            cwd=root,
            input=listing.encode(),
            stdout=out,
        )


def compress_ramdisk(cpio_file, output, kind):
    if kind == "none":
        shutil.copyfile(cpio_file, output)
    elif kind == "gzip":
        with open(output, "wb") as out:
            run(["gzip", "-9", "-n", "-c", cpio_file], stdout=out)
    elif kind == "lz4-legacy":
        with open(output, "wb") as out:
            run(["lz4", "-l", "-12", "--favor-decSpeed", "-q", "-c", cpio_file], stdout=out)
    elif kind == "lz4":
        with open(output, "wb") as out:
            run(["lz4", "-12", "--favor-decSpeed", "-q", "-c", cpio_file], stdout=out)
    else:
        die(f"internal error: unknown compression kind {kind}")


def unwrap_kernelsu_ramdisk(ramdisk_root):
    init_real = ramdisk_root / "init.real"
    if not init_real.exists():
        return False
    for name in ("init", "kernelsu.ko", "ksu_config"):
        path = ramdisk_root / name
        if path.exists() or path.is_symlink():
            path.unlink()
    shutil.move(str(init_real), str(ramdisk_root / "init"))
    return True


def install_modules(modules_dir, ramdisk_root, release):
    required = [
        "modules.load",
        "modules.dep",
        "modules.alias",
        "modules.softdep",
        "modules.blocklist",
        "modules.options",
    ]
    missing = [name for name in required if not (modules_dir / name).is_file()]
    if missing:
        die(f"module metadata missing from {modules_dir}: {', '.join(missing)}")

    module_files = sorted(modules_dir.glob("*.ko"))
    if not module_files:
        die(f"no .ko files in {modules_dir}")

    target = ramdisk_root / "lib" / "modules" / release
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for source in module_files + [modules_dir / name for name in required]:
        shutil.copyfile(source, target / source.name)
        (target / source.name).chmod(0o644)
    for directory in [ramdisk_root / "lib", ramdisk_root / "lib" / "modules", target]:
        directory.chmod(0o755)
    return target, len(module_files)


def make_boot_image(tools_dir, args, kernel, ramdisk, output, extra_bootargs):
    version = header_version(args)
    if version < 3:
        die(f"boot header v{version} is unsupported; lemonadep migration expects v3 or v4")
    args = replace_option(args, "--kernel", kernel)
    args = replace_option(args, "--ramdisk", ramdisk)
    args = append_extra_bootargs(args, extra_bootargs)
    run([sys.executable, tools_dir / "mkbootimg.py", *args, "--output", output])
    return version


def make_vendor_boot_image(tools_dir, args, dtbs, output):
    version = header_version(args)
    if version not in (3, 4):
        die(f"vendor_boot header v{version} is unsupported; expected v3 or v4")
    args = replace_option(args, "--dtb", dtbs, required=False)
    run([sys.executable, tools_dir / "mkbootimg.py", *args, "--vendor_boot", output])
    return version


def vendor_ramdisk_fragments(directory):
    single = directory / "vendor_ramdisk"
    if single.exists():
        return [single]
    return sorted(directory.glob("vendor_ramdisk[0-9][0-9]"))


def compare_fragments(original_dir, repacked_dir):
    original = vendor_ramdisk_fragments(original_dir)
    repacked = vendor_ramdisk_fragments(repacked_dir)
    if len(original) != len(repacked):
        die(f"vendor ramdisk fragment count changed: {len(original)} -> {len(repacked)}")
    for before, after in zip(original, repacked):
        if sha256(before) != sha256(after):
            die(f"vendor ramdisk fragment changed while repacking: {before.name}")
    return len(original)


def check_size(path, limit, label):
    size = path.stat().st_size
    if size > limit:
        die(f"{label} is {size} bytes, over the {limit}-byte lemonadep partition limit")
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-dir", required=True, type=Path)
    parser.add_argument("--boot", required=True, type=Path)
    parser.add_argument("--vendor-boot", required=True, type=Path)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--modules-dir", required=True, type=Path)
    parser.add_argument("--release", required=True)
    parser.add_argument("--vendor-dtbs", required=True, type=Path)
    parser.add_argument("--dtbo", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--extra-bootargs", default="")
    args = parser.parse_args()

    tools = args.tools_dir.resolve()
    for name in ("mkbootimg.py", "unpack_bootimg.py"):
        if not (tools / name).is_file():
            die(f"missing {tools / name}; run ./build.sh tools")
    for path in (args.boot, args.vendor_boot, args.kernel, args.vendor_dtbs, args.dtbo):
        if not path.is_file():
            die(f"input does not exist: {path}")
    if not args.modules_dir.is_dir():
        die(f"module directory does not exist: {args.modules_dir}")

    work = args.work_dir.resolve()
    out_dir = args.out_dir.resolve()
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    work.mkdir(parents=True)
    out_dir.mkdir(parents=True)

    boot_unpack = work / "boot-unpack"
    vendor_unpack = work / "vendor-unpack"
    boot_args = unpack_args(tools, args.boot.resolve(), boot_unpack)
    vendor_args = unpack_args(tools, args.vendor_boot.resolve(), vendor_unpack)
    boot_header = header_version(boot_args)
    vendor_header = header_version(vendor_args)
    if boot_header < 3:
        die(f"boot header v{boot_header} is unsupported; expected a GKI boot image")
    if vendor_header not in (3, 4):
        die(f"vendor_boot header v{vendor_header} is unsupported; expected v3 or v4")

    compressed = boot_unpack / "ramdisk"
    cpio_file = work / "ramdisk.cpio"
    ramdisk_kind = decompress_ramdisk(compressed, cpio_file)
    ramdisk_root = work / "ramdisk-root"
    extract_cpio(cpio_file, ramdisk_root)
    original_ramdisk_names = set(cpio_names(cpio_file))
    unwrapped = unwrap_kernelsu_ramdisk(ramdisk_root)
    module_target, module_count = install_modules(args.modules_dir.resolve(), ramdisk_root, args.release)

    new_cpio = work / "ramdisk-new.cpio"
    create_cpio(ramdisk_root, new_cpio)
    new_compressed = work / "ramdisk-new"
    compress_ramdisk(new_cpio, new_compressed, ramdisk_kind)

    boot_out = work / "boot.img"
    vendor_out = work / "vendor_boot.img"
    make_boot_image(tools, boot_args, args.kernel.resolve(), new_compressed, boot_out, args.extra_bootargs)
    make_vendor_boot_image(tools, vendor_args, args.vendor_dtbs.resolve(), vendor_out)

    # Repack validation: unpack the outputs again and verify the pieces that
    # must either change or remain byte-for-byte identical.
    boot_check = work / "boot-check"
    vendor_check = work / "vendor-check"
    check_boot_args = unpack_args(tools, boot_out, boot_check)
    check_vendor_args = unpack_args(tools, vendor_out, vendor_check)
    if sha256(boot_check / "kernel") != sha256(args.kernel):
        die("repacked boot kernel does not match the 6.18 Image")
    if sha256(vendor_check / "dtb") != sha256(args.vendor_dtbs):
        die("repacked vendor_boot DTB does not match vendor-dtbs.img")

    original_boot_cmdline = arg_value(boot_args, "--cmdline") or ""
    expected_boot_cmdline = (original_boot_cmdline.strip() + " " + args.extra_bootargs.strip()).strip()
    if (arg_value(check_boot_args, "--cmdline") or "") != expected_boot_cmdline:
        die("repacked boot cmdline does not match the input cmdline plus EXTRA_BOOTARGS")
    for option in ("--header_version", "--os_version", "--os_patch_level"):
        if arg_value(boot_args, option) != arg_value(check_boot_args, option):
            die(f"repacked boot metadata changed: {option}")

    for option in ("--header_version", "--pagesize", "--vendor_cmdline", "--board", "--dtb_offset"):
        if arg_value(vendor_args, option) != arg_value(check_vendor_args, option):
            die(f"repacked vendor_boot metadata changed: {option}")
    original_bootconfig = vendor_unpack / "bootconfig"
    if original_bootconfig.exists():
        check_bootconfig = vendor_check / "bootconfig"
        if not check_bootconfig.exists() or sha256(original_bootconfig) != sha256(check_bootconfig):
            die("vendor_boot bootconfig changed while repacking")

    fragments = compare_fragments(vendor_unpack, vendor_check)

    check_cpio = work / "ramdisk-check.cpio"
    check_kind = decompress_ramdisk(boot_check / "ramdisk", check_cpio)
    if check_kind != ramdisk_kind:
        die(f"ramdisk compression changed: {ramdisk_kind} -> {check_kind}")
    module_prefix = f"lib/modules/{args.release}/"
    names = cpio_names(check_cpio)
    name_set = set(names)
    intentionally_removed = {"init.real", "kernelsu.ko", "ksu_config"} if unwrapped else set()
    missing_entries = sorted(original_ramdisk_names - name_set - intentionally_removed)
    if missing_entries:
        die("repacked ramdisk lost original entries: " + ", ".join(missing_entries[:8]))
    packaged = sum(1 for name in names if name.startswith(module_prefix) and name.endswith(".ko"))
    if packaged != module_count:
        die(f"repacked ramdisk has {packaged}/{module_count} expected modules")
    if module_prefix + "modules.load" not in names:
        die("repacked ramdisk lacks the versioned modules.load")

    final_boot = out_dir / "boot.img"
    final_vendor = out_dir / "vendor_boot.img"
    final_dtbo = out_dir / "dtbo.img"
    final_vendor_dlkm = out_dir / "vendor_dlkm.img" if args.vendor_dlkm else None
    shutil.copyfile(boot_out, final_boot)
    shutil.copyfile(vendor_out, final_vendor)
    shutil.copyfile(args.dtbo, final_dtbo)
    if final_vendor_dlkm:
        shutil.copyfile(args.vendor_dlkm, final_vendor_dlkm)

    boot_size = check_size(final_boot, BOOT_IMAGE_LIMIT, "boot.img")
    vendor_size = check_size(final_vendor, VENDOR_BOOT_IMAGE_LIMIT, "vendor_boot.img")
    dtbo_size = check_size(final_dtbo, DTBO_IMAGE_LIMIT, "dtbo.img")

    report = [
        "lemonadep 6.18 migration images",
        f"kernel release: {args.release}",
        f"boot header: v{boot_header}; vendor_boot header: v{vendor_header}",
        f"ramdisk compression: {ramdisk_kind}",
        f"modules: {module_count} files in /lib/modules/{args.release}",
        f"vendor ramdisk fragments preserved: {fragments}",
        f"KernelSU loader unwrapped: {'yes' if unwrapped else 'no'}",
        f"extra bootargs: {args.extra_bootargs if args.extra_bootargs else '(none)'}",
        "",
        "sha256:",
    ]
    output_images = [
        ("boot.img", final_boot, boot_size),
        ("vendor_boot.img", final_vendor, vendor_size),
        ("dtbo.img", final_dtbo, dtbo_size),
    ]
    if final_vendor_dlkm:
        output_images.append(("vendor_dlkm.img", final_vendor_dlkm, final_vendor_dlkm.stat().st_size))
    for label, path, size in output_images:
        report.append(f"{sha256(path)}  {label}  ({size} bytes)")
    (out_dir / "SHA256SUMS.txt").write_text("\n".join(report) + "\n")

    print(f"migration images written to {out_dir}")
    print(f"  boot.img        {boot_size} bytes")
    print(f"  vendor_boot.img {vendor_size} bytes")
    print(f"  dtbo.img        {dtbo_size} bytes")
    if final_vendor_dlkm:
        print(f"  vendor_dlkm.img {final_vendor_dlkm.stat().st_size} bytes")
    print(f"  modules in /lib/modules/{args.release}: {module_count}")
    if unwrapped:
        print("  note: an old KernelSU loader was unwrapped because its kernel module is not compatible")


if __name__ == "__main__":
    main()
