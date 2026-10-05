# GreedyFTL 3.0.0 research patch

**2026-10-05 lab workflow:** [LAB_RUNBOOK_KO.md](LAB_RUNBOOK_KO.md) covers the already-working
Windows SDK laptop + Linux PCIe Host setup, preserving hardware/BSP configuration.
Includes a read-only UART LAN bridge, source preview/backup installer, inspect/allocation
validation phases, PCI identity guard and fio parse-only preflight. UART remains on laptop.

**Schema 2 update:** start with [EXPERIMENT_GUIDE_KO.md](EXPERIMENT_GUIDE_KO.md).
The new `host/` runner replaces manual workload/log collection for new experiments.
This is source code requiring a matching Xilinx SDK/BSP build and board validation,
not a board-tested ARM ELF. Never add `tests/bsp_stubs` to a real firmware build.

This directory is based on the official Cosmos+ OpenSSD GreedyFTL 3.0.0 source.
It adds allocation-policy selection, GC provenance, GC/WA instrumentation, and a
real NVMe FLUSH path.

## Allocation policies

Set exactly one application-wide compiler macro (default: Channel-first):

```text
-DALLOCATION_POLICY_CHANNEL_FIRST
-DALLOCATION_POLICY_WAY_FIRST
-DALLOCATION_POLICY_PAGE_FIRST
```

- Channel-first advances channel for every 16 KiB FTL slice, then way.
- Way-first advances way for every slice, then channel.
- Page-first fills the current block on one die before advancing to the next die
  in channel-first order.

Run the actual C policy helper tests before building:

```bash
python3 tools/check_host.py
```

For one firmware-validation run, set `ALLOCATION_TRACE_COUNT` to 128. The UART
will print the actual channel, way, block, and page of the first allocations.
Set it back to zero for every latency experiment.

## Metrics

`research_stats.c` records:

- host logical write bytes
- host and GC NAND program pages
- GC read and migrated pages
- completed GC erase count
- GC count, failures, total execution cycles, and maximum execution cycles
- host NAND requests queued while a GC request was pending on the same die or
  another way of the same channel

GC execution time begins just after victim selection and ends when that GC's
erase completion is observed. Each erase retains its invocation timestamp even
if another GC is queued on the same die. The blocked-time counters are queue-wait
proxies: they count the entire enqueue-to-issue interval for a host request that
observed pending GC work at enqueue time.

Write amplification is calculated after a real FLUSH:

```text
WA = (host_nand_program_pages + gc_nand_program_pages)
     * nand_page_bytes / host_logical_write_bytes
```

## Statistics control

Only issue the reset command while the device is idle and after FLUSH.

```bash
sudo nvme admin-passthru /dev/nvme0 --opcode=0xc0
sudo nvme admin-passthru /dev/nvme0 --opcode=0xc1
```

Opcode `0xc0` resets counters. Opcode `0xc1` prints one statistics block to the
Cosmos+ UART. Capture that output and parse it with:

```bash
python3 tools/parse_research_stats.py serial.log
```

## FLUSH and latency interpretation

The original FLUSH handler did not force dirty-buffer writeback (ordinary
eviction still generated NAND writes). This patch
makes FLUSH wait for preceding work, program every dirty data-buffer entry, and
wait for all generated NAND requests.

Normal write commands are still acknowledged after host-to-device DMA. For
media-related effects, use FLUSH completion time or a foreground read probe while
a background writer generates GC. Reads can still hit the data cache; neither
metric is pure NAND service time. fio write completion latency alone remains a
write-buffer latency measurement. FUA, power-loss persistence and full NAND error
propagation are not guaranteed by this experimental FLUSH patch.

## Suggested fio structure

Use a raw test namespace only; these workloads destroy its contents. Use 16 KiB
aligned writes as the allocation-policy baseline and a separate 4 KiB test for
read-modify-write effects.

Keep total outstanding I/O constant when comparing job count:

```text
numjobs=1, iodepth=32
numjobs=2, iodepth=16
numjobs=4, iodepth=8
numjobs=8, iodepth=4
```

Run identical preconditioning after every firmware change or reboot. Reset
statistics only after preconditioning and immediately before the measurement
window. Issue FLUSH after the measurement window before printing statistics.

An example concurrent GC-writer/read-probe workload is included. All five
environment variables are required:

```bash
sudo TEST_DEVICE=/dev/nvme0n1 TEST_SIZE=20G \
  WRITER_JOBS=4 WRITER_QD=8 PROBE_IOPS=1000 \
  fio fio/gc_interference.fio --output-format=json --output=fio.json
python3 tools/parse_fio_p99.py fio.json
```

## Schema 2 additions

- `allocation_policy.h`: shared actual C policy helper, tested for rollover.
- `research_config.h`: trace 0=counters, 1=GC/marker events, 2=NAND phases/Host issue.
- `0xc2`: buffer a marker using CDW10; `0xc3`: dump buffered events after workload.
- `host_nand_req_count`, read pages and Host NAND failures.
- `host_same_die_gc_issue_overlap_cycles`: overlap between Host enqueue-to-first-issue
  and same-die GC issued phases. This is observed phase time, not pure hardware busy
  or counterfactual GC-only blocking time. Read trigger/transfer/retry phases are separate.
- `gc_issued_phase_cycles`: summed GC phase intervals; not Channel bus utilization.
- UART output is removed from timed FLUSH; statistics/trace dumps require idle state.
- `window` statistics before final dirty-buffer drain and `drained` statistics after
  final FLUSH are stored separately by the runner. Use drained counts for WA.
- Stats report firmware policy/geometry/schema and trace drops. GC timelines are
  incomplete when `trace_dropped>0`.
- FUA/write-through, mapping persistence, full NVMe error propagation and exact
  controller-bus ownership instrumentation are not provided by this update.

Run `python3 tools/check_host.py` for host tests, C logic tests and firmware syntax
checks with BSP stubs. Actual ARM build/link and board timing/data tests remain required.
See the guide for Linux execution, correctness checks, raw fio latency analysis,
clock alignment limitations and full file responsibilities.
