# Cosmos+ 실험 적용 가이드 (schema 2)

2026-10-05: 가이드의 Windows 노트북 UART + Linux Host 구성에는
[LAB_RUNBOOK_KO.md](LAB_RUNBOOK_KO.md)를 먼저 사용하세요. 장비별 적용/명령 전체를 제공합니다.
`host/uart_bridge.py`와 socket:// URL 수집, inspect/allocation 단계, PCI ID 검사,
SDK 소스 diff/백업 적용 도구를 추가했습니다. 아래 /dev/ttyUSB0 예시는 UART 직접 연결 방식입니다.

## 필요한 환경

보드 쪽에는 Cosmos+ 보드, 실제 Channel/Way 구성에 맞는 FPGA bitstream/HDF,
Xilinx SDK application과 BSP가 필요합니다. 이 패키지에는 FPGA 프로젝트와 BSP가 없습니다.
Host 쪽에는 PCIe로 보드에 연결된 Linux PC, UART, Python 3.9+, fio 3.x,
nvme-cli, pyserial, matplotlib가 필요합니다. Ubuntu 설치 예시:

```bash
sudo apt install fio nvme-cli python3-venv build-essential
python3 -m venv .venv
.venv/bin/pip install -r host/requirements.txt
python3 tools/check_host.py
```

## 파일 역할

| 파일 | 역할 |
|---|---|
| `address_translation.h/.c`, `allocation_policy.h` | 정책 선택과 실제 Host NAND allocation 순서 |
| `request_format.h` | HOST/GC/INTERNAL origin, queue 시각, phase overlap baseline |
| `request_transform.c`, `data_buffer.c` | Host NAND origin, dirty-buffer writeback FLUSH |
| `garbage_collection.c`, `address_translation.c::EraseBlock()` | GC origin, victim/migration 및 GC별 erase timestamp |
| `request_allocation.c` | NAND enqueue와 완료 계측 hook |
| `request_schedule.c` | 실제 NAND phase 발행·완료 관찰 hook |
| `research_stats.c/.h`, `research_config.h` | 카운터, timer, DRAM event buffer, UART 출력 |
| `nvme/nvme.h`, `nvme/nvme_admin_cmd.c` | vendor reset/stats/marker/trace 명령 |
| `nvme/nvme_io_cmd.c` | 실험용 FLUSH, timed path UART 출력 제거 |
| `lscript.ld` | firmware globals/trace/stack이 NVMe RAM을 침범하면 link 실패 |
| `host/experiment.py` | 전처리/fio/UART/FLUSH/metadata 저장 |
| `host/telemetry.py`, `host/analyze.py` | P99/P99.9, WA, GC 지표와 통합 그래프 |
| `tools/check_allocation_trace.py` | 실제 보드 ALLOC 로그와 정책 순서 대조 |
| `tools/check_host.py`, `tests/` | 호스트 검증; 보드 build 대신 사용할 수 없음 |

## 펌웨어 빌드/적용

1. 보드 Quick Start Guide에 맞춰 official GreedyFTL SDK application/BSP를 준비합니다.
2. 기존 SDK application을 백업한 뒤 `tools/apply_sdk_sources.py`로 변경 diff를 확인하고
   연구 변경 파일만 적용합니다. 기존 `ftl_config.h`, BSP, hardware 의존 파일을 보존합니다.
   `research_stats.c`가 실제 compilation source에 포함되어야 하고,
   `allocation_policy.h`, `research_config.h`도 root include 경로에 필요합니다.
   host/tests/tools/fio는 ARM application의 source 폴더에 넣지 않습니다.
3. 실제 bitstream/BSP와 NAND SLC/MLC, geometry, USER_CHANNELS/USER_WAYS를 일치시킵니다.
4. application 전체 compiler 옵션에 다음 중 **하나**만 넣고 각각 다른 ELF로 빌드합니다.

```text
-DALLOCATION_POLICY_CHANNEL_FIRST
-DALLOCATION_POLICY_WAY_FIRST
-DALLOCATION_POLICY_PAGE_FIRST
```

헤더에서 다른 정책을 동시에 켜면 에러입니다. 지정하지 않으면 Channel-first입니다.
Page-first는 현재 block을 채운 후 Channel-first 순서로 die를 변경합니다.
GC migration destination은 원본처럼 같은 die 내에서 선택하므로 비교 대상은 Host allocation입니다.

