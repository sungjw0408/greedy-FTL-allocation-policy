#ifndef RESEARCH_FIRMWARE_MOCK_H_
#define RESEARCH_FIRMWARE_MOCK_H_
#include <stdio.h>
#define FTL_CONFIG_H_
#ifndef USER_CHANNELS
#define USER_CHANNELS 2
#endif
#ifndef USER_WAYS
#define USER_WAYS 2
#endif
#define USER_DIES (USER_CHANNELS * USER_WAYS)
#define USER_PAGES_PER_BLOCK 4
#define BYTES_PER_NVME_BLOCK 4096
#define BYTES_PER_DATA_REGION_OF_SLICE 16384
#define COUNTS_PER_SECOND 1000000
#define ALLOCATION_TRACE_COUNT 0
#define Pcw2VdieTranslation(ch, way) ((ch) + (way) * USER_CHANNELS)
#define Vdie2PchTranslation(die) ((die) % USER_CHANNELS)
#define Vdie2PwayTranslation(die) ((die) / USER_CHANNELS)
#include "../request_allocation.h"
#include "../research_stats.h"
typedef unsigned long long XTime;
extern unsigned long long mockNow;
static inline void XTime_GetTime(XTime *value) { *value = mockNow; }
#define xil_printf printf
#endif
