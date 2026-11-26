// SPDX-License-Identifier: GPL-2.0-only
/*
 * Minimal lemonadep boot-debug kernel log writeback.
 *
 * This is a temporary bring-up diagnostic, not a port of the full OPLUS
 * Phoenix feature set.  It mirrors the Phoenix 2.0 on-disk layout used by
 * the stock kernel so bootloops can be analysed from recovery:
 *
 *   0..4 MiB                         UEFI logs (untouched)
 *   4 MiB                            kernel header
 *   4 MiB + 4 KiB + (bootcount % 8)  2 MiB circular kernel-log slots
 *
 * The writer deliberately starts as a thread and retries because lemonadep's
 * UFS/storage stack is modular in the migration image.  Once the block device
 * appears, the kmsg iterator still starts at the oldest record retained in
 * the printk ring buffer, so early boot messages are captured too.
 */

#include <linux/blkdev.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/kmsg_dump.h>
#include <linux/kthread.h>
#include <linux/slab.h>

#define KWB_HEADER_OFFSET	(4LL * 1024 * 1024)
#define KWB_BLOCK_SIZE		4096
#define KWB_LINE_SIZE		2048
#define KWB_SLOT_BLOCKS		512
#define KWB_SLOT_COUNT		8
#define KWB_HEADER_BLOCKS	1
#define KWB_RETRY_COUNT		1800
#define KWB_RETRY_MS		100
#define KWB_FLUSH_MS		10
#define KWB_RUNTIME_MS		(180 * 1000)
#define KWB_MAGIC		"PHOENIX2.0"

struct kwb_disk_header {
	u64 bootcount;
	char magic[12];
	char is_monitoring;
	char is_needfeedback;
	u64 last_bootcount;
	u64 nobootcount;
};

static int kwb_match_label(struct device *dev, const void *data)
{
	struct block_device *bdev = dev_to_bdev(dev);
	const char *label = data;

	return bdev->bd_meta_info &&
		!strcmp(label, bdev->bd_meta_info->volname);
}

static dev_t kwb_find_partlabel(const char *label)
{
	struct device *dev;
	dev_t devt = 0;

	dev = class_find_device(&block_class, NULL, label, kwb_match_label);
	if (dev) {
		devt = dev->devt;
		put_device(dev);
	}

	return devt;
}

static struct file *kwb_open_reserve(dev_t *devt_out)
{
	static const char * const labels[] = { "oplusreserve5", "opporeserve5" };
	struct file *file;
	dev_t devt;
	int i;

	for (i = 0; i < ARRAY_SIZE(labels); i++) {
		devt = kwb_find_partlabel(labels[i]);
		if (!devt)
			continue;

		file = bdev_file_open_by_dev(devt,
				BLK_OPEN_READ | BLK_OPEN_WRITE, NULL, NULL);
		if (!IS_ERR(file)) {
			*devt_out = devt;
			return file;
		}
	}

	return ERR_PTR(-ENODEV);
}

static int kwb_write_full(struct file *file, const void *buf, size_t len,
		loff_t pos)
{
	loff_t p = pos;
	ssize_t ret;

	ret = kernel_write(file, buf, len, &p);
	if (ret != len)
		return ret < 0 ? ret : -EIO;

	return 0;
}

static int kwb_init_header(struct file *file, u64 *bootcount)
{
	struct kwb_disk_header head;
	loff_t pos = KWB_HEADER_OFFSET;
	ssize_t ret;

	memset(&head, 0, sizeof(head));
	ret = kernel_read(file, &head, sizeof(head), &pos);
	if (ret != sizeof(head))
		return ret < 0 ? ret : -EIO;

	if (!memcmp(head.magic, KWB_MAGIC, strlen(KWB_MAGIC)))
		head.bootcount++;
	else {
		memset(&head, 0, sizeof(head));
		memcpy(head.magic, KWB_MAGIC, strlen(KWB_MAGIC));
		head.bootcount = 0;
	}

	head.last_bootcount = head.bootcount;
	head.is_monitoring = 0;
	head.is_needfeedback = 0;

	ret = kwb_write_full(file, &head, sizeof(head), KWB_HEADER_OFFSET);
	if (ret)
		return ret;

	*bootcount = head.bootcount;
	return 0;
}