5. linker script의 RAM boundary ASSERT와 SDK link map을 확인합니다.
6. matching bitstream과 정책별 ELF를 보드에 다운로드하고 실행합니다.
   host runner가 FPGA/ELF를 다운로드하거나 policy를 변경하지는 않습니다.

첫 검증용 build에서는 `-DALLOCATION_TRACE_COUNT=512`로 처음의 실제 allocation을
UART에 출력합니다. 같은 fresh firmware 상태에서 sequential write를 주고 대조합니다.
Page-first의 block rollover를 보려면 block당 page 수보다 긴 trace가 필요합니다.

```bash
python3 tools/check_allocation_trace.py validation-uart.log \
  --policy channel-first --channels 8 --ways 8 --pages-per-block 128
```

실제 geometry로 수정하세요. ALLOC 순서는 fio command와 일대일 대응하지 않습니다.
검증 후 latency용 build에서는 `ALLOCATION_TRACE_COUNT=0`으로 설정합니다.

`research_config.h`: trace level 0은 카운터만, 1은 GC_START/GC_END/marker,
2는 NAND phase와 Host issue까지 기록합니다. 기본 level 1, capacity 2048입니다.
buffer는 약 64 KiB이며 overflow 후 새 이벤트를 버리고 trace_dropped를 증가시킵니다.
capacity는 link-map 여유 내에서 변경하세요. level 2는 짧은 진단에 사용합니다.

## 안전한 계획 생성

다음은 장치 명령을 실행하지 않고 fio 파일과 manifest만 생성합니다.
출력 폴더는 새 폴더여야 합니다.

```bash
.venv/bin/python host/experiment.py \
  --namespace /dev/nvme0n1 --controller /dev/nvme0 \
  --policy channel-first --mode gc --phase all \
  --size-bytes 21474836480 --writer-jobs 4 --writer-qd 8 \
  --probe-iops 1000 --probe-qd 1 --runtime 120 \
  --overwrite-passes 2 --warmup-seconds 30 \
  --output results/channel-first-plan
```

20 GiB는 문법 예시입니다. 보드 physical capacity가 크면 몇 번 overwrite만으로 GC가
발생하지 않을 수 있습니다. pilot에서 충분한 주소 범위와 총 write량을 정한 후,
모든 정책에 같은 preconditioning을 적용하세요. 고정 pass 수만으로 steady state가
보장되지 않으므로 IOPS/GC율 안정성도 별도로 확인해야 합니다.

writer jobs 4 × QD 8은 writer 최대 outstanding 32개이며 probe QD 1개가 추가됩니다.
실제 outstanding이 계속 33개는 아닙니다. runner는 기본 `--worker-model threads`로
fio `thread=1`을 설정하므로 numjobs는 worker thread 수입니다.
`--worker-model processes`로 process 실행도 가능하지만 정책 간에는 동일하게 유지하세요.
probe의 rate_iops는 cap이며 QD가 작거나 latency가 길면 달성 IOPS가 더 낮을 수 있습니다.
엄격한 open-loop arrival generator는 구현하지 않았습니다.
각 writer는 동일한 LBA 범위를 독립적으로 overwrite합니다. hot/cold 분리 실험은 별도 구성입니다.

## 실제 실행

이 명령은 테스트 namespace 내용을 덮어씁니다. namespace/controller/UART를
`nvme list`, `lsblk`와 보드 연결로 식별하고 테스트 전용 장치만 지정하세요.
mount/swap/device-mapper/RAID holder가 있으면 runner가 중단됩니다.
자동 unmount/format/trim은 하지 않습니다. 다른 프로그램의 raw DUT 접근도 중지하세요.
로그는 Cosmos+가 아닌 Host SSD에 저장합니다.

우선 CRC32C write → FLUSH → read 검증을 실행합니다. 64 MiB 또는 지정한 size 중
작은 범위를 사용하므로 NAND read 검사를 위해 보드 data cache보다 큰 size가 필요합니다.
이 테스트는 power-loss 복구 검증이 아닙니다.

```bash
sudo .venv/bin/python host/experiment.py \
  --namespace /dev/nvme0n1 --controller /dev/nvme0 --serial /dev/ttyUSB0 \
  --policy channel-first --phase verify --size-bytes 67108864 \
  --output results/channel-first-integrity \
  --execute --allow-device /dev/nvme0n1
```

latency 측정 예시:

