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
sudo apt install git make bc bison flex python3 perl rsync cpio curl zip unzip \
    build-essential kmod libssl-dev libelf-dev zlib1g-dev

# Arch
sudo pacman -S --needed git make bc bison flex python perl rsync cpio curl zip unzip \
    base-devel kmod openssl libelf zlib

# Fedora
sudo dnf install git make bc bison flex python3 perl rsync cpio curl zip unzip \
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
| `tools` | Downloads pinned Clang r596125, Rust 1.88.0, bindgen 0.72.1, pahole, mkdtboimg and AnyKernel3 |
| `kernel` | Configures with `gki_defconfig + vendor/lemonadep.config`, builds `Image` and in-tree modules |
| `modules` | Builds vendor modules and collects/strips the shipped module set |
| `dtbo` | Builds devicetree overlays and `dtbo.img` |
| `zip` | Packs `Image`, modules and `dtbo.img` into an AnyKernel3 zip |
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
| `MODULES_REF`, `DT_REF` | `main` | Branch cloned when sibling sources are absent |
| `MODSRC`, `DTSRC` | sibling checkout or `$WORK` clone | Explicit module/devicetree source locations |
| `CLANG_DIR` | downloaded toolchain | Existing Android Clang installation |
| `PAHOLE` | downloaded binary | Existing Android-compatible pahole |

## Output

`$WORK/dist` contains:

- `Image`
- `dtbo.img`
- `modules/` with stripped `.ko` files, `modules.load`, `modules.blocklist`,
  `modules.options` and depmod metadata
- `LemonadepKernel-<version>-lemonadep-<date>.zip`

Do not mix a new `Image` with modules from another kernel sublevel. Rebuild all
steps after every ACK or configuration change.

## Safety

Do not flash the current scaffold to a daily-use phone. Before hardware tests,
confirm the port status in [PORTING.md](PORTING.md), keep fastboot access, and
back up the working `boot`, `vendor_boot` and `dtbo` partitions.
