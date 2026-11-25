# Building the lemonadep 6.18 kernel

`build.sh` builds the kernel, vendor modules, `dtbo.img` and a flashable
AnyKernel3 zip on an x86_64 Linux host. It downloads a pinned Android
toolchain, so host-wide compiler installation is not required.

The current tree is a **build-system scaffold**. A successful compile does not
yet mean the result is safe or functional on OnePlus 9 Pro hardware; see
[PORTING.md](PORTING.md).

## Requirements

- x86_64 Linux
- about 25 GB free disk for toolchain and build output
- 8 GB RAM or more (reduce `JOBS` on smaller machines)
- common kernel build packages:

```sh
# Debian / Ubuntu
sudo apt install git make bc bison flex python3 perl rsync cpio curl zip unzip lz4 \
    build-essential kmod erofs-utils libssl-dev libelf-dev zlib1g-dev

# Arch
sudo pacman -S --needed git make bc bison flex python perl rsync cpio curl zip unzip lz4 \
    base-devel kmod openssl libelf zlib

# Fedora
sudo dnf install git make bc bison flex python3 perl rsync cpio curl zip unzip lz4 \
    gcc kmod openssl-devel elfutils-libelf-devel zlib-devel
```

## Sync and build through repo

```sh
repo init -u https://github.com/blahajcoding/android_kernel_manifest.git -b android17-6.18-lemonadep
repo sync --force-sync --no-clone-bundle --current-branch --no-tags -j$(nproc --all)
cd kernel/lemonadep-6.18
./build.sh
```

The script detects these sibling projects:

```text
kernel/lemonadep-6.18
kernel/lemonadep-6.18-modules
kernel/lemonadep-6.18-devicetrees
```

and builds directly against them. Output goes to `lemonadep-618-build` next to
the kernel checkout unless `WORK` is set. In a repo workspace, set for example:

```sh
WORK=$PWD/../../out/lemonadep-6.18 ./build.sh
```

to keep output at the top level of the workspace.

## Steps

| Step | What it does |
|---|---|
| `tools` | Downloads pinned Clang r596125, Rust 1.88.0, bindgen 0.72.1, pahole, mkdtboimg, mkbootimg/unpack_bootimg and AnyKernel3 |
| `kernel` | Configures with `gki_defconfig + vendor/lemonadep.config`, builds `Image` and in-tree modules |
| `modules` | Builds vendor modules and collects/strips the shipped module set |
| `vendor_dlkm` | Builds the small EROFS `vendor_dlkm.img` containing the deferred CNSS/qcacld WLAN modules |
| `dtbo` | Builds devicetree overlays and `dtbo.img` |
| `zip` | Packs `Image`, modules, `vendor_dlkm.img` and `dtbo.img` into an AnyKernel3 zip |
| `migrate` | Repacks dumped crDroid `boot`/`vendor_boot` images into offline inactive-slot migration images |
| `clean` | Removes build output while keeping toolchains and source checkouts |

Examples:

```sh
./build.sh                 # all steps
./build.sh kernel          # only the kernel
./build.sh modules dtbo    # selected steps in order
JOBS=4 ./build.sh kernel   # lower parallelism
```

## Options

| Variable | Default | Meaning |
|---|---|---|
| `WORK` | sibling `lemonadep-618-build` | Work/output directory |
| `TC` | `$WORK/toolchain` | Toolchain directory |
| `JOBS` | CPU count | Parallel build jobs |
| `BUILD_NUMBER` | `1` | Kernel build number |
| `BUILD_USER`, `BUILD_HOST` | `build-user`, `build-host` | `/proc/version` identity |
| `KBUILD_BUILD_TIMESTAMP` | fixed epoch timestamp | Kernel build timestamp; override to reproduce a release timestamp exactly |
| `MODULES_REF`, `DT_REF` | `lemonadep/initial-scaffold` | Branch cloned when sibling sources are absent; tracks the open checkpoint PRs until they merge |
| `BOOT_IMG`, `VENDOR_BOOT_IMG` | unset, required for `migrate` | Dumped crDroid boot images used as migration input |
| `EXTRA_BOOTARGS` | empty | Extra kernel arguments appended to the input boot image cmdline by `migrate` |
| `MODSRC`, `DTSRC` | sibling checkout or `$WORK` clone | Explicit module/devicetree source locations |
| `CLANG_DIR` | downloaded toolchain | Existing Android Clang installation |
| `PAHOLE` | downloaded binary | Existing Android-compatible pahole |

## Output

`$WORK/dist` contains:

- `Image`
- `dtbo.img`
- `vendor-dtbs.img`, the concatenated Lahaina v1/v2/v2.1 base devicetrees in
  the same order as stock `vendor_boot`. The zip carries it as `dtb` and the
  AnyKernel script repacks the existing `vendor_boot` with it while preserving
  that image's vendor ramdisk and cmdline.