```bash
sudo .venv/bin/python host/experiment.py \
  --namespace /dev/nvme0n1 --controller /dev/nvme0 --serial /dev/ttyUSB0 \
  --policy channel-first --mode gc --phase all \
  --size-bytes 21474836480 --writer-jobs 4 --writer-qd 8 \
  --probe-iops 1000 --probe-qd 1 --runtime 120 \
  --overwrite-passes 2 --warmup-seconds 30 --repeat 1 \
  --firmware-elf firmware/channel-first.elf \
  --output results/channel-first-gc-r1 \
  --execute --allow-device /dev/nvme0n1
```

firmware-elf에는 실제 다운로드한 ELF를 지정하여 SHA-256을 보관합니다.
UART baud는 보드에 맞춰 --baud로 변경합니다. 실행 순서:

```text
장치/firmware policy/schema 확인
→ Sequential fill → 일정 write량의 random overwrite 전처리 → FLUSH
→ 별도 warm-up → FLUSH → RESET → START marker
→ Background random write + Foreground read probe 동시 실행
→ END marker → 이미 생성된 NAND 완료 → window 통계
→ FLUSH → drained 통계 → buffered trace 출력
```

Way-first/Page-first ELF를 각각 다운로드한 뒤 --policy, ELF, 결과 폴더를 바꿔 동일하게 실행합니다.
정책 비교에서 size/runtime/seed/jobs/QD/전처리는 고정합니다.
각 반복마다 동일 초기화/전처리를 하고 --repeat 1..5를 별도 실행합니다.
repeat은 식별자이며 자동 반복 옵션이 아닙니다. 정책 순서는 교차 배치하세요.

--mode baseline은 writer 없이 같은 read probe만 실행하며 GC count가 0인지 검사합니다.
--mode gc에서는 GC count > 0을 확인하고, 없으면 무효 실행으로 기록합니다.
NAND 실패가 있어도 무효 처리합니다. gc_erase_count와 achieved IOPS도 함께 확인하세요.
--phase prepare는 전처리만, --phase measure는 이미 준비한 상태의 측정만 수행합니다.
measure에서 전처리 누락을 자동 증명할 수 없으므로 preparation 기록을 보관해야 합니다.
--phase inspect는 workload 없이 initial FLUSH와 정책/geometry 통계를 확인합니다.
--phase allocation은 TRACE_COUNT>0인 검증용 ELF에서 sequential write와 FLUSH를 수행하며,
실제 ALLOC 로그는 check_allocation_trace.py로 검사합니다. 자세한 부팅/검증 순서는 runbook을 따릅니다.

## 통계와 로그

| opcode | 기능 |
|---|---|
| 0xc0 | idle에서 카운터/trace reset |
| 0xc1 | idle에서 UART 누적 통계 출력 |
| 0xc2 | CDW10 값을 DRAM marker로 기록 |
| 0xc3 | idle에서 UART buffered trace 출력 |

측정 중 stats/trace 출력 명령을 호출하지 마세요. START/END marker는 fio 바깥에서 호출합니다.

| 결과 파일 | 의미 |
|---|---|
| manifest.json | policy/부하/seed/ELF hash/Host 시각/valid 상태 |
| *.fio | 사용한 workload |
| fio.json | probe와 writer를 별도 group으로 집계한 결과 |
| probe_clat.*.log | 개별 read completion latency, timestamp ms / latency ns |
| uart.log | UART 수신 전체 |
| window.stats.txt | 최종 dirty-buffer FLUSH 이전 통계 |
| drained.stats.txt | 최종 FLUSH 이후 통계; WA 계산용 |
| trace.txt | GC/marker/선택적 phase 이벤트 |

지표 해석:

- gc_*_blocked_cycles는 enqueue 시 pending GC가 있던 Host 요청의 전체 queue wait입니다.
  GC만이 유발한 blocked time으로 표현하면 안 됩니다.
- host_same_die_gc_issue_overlap_cycles는 Host enqueue→first issue 중 같은 die의
  GC issued phase와 겹친 시간입니다. READ trigger/transfer/retry를 구분합니다.
  펌웨어 완료 관찰 지연을 포함하므로 순수 hardware busy나 원인별 denial 시간은 아닙니다.
- gc_issued_phase_cycles는 die별 GC phase 시간의 합이며 Channel bus utilization이 아닙니다.
- host_nand_req_count는 NVMe 명령 수가 아니라 NAND 요청 수입니다.
- gc_execution_cycles는 victim 선택 후 hook부터 해당 GC erase 완료 관찰까지이며,
  겹친 GC가 있으면 총합이 wall-clock time을 넘을 수 있습니다.