static int kwb_thread(void *unused)
{
	struct kmsg_dump_iter iter;
	struct file *file = ERR_PTR(-ENODEV);
	loff_t base, write_pos;
	dev_t devt = 0;
	char *buf, *line;
	u64 bootcount = 0;
	size_t used = 0, len = 0;
	int retry, block = 0, elapsed = 0, ret = 0, i;
	bool dirty = false;

	/* Start early, but do not touch the block class before storage init. */
	msleep(700);

	for (retry = 0; retry < KWB_RETRY_COUNT; retry++) {
		file = kwb_open_reserve(&devt);
		if (!IS_ERR(file))
			break;
		msleep_interruptible(KWB_RETRY_MS);
	}

	if (IS_ERR(file)) {
		pr_err("lemonadep-kmsg-wb: reserve5 never appeared\n");
		return 0;
	}

	buf = kzalloc(KWB_BLOCK_SIZE, GFP_KERNEL);
	line = kzalloc(KWB_LINE_SIZE, GFP_KERNEL);
	if (!buf || !line)
		goto out_free;

	ret = kwb_init_header(file, &bootcount);
	if (ret) {
		pr_err("lemonadep-kmsg-wb: header update failed: %d\n", ret);
		goto out_free;
	}

	base = KWB_HEADER_OFFSET +
		(KWB_HEADER_BLOCKS + (bootcount % KWB_SLOT_COUNT) * KWB_SLOT_BLOCKS) *
		KWB_BLOCK_SIZE;
	pr_err("lemonadep-kmsg-wb: dev %u:%u bootcount %llu slot %llu base %#llx\n",
		MAJOR(devt), MINOR(devt), bootcount,
		bootcount % KWB_SLOT_COUNT, base);

	for (i = 0; i < KWB_SLOT_BLOCKS; i++) {
		ret = kwb_write_full(file, buf, KWB_BLOCK_SIZE,
				base + (loff_t)i * KWB_BLOCK_SIZE);
		if (ret) {
			pr_err("lemonadep-kmsg-wb: slot erase failed: %d\n", ret);
			goto out_free;
		}
	}

	kmsg_dump_rewind(&iter);
	while (elapsed < KWB_RUNTIME_MS) {
		while (kmsg_dump_get_line(&iter, true, line, KWB_LINE_SIZE, &len)) {
			if (used + len >= KWB_BLOCK_SIZE) {
				write_pos = base + (loff_t)block * KWB_BLOCK_SIZE;
				ret = kwb_write_full(file, buf, used, write_pos);
				if (ret) {
					pr_err("lemonadep-kmsg-wb: write failed: %d\n", ret);
					goto out_free;
				}
				block++;
				if (block >= KWB_SLOT_BLOCKS)
					goto out_free;
				used = 0;
				memset(buf, 0, KWB_BLOCK_SIZE);
			}

			memcpy(buf + used, line, len);
			used += len;
			len = 0;
			dirty = true;
		}

		if (used && dirty) {
			/* Rewrite the current partial block only when new records arrived. */
			write_pos = base + (loff_t)block * KWB_BLOCK_SIZE;
			ret = kwb_write_full(file, buf, used, write_pos);
			if (ret) {
				pr_err("lemonadep-kmsg-wb: partial write failed: %d\n", ret);
				goto out_free;
			}
			dirty = false;
		}

		msleep_interruptible(KWB_FLUSH_MS);
		elapsed += KWB_FLUSH_MS;
		if (!(elapsed % 2000))
			pr_err("lemonadep-kmsg-wb: alive elapsed %d ms\n", elapsed);
	}

out_free:
	if (!IS_ERR(file))
		bdev_fput(file);
	kfree(line);
	kfree(buf);
	return 0;
}

static int __init lemonadep_kmsg_wb_init(void)
{
	kthread_run(kwb_thread, NULL, "lemonadep-kmsg-wb");
	return 0;
}
core_initcall(lemonadep_kmsg_wb_init);