- `lahaina-v2.1.dtb`, the intermediate merged base devicetree used for
  debugging/devicetree inspection. It is also carried in the zip for
  convenience, but is not flashed directly.
- `modules/` with stripped `.ko` files, `modules.load`, `modules.blocklist`,
  `modules.options` and depmod metadata
- `vendor_dlkm.img`, an EROFS image whose `lib/modules` directory contains the
  ten deferred CNSS/qcacld modules, dependency-ordered `modules.load`,
  `/vendor/lib/modules/`-prefixed `modules.dep`, aliases and the qcacld
  blocklist. crDroid mounts `vendor_dlkm` as EROFS at `/vendor_dlkm`; its
  `/vendor/lib/modules` path then gives second-stage init the modules that
  disappear with the first-stage boot ramdisk.
- `LemonadepKernel-<version>-lemonadep-<date>.zip`

Do not mix a new `Image` with modules from another kernel sublevel. Rebuild all
steps after every ACK or configuration change.


## Offline crDroid migration images

The AnyKernel zip remains an updater for a ROM that is already running this
6.18 kernel. For the first migration from crDroid's 5.4 kernel, build offline
images instead:

```sh
BOOT_IMG=/path/to/boot.img VENDOR_BOOT_IMG=/path/to/vendor_boot.img ./build.sh migrate
```

The two input images must be dumps from the same working crDroid slot. The
step writes `boot.img`, `vendor_boot.img`, `dtbo.img`, `vendor_dlkm.img` and
`SHA256SUMS.txt` to `$WORK/dist/migration`.

The migration repack deliberately preserves the input vendor ramdisks,
bootconfig, vendor cmdline and boot cmdline. It changes only:

- the boot kernel, replaced with the 6.18 `Image`;
- the boot ramdisk, which gains `/lib/modules/<kernel-release>` with the 6.18
  module payload. Android first-stage init prefers this exact-release
  directory over the old 5.4 module directories in the vendor ramdisk;
- the vendor_boot DTB, replaced with the concatenated 6.18 Lahaina v1/v2/v2.1
  base devicetrees;
- `vendor_dlkm.img` is not derived from the input images. It is the newly
  built 6.18 WLAN module partition and must be flashed alongside the inactive
  slot images when testing wireless.

The 6.18 base bootargs are already in the base devicetree, while
`androidboot.hardware=qcom` and the other crDroid arguments remain in the
preserved vendor_boot cmdline. Set `EXTRA_BOOTARGS` only for a focused boot
experiment; it is appended to the original boot cmdline rather than replacing
it.

If the input boot ramdisk was wrapped by an old KernelSU loader, the migration
image unwraps `/init.real` and drops the incompatible old `kernelsu.ko`. Root
is therefore not preserved in that migration boot. This is intentional: a
kernel module built for 5.4 cannot be loaded into 6.18.

Flash the output only to the inactive slot, leaving the working slot as the
fallback, after backing up all three original partitions and slot a's `vendor_dlkm`. Because crDroid uses
Virtual A/B, first confirm that the inactive slot actually has its logical
partitions: `fastboot getvar all` should list the relevant `is-logical:*_b`
entries when slot `b` is the target, and `vbmeta_b` should report disabled
verification flags. If those logical partitions are missing, restore the same
crDroid build to slot b first instead of flashing only these three images.

For the first diagnostic attempt, use
`EXTRA_BOOTARGS="androidboot.first_stage_console=2"` when the crDroid build is
`ro.debuggable=1`; otherwise the option is ignored. A first-stage module failure
is otherwise difficult to distinguish from a bootloader memory or partition
failure. `migrate618.py` prints the kernel arm64 `image_size`, compressed boot
and vendor ramdisk sizes, two 1 MiB DT slots and their total; treat a total
above 80 MiB as a warning because the default bootloader memory region is about
86 MiB.

For example, if the inactive slot is `b`:

```sh
fastboot reboot fastboot
fastboot flash vendor_dlkm_b vendor_dlkm.img
fastboot reboot bootloader
fastboot flash boot_b boot.img
fastboot flash vendor_boot_b vendor_boot.img
fastboot flash dtbo_b dtbo.img
fastboot --set-active=b
```

Do not flash both slots. If the device refuses the images because of verified
boot policy, stop and keep the original slot; migration does not bypass or
re-sign Android Verified Boot. A successful first migration test should reach
adb, contain both the 6.18 devicetree bootargs and
`androidboot.hardware=qcom` in `/proc/cmdline`, report lemonadep in
`/proc/device-tree/model`, and mount userdata.

## Safety

Do not flash the current scaffold to a daily-use phone. Before hardware tests,
confirm the port status in [PORTING.md](PORTING.md), keep fastboot access, and
back up the working `boot`, `vendor_boot` and `dtbo` partitions. The installer
now rewrites all three partitions; the `vendor_boot` rewrite is required because
the stock 5.4 base DTBs do not match the 6.18 overlay/module ABI.
