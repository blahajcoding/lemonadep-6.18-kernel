# Linux 6.18 for OnePlus 9 Pro (lemonadep)

Kernel source for the **OnePlus 9 Pro** (`lemonadep`, Snapdragon 888 /
SM8350 "lahaina") forward-port onto Android Common Kernel 6.18.

This repository starts from Suvojeet Sengupta's working Lahaina/Yupik 6.18
architecture for Xiaomi `redwood`: ACK `android17-6.18` plus `android17-6.18-lts`,
Qualcomm's Lahaina platform delta, a GKI built-in kernel, and platform/board
drivers shipped as modules. lemonadep-specific work is being ported on top of
that base; the old OnePlus SM8350 5.4 kernel is a reference, not a merge base.

| | |
|---|---|
| Version | Linux 6.18.63 |
| Base | ACK `android17-6.18`, with `android17-6.18-lts` merged in |
| Platform | Qualcomm Lahaina/SM8350, GKI core plus modular vendor drivers |
| Config | `gki_defconfig` + `vendor/lemonadep.config` |
| Toolchain | Android Clang 22.0.2 (r596125), Rust 1.88.0, bindgen 0.72.1 |
| Status | **Build-system scaffold; not yet validated on lemonadep hardware** |

## Repositories

| Repository | Contents |
|---|---|
| **lemonadep-6.18-kernel** (this one) | The kernel and top-level build script |
| [lemonadep-6.18-modules](https://github.com/blahajcoding/lemonadep-6.18-modules) | Qualcomm vendor modules and lemonadep board modules |
| [lemonadep-6.18-devicetrees](https://github.com/blahajcoding/lemonadep-6.18-devicetrees) | Lahaina base devicetrees and lemonadep board overlays |
| [android_kernel_manifest](https://github.com/blahajcoding/android_kernel_manifest/tree/android17-6.18-lemonadep) | repo manifest for syncing all three source trees |

## Current port status

The initial tree intentionally inherits the redwood 6.18 build architecture so
the kernel and Qualcomm platform modules can be compiled while lemonadep board
support is ported incrementally. The inherited module list and devicetree
workflow are **not yet a working OnePlus 9 Pro product**.

Near-term milestones are tracked in [PORTING.md](PORTING.md). Nothing is
silently stubbed out: hardware whose drivers have not been forward-ported is
listed there and in the relevant pull request.

## Syncing with repo

```sh
repo init -u https://github.com/blahajcoding/android_kernel_manifest.git -b android17-6.18-lemonadep
repo sync --force-sync --no-clone-bundle --current-branch --no-tags -j$(nproc --all)
cd kernel/lemonadep-6.18
./build.sh
```

In a repo workspace the script uses the sibling module and devicetree
checkouts. In a stand-alone clone it clones the published module/devicetree
repositories into its work directory.

See [BUILDING.md](BUILDING.md) for host requirements, build steps, options and
output layout.

## Updating

`main` should follow ACK `android17-6.18` and `android17-6.18-lts`. Every new
stable sublevel changes module vermagic, so the `Image` and all modules must be
rebuilt together.

## Credits

- Google, for the Android Common Kernel
- Qualcomm (CodeLinaro), for the Lahaina platform
- Suvojeet Sengupta, for the redwood 6.18 architecture and API migration work
- OnePlus/OPLUS and the crDroid SM8350 maintainers, for the lemonadep 5.4
  hardware support used as the forward-porting reference
- The Linux kernel community

The original ACK contribution guide is in [README.ACK.md](README.ACK.md).

## License

GPL-2.0, like the Linux kernel. See [COPYING](COPYING).
