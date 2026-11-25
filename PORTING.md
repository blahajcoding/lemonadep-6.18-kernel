# lemonadep 6.18 forward-porting plan and deferred hardware

This file is the working contract for the port. It exists so missing hardware
support is explicit instead of being hidden behind disabled Kconfig symbols or
empty driver stubs.

## Porting rule

Forward-port only: implement lemonadep support on ACK 6.18. Do not merge ACK
6.18 back into the old SM8350 5.4 kernel and do not carry over large OPLUS
core-kernel modifications without a demonstrated userspace or hardware need.

## Milestones

1. **Build architecture scaffold** — fork the working Lahaina/Yupik 6.18
   decomposition, rename the product integration to lemonadep, publish a repo
   manifest, and compile the inherited kernel/platform baseline.
2. **Lahaina/SM8350 core product** — prune Yupik/Xiaomi board policy, keep the
   SM8350 clock/pinctrl/UFS/interconnect/remoteproc path, and produce a boot
   image/module set suitable for first hardware testing.
3. **lemonadep devicetree** — port `lemonadep-19815-overlay.dts` and the T0
   variant, including display, touch, audio, camera, charging, NFC, fingerprint
   and reserved-memory nodes, validating bindings against the 6.18 drivers.
4. **Core peripheral drivers** — display/SDE/DSI and panel first, then touch,
   USB role/charger interaction, remote processors, audio, WLAN/Bluetooth,
   mobile data, video, camera, fingerprint, haptics, alert slider and sensors.
5. **Android integration** — module ordering/blocklist, recovery modules,
   vendor_boot/dtbo packaging, SELinux compatibility, deep sleep, thermal and
   charging validation.

## Hardware support matrix

| Block | 5.4 lemonadep source of truth | 6.18 plan | Current state |
|---|---|---|---|
| Boot, UFS, clocks, pinctrl, interconnect | Qualcomm Lahaina QGKI | Reuse redwood's 6.18 Lahaina platform and SM8350 clock drivers | Inherited; untested on lemonadep |
| Display/panel | `techpack/display`, `dsi-panel-samsung-amb670yf01*` and OPLUS 20031 panel DT | Reuse redwood's 6.18 SDE/DRM port; port lemonadep panel timing/OPLUS additions | Deferred; redwood panel must not be treated as lemonadep support |
| Touch | `drivers/input/touchscreen/oplus_touchscreen_v2`, Synaptics S3908 | Port OPLUS touch framework and Synaptics TCM-oncell driver | Deferred; inherited redwood Goodix/Focaltech drivers are not a replacement |
| Fingerprint | `drivers/input/oplus_fp_drivers`, Goodix optical G3S | Port OPLUS fingerprint common/Goodix optical stack with display/UDFPS coordination | Deferred |
| Audio | Lahaina ASoC techpack, WCD938x, dual NXP TFA98xx | Reuse 6.18 Qualcomm audio platform; port lemonadep machine/amp configuration | Deferred; redwood AW88261 configuration is not correct for lemonadep |
| Camera | Spectra `camera.ko`, OPLUS sensor/OIS/EEPROM adaptations | Reuse 6.18 Spectra base; port lemonadep camera DT and OPLUS sensor logic | Deferred |
| WLAN/Bluetooth | QCA6490, qcacld-3.0, CNSS, btpower/bt_fm_slim | Reuse redwood's Lahaina-profile 6.18 WLAN/CNSS port; validate QCA6490 firmware and board DT | Inherited platform work; lemonadep validation pending |
| Mobile data | IPA, datarmnet, rmnet offload/SHS | Reuse redwood's 6.18 data stack; adapt subsystem compatibility paths to Lahaina | Inherited platform work; validation pending |
| Video | downstream `msm-vidc` | Reuse redwood's 6.18 msm-vidc port and validate SM8350 firmware/UAPI | Inherited platform work; validation pending |
| Charging | `drivers/power/oplus_chg`, MP2650, RK826/OP10 Warp, HL7227, P9415 wireless | Port OPLUS charging stack only after basic power-supply/thermal safety works | Deferred; do not enable high-current charging early |
| Haptics | AW8697 | Compare stock OPLUS driver with redwood's 6.18 AW8697 port and keep the ABI lemonadep userspace expects | Needs analysis; not yet productized |
| Alert slider | `drivers/misc/tri_state_key`, IST8801/MXM1120 Hall sensors | Port as lemonadep board modules | Deferred |
| NFC | SN100T / NQ-NCI | Port the lemonadep NFC driver/DT; redwood `nxp-nci` is only a reference | Deferred |
| Sensors/devinfo | OPLUS sensor feedback/devinfo and SAR/proximity/ALS configuration | Port after core input/power/devicetree is stable | Deferred |
| OPLUS performance/secureguard extras | `vendor/oplus/kernel/*` superset | Port only when a userspace dependency is proven | Deferred by default |

## Explicitly deferred or excluded inherited pieces

These are present in the upstream redwood reference but are not lemonadep
support. They must be removed or replaced before a hardware release:

- Xiaomi touch drivers (`focaltech_touch`, `xiaomi_touch`, Goodix Berlin touch)
- Xiaomi fingerprint glue (`xiaomi_fp`, redwood-specific `goodix_fp`)
- Xiaomi speaker calibration/driver glue (`snd-soc-aw88261`, AW88395 library)
- Xiaomi thermal interface (`mi_thermal`)
- IR blaster driver (`ir-spi`), because OnePlus 9 Pro has no IR blaster
- redwood board devicetree and panel descriptions
- redwood-specific charger policy embedded in Qualcomm's battery charger driver
- redwood splash-console defaults (disabled until lemonadep framebuffer base,
  stride and 1440x3216 panel geometry are validated)
- redwood vendor-compatibility shims (`subsys_compat`, `ioncompat`, `usbrole`,
  `frpc-adsprpc`) and test-only logging/guard modules, which require OnePlus
  userspace/SELinux audit before use
- legacy `msm-vidc` compatibility packaging until the lemonadep Codec2 ABI is
  confirmed against the OnePlus vendor image

The first scaffold may still compile some of these inherited objects while the
replacement structure is being created. They are build artifacts only, not
claimed lemonadep functionality.

## Compile-fix documentation rule

Every pull request that cannot yet support a hardware block must say so in its
description. Do not remove a driver solely because it fails to compile unless
the PR explains the replacement plan and updates this matrix.
