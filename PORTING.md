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

## Devicetree packaging contract

Stock lemonadep `vendor_boot` contains three concatenated Lahaina base FDTs
(v1, v2 and v2.1), selected by `qcom,msm-id`. The stock `dtbo` contains four
OPLUS entries; lemonadep uses the T0 entry first and the production entry
second. Those overlays do **not** carry `qcom,msm-id`; the base FDT supplies
SoC revision selection. The 6.18 packaging therefore mirrors the same split:
`dtbo.img` is T0-first, while the zip carries concatenated v1/v2/v2.1 base
FDTs as `dtb` and patches them into the existing `vendor_boot` at install time.

The first lemonadep overlay checkpoint now ports the stock critical memory
reservations (`removed_mem` through `0xe1600000`, splash/dfps memory, OPLUS
boot-log/param memory and ramoops) plus stock USB/PCIe board fixes. Display,
touch, charging, audio, camera, sensors, fingerprint, NFC and pinctrl
sleep-state coverage remain incomplete; this is not yet a full stock
devicetree replacement. The QCA6490 CNSS platform node, PCIe IOMMU fastmap
partition and lemonadep NV-MAC/RF-rail overrides are now present, but they are
unproven on hardware.


The AnyKernel zip is currently an update mechanism for a ROM already running a
compatible 6.18 kernel; it intentionally keeps its 6.18-ROM guard. The first
migration path is instead the offline `./build.sh migrate` flow: it repacks a
dumped crDroid boot image with the 6.18 kernel and an exact-release
`/lib/modules/<kernel-release>` first-stage module directory, repacks the
matching vendor_boot with the 6.18 base DTBs, and emits flashable
`boot.img`/`vendor_boot.img`/`dtbo.img` plus a 6.18 `vendor_dlkm.img` for the
inactive slot. Android
first-stage init supplies the module-loading policy, so no custom PID 1 is
needed for this checkpoint. This packaging path is implemented and host-side
validated, but it remains untested on hardware; cmdline, userdata mounting,
remoteproc firmware timing, deferred probes and ramoops still require a real
inactive-slot boot test.

## Hardware support matrix

| Block | 5.4 lemonadep source of truth | 6.18 plan | Current state |
|---|---|---|---|
| Boot, UFS, clocks, pinctrl, interconnect | Qualcomm Lahaina QGKI | Reuse redwood's 6.18 Lahaina platform and SM8350 clock drivers | Inherited; lemonadep memory map/USB/PCIe scaffold ported; untested on hardware |
| Display/panel | `techpack/display`, `dsi-panel-samsung-amb670yf01*` and OPLUS 20031 panel DT | Reuse redwood's 6.18 SDE/DRM port; port lemonadep panel timing/OPLUS additions | Deferred; redwood panel must not be treated as lemonadep support |
| Touch | `drivers/input/touchscreen/oplus_touchscreen_v2`, Synaptics S3908 | Port OPLUS touch framework and Synaptics TCM-oncell driver | Deferred; inherited redwood Goodix/Focaltech drivers are not a replacement |
| Fingerprint | `drivers/input/oplus_fp_drivers`, Goodix optical G3S | Port OPLUS fingerprint common/Goodix optical stack with display/UDFPS coordination | Deferred |
| Audio | Lahaina ASoC techpack, WCD938x, dual NXP TFA98xx | Reuse 6.18 Qualcomm audio platform; port lemonadep machine/amp configuration | Deferred; redwood AW88261 configuration is not correct for lemonadep |
| Camera | Spectra `camera.ko`, OPLUS sensor/OIS/EEPROM adaptations | Reuse 6.18 Spectra base; port lemonadep camera DT and OPLUS sensor logic | Deferred; not shipped because the inherited flash/WLED providers depend on the wrong charger implementation |
| WLAN/Bluetooth | QCA6490, qcacld-3.0, CNSS, btpower/bt_fm_slim | Reuse redwood's Lahaina-profile 6.18 WLAN/CNSS port; port `qcom,cnss-qca6490` DT, then load `qca_cld3_wlan` after firmware mounts as crDroid does | CNSS/qcacld compile and are packaged in an EROFS `vendor_dlkm.img`; the qca6490 DT/PCIe fastmap partition is present but unproven on hardware; btpower/bt_fm_slim deferred |
| Mobile data | IPA, datarmnet, rmnet offload/SHS | Reuse redwood's 6.18 data stack; adapt subsystem compatibility paths to Lahaina | Inherited platform work; validation pending |
| Video | downstream `msm-vidc` | Reuse redwood's 6.18 msm-vidc port and validate SM8350 firmware/UAPI | Inherited platform work; validation pending |
| Charging | `drivers/power/oplus_chg`, MP2650, RK826/OP10 Warp, HL7227, P9415 wireless | Port OPLUS charging stack only after basic power-supply/thermal safety works | Deferred; inherited Qualcomm charger module is redwood/Xiaomi-policy code and is not shipped |
| Haptics | AW8697 | Compare stock OPLUS driver with redwood's 6.18 AW8697 port and keep the ABI lemonadep userspace expects | Deferred; inherited Qualcomm HV haptics object depends on the deferred redwood charger notifier ABI |
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
- redwood-specific charger policy embedded in Qualcomm's battery charger driver;
  because `leds-qcom-flash`, `leds-qti-flash`, `qcom-spmi-wled` and
  `qcom-hv-haptics` link directly to that implementation, those objects are
  currently not configured or shipped either. `camera.ko` in turn depends on
  the flash/WLED interfaces and is therefore absent until the power chain is
  replaced with lemonadep hardware support.
- redwood `nxp-nci` NFC glue, which is not lemonadep SN100T/NQ-NCI support
- MTP `wsa883x`/machine audio remains reference-only even though currently shipped for dependency closure; lemonadep uses dual NXP TFA98xx amps and the MTP machine/amp pair must be removed together in the audio checkpoint
- first-stage CNSS/qcacld loading: `qca_cld3_wlan.ko` is shipped and blocklisted but must be modprobed only after firmware mounts and the lemonadep `qcom,cnss-qca6490` node exists
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


## 6.18 API migration notes

These compatibility changes are intentional forward-porting glue, not hidden
stubs. They should be revisited as the corresponding upstream interfaces settle:

- `pci-msm` keeps Qualcomm's legacy `aer_stats` sysfs ABI but points it at the
  upstream `pci_dev::aer_info` allocation. The two structures have the same
  counter layout prefix in 6.18; a cleaner follow-up would expose or share the
  upstream type instead of using the local layout-compatible definition.
- `qcom_iommu_set_fault_handler*()` wrappers restore the Qualcomm fault-handler
  API expected by CNSS/PCIe while dispatching to the 6.18 IOMMU core and the
  registered ARM SMMU implementation. Unsupported domains fail inertly, as the
  other Qualcomm IOMMU utility wrappers do.
- `mhi_uevent_notify()` is the missing Qualcomm MHI execution-environment
  notification body, based on the upstream Qualcomm patch, and emits the real
  `EXEC_ENV` uevent rather than suppressing it.

## Compile-fix documentation rule

Every pull request that cannot yet support a hardware block must say so in its
description. Do not remove a driver solely because it fails to compile unless
the PR explains the replacement plan and updates this matrix.