- gc_migration_pages는 계획한 migration 수, gc_nand_program_pages는 성공한 GC write 수입니다.
- WA = (Host NAND program + GC NAND program) × page bytes / Host logical write bytes.
  전처리 후 FLUSH→RESET, 측정 후 FLUSH→drained 통계 순서를 지켜야 합니다.
- window 통계에는 fio 종료 후 이미 생성된 NAND 요청의 완료까지 들어갑니다.
  drained에는 최종 FLUSH가 만든 추가 작업까지 들어가므로 두 값을 분리해 사용합니다.

## 분석 및 통합 그래프

```bash
.venv/bin/python host/analyze.py \
  results/channel-first-gc-r1 results/way-first-gc-r1 results/page-first-gc-r1 \
  --output results/comparison --window-seconds 1 --metric p99
```

summary.csv, 정책별 latency-windows/events/gc-intervals.csv,
통합 latency-timeseries-p99.png/.svg 및 latency-ccdf.png/.svg를 생성합니다.
--metric p99_9로 P99.9 시간 그래프도 생성합니다.

1초 P99는 그 구간의 **원시 latency 표본**으로 계산합니다. log_avg_msec=1000의
평균값들로 P99를 계산하지 않습니다. 전체 P99도 구간 P99들의 평균이 아닙니다.
1000 IOPS의 1초 P99.9는 약 한 개의 극단 표본에 민감하므로 count와 window 길이를 함께 보고
전체 run P99.9와 반복 실험도 확인하세요. fio histogram percentile과 raw nearest-rank 값에는
binning 차이가 있습니다. 구버전 us latency 로그면 --latency-unit us를 사용합니다.

각 정책은 별도 run이므로 X축은 각 실행의 경과 시간입니다. 같은 50초의 요청을 서로 대응시키지 않습니다.
fio log는 job 시작 기준, GC trace는 firmware RESET 기준입니다.
marker의 Host 왕복 bracket은 manifest에, firmware tick은 trace에 있지만 process launch→job 시작
지연까지 보정하지 않으므로 현재 그래프에 GC 음영을 자동 삽입하지 않습니다.
정밀한 시간 상관 분석은 clock alignment를 검증한 다음 진행해야 합니다.

보드 없이 분석 흐름만 시험:

```bash
.venv/bin/python host/demo.py --output results/synthetic-demo
```

그림에도 SYNTHETIC을 명시하며 실험 결과가 아닙니다.

## 검증 범위와 남은 한계

호스트의 Python tests, 실제 allocation C helper와 telemetry C tests,
수정 firmware의 C 문법 검사를 제공합니다. 실제 ARM build/link, DMA/NAND 데이터 정확성,
physical geometry와 latency overhead는 보드에서 확인해야 합니다.
tests/bsp_stubs는 문법 검사 전용이며 실제 SDK include path에 넣으면 안 됩니다.

trace_dropped > 0이면 이벤트 timeline이 불완전합니다. 카운터는 계속 기록됩니다.
level 1/0 비교로 trace overhead를 점검하세요. Channel controller bus의 정확한 origin과
scheduler denial은 아직 계측하지 않았습니다.

실험용 FLUSH는 data-buffer program 완료를 기다립니다. FUA/write-through,
mapping의 power-loss recovery와 완전한 NVMe 오류 전파는 구현하지 않았습니다.
상용 수준의 전원 차단 영속성을 보장하는 FLUSH로 해석하면 안 됩니다.

현재 queue wait는 buffer/row dependency 이후의 NAND-ready queue 단계입니다.
CPU가 GC를 생성하여 Host 수신이 늦어진 시간이나 그 이전 dependency 대기는 전부 포착하지 않습니다.
Host NVMe별 충돌 집단의 P99를 분석하려면 NVMe↔NAND provenance와 Host completion을
연결하는 추가 계측이 필요합니다. 현 카운터만으로 요청별 causal attribution을 주장하지 마세요.

참고: [공식 fio log 문서](https://fio.readthedocs.io/en/latest/fio_doc.html#log-file-formats),
[공식 GreedyFTL 소스](https://github.com/Cosmos-OpenSSD/Cosmos-plus-OpenSSD/tree/master/source/software/GreedyFTL-3.0.0).
