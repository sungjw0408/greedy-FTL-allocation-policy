#ifdef RESEARCH_HOST_TEST
#include "tests/firmware_mock.h"
#else
#include "xil_printf.h"
#include "xparameters.h"
#include "xtime_l.h"
#include "memory_map.h"
#include "research_stats.h"
#endif
#include "research_config.h"

volatile RESEARCH_STATS researchStats;

static unsigned int gcPendingPerDie[USER_CHANNELS][USER_WAYS];
static unsigned int gcPendingPerChannel[USER_CHANNELS];
static unsigned long long gcStartTime[USER_DIES];
static unsigned int gcMigrated[USER_DIES];
static unsigned char phaseActive[USER_CHANNELS][USER_WAYS];
static unsigned int phaseOrigin[USER_CHANNELS][USER_WAYS];
static unsigned int phaseCode[USER_CHANNELS][USER_WAYS];
static unsigned long long phaseStart[USER_CHANNELS][USER_WAYS];
static unsigned long long gcPhaseTotal[USER_CHANNELS][USER_WAYS];
static unsigned long long statsEpoch;

/* a,b are event-dependent: START(victim,0), END(migrations,elapsed),
 * HOST_ISSUE(queue-wait,same-die GC issued-phase overlap),
 * PHASE_END(origin,elapsed), MARK(marker,0). 32 bytes per record on ARM. */
typedef struct {
	unsigned long long tick, a, b;
	unsigned int type, resource;
} RESEARCH_EVENT;
static RESEARCH_EVENT events[RESEARCH_TRACE_CAPACITY];
static unsigned int eventCount, eventDropped;
static unsigned long long ResearchNow(void);

static void RecordEvent(unsigned int type, unsigned int ch, unsigned int way,
	unsigned long long a, unsigned long long b)
{
#if RESEARCH_TRACE_LEVEL > 0
	if(eventCount == RESEARCH_TRACE_CAPACITY) { eventDropped++; return; }
	events[eventCount].tick = ResearchNow();
	events[eventCount].a = a;
	events[eventCount].b = b;
	events[eventCount].type = type;
	events[eventCount].resource = (ch << 16) | way;
	eventCount++;
#else
	(void)type; (void)ch; (void)way; (void)a; (void)b;
#endif
}

static unsigned long long ResearchNow(void)
{
	XTime now;
	XTime_GetTime(&now);
	return (unsigned long long)now;
}

static void ClearRuntimeState(void)
{
	unsigned int chNo, wayNo, dieNo;

	for(chNo = 0; chNo < USER_CHANNELS; chNo++)
	{
		gcPendingPerChannel[chNo] = 0;
		for(wayNo = 0; wayNo < USER_WAYS; wayNo++)
		{
			gcPendingPerDie[chNo][wayNo] = 0;
			phaseActive[chNo][wayNo] = 0;
			gcPhaseTotal[chNo][wayNo] = 0;
		}
	}

	for(dieNo = 0; dieNo < USER_DIES; dieNo++)
	{
		gcStartTime[dieNo] = 0;
		gcMigrated[dieNo] = 0;
	}
}

void ResearchStatsReset(void)
{
	volatile unsigned int *word;
	unsigned int i;

	word = (volatile unsigned int *)&researchStats;
	for(i = 0; i < sizeof(RESEARCH_STATS) / sizeof(unsigned int); i++)
		word[i] = 0;

	ClearRuntimeState();
	statsEpoch = ResearchNow();
	eventCount = eventDropped = 0;
}

unsigned int ResearchStatsIdle(void)
{
	return !notCompletedNandReqCnt && !blockedReqCnt &&
		nvmeDmaReqQ.headReq == REQ_SLOT_TAG_NONE &&
		sliceReqQ.headReq == REQ_SLOT_TAG_NONE;
}

void ResearchStatsInit(void)
{
	ResearchStatsReset();
}

static void PrintU64(const char *name, unsigned long long value)
{
	xil_printf("%s=0x%08x%08x\r\n", name,
		(unsigned int)(value >> 32), (unsigned int)value);
}

void ResearchStatsPrint(void)
{
	xil_printf("\r\n=== RESEARCH_STATS_BEGIN ===\r\n");
	PrintU64("host_logical_write_bytes", researchStats.hostLogicalWriteBytes);
	PrintU64("host_nand_program_pages", researchStats.hostNandProgramPages);
	PrintU64("gc_nand_program_pages", researchStats.gcNandProgramPages);
	PrintU64("gc_read_pages", researchStats.gcReadPages);
	PrintU64("gc_migration_pages", researchStats.gcMigrationPages);
	PrintU64("gc_erase_count", researchStats.gcEraseCount);
	PrintU64("gc_count", researchStats.gcCount);
	PrintU64("gc_failed_req_count", researchStats.gcFailedReqCount);
	PrintU64("gc_execution_cycles", researchStats.gcExecutionCycles);
	PrintU64("gc_max_execution_cycles", researchStats.gcMaxExecutionCycles);
	PrintU64("gc_die_blocked_req_count", researchStats.gcDieBlockedReqCount);
	PrintU64("gc_die_blocked_cycles", researchStats.gcDieBlockedCycles);
	PrintU64("gc_channel_blocked_req_count", researchStats.gcChannelBlockedReqCount);
	PrintU64("gc_channel_blocked_cycles", researchStats.gcChannelBlockedCycles);
	PrintU64("host_nand_req_count", researchStats.hostNandReqCount);
	PrintU64("host_nand_read_pages", researchStats.hostNandReadPages);
	PrintU64("host_failed_req_count", researchStats.hostFailedReqCount);
	PrintU64("host_queue_wait_cycles", researchStats.hostQueueWaitCycles);
	PrintU64("host_same_die_gc_issue_overlap_req_count", researchStats.hostSameDieGcIssueOverlapReqCount);
	PrintU64("host_same_die_gc_issue_overlap_cycles", researchStats.hostSameDieGcIssueOverlapCycles);
	PrintU64("gc_issued_phase_cycles", researchStats.gcIssuedPhaseCycles);
	PrintU64("stats_epoch_ticks", statsEpoch);
	PrintU64("stats_snapshot_ticks", ResearchNow());
	PrintU64("trace_event_count", eventCount);
	PrintU64("trace_dropped", eventDropped);
	xil_printf("research_schema=0x00000002\r\n");
#if defined(ALLOCATION_POLICY_WAY_FIRST)
	xil_printf("allocation_policy=way-first\r\n");
#elif defined(ALLOCATION_POLICY_PAGE_FIRST)
	xil_printf("allocation_policy=page-first\r\n");
#else
	xil_printf("allocation_policy=channel-first\r\n");
#endif
	xil_printf("trace_level=0x%08x\r\n", RESEARCH_TRACE_LEVEL);
	xil_printf("allocation_trace_count=0x%08x\r\n", ALLOCATION_TRACE_COUNT);
	xil_printf("user_channels=0x%08x\r\nuser_ways=0x%08x\r\n", USER_CHANNELS, USER_WAYS);
	xil_printf("user_pages_per_block=0x%08x\r\n", USER_PAGES_PER_BLOCK);
	xil_printf("timer_counts_per_second=0x%08x\r\n", (unsigned int)COUNTS_PER_SECOND);
	xil_printf("nand_page_bytes=0x%08x\r\n", BYTES_PER_DATA_REGION_OF_SLICE);
	xil_printf("=== RESEARCH_STATS_END ===\r\n");
}

void ResearchMark(unsigned int marker)
{
	RecordEvent(6, 0, 0, marker, 0);
}

void ResearchTracePrint(void)
{
	unsigned int i;
	RESEARCH_EVENT *e;
	xil_printf("=== RESEARCH_TRACE_BEGIN ===\r\n");
	xil_printf("TRACE_HEADER,type,ch,way,tick,a,b\r\n");
	for(i = 0; i < eventCount; i++)
	{
		e = &events[i];
		xil_printf("TRACE,%d,%d,%d,0x%08x%08x,0x%08x%08x,0x%08x%08x\r\n",
			e->type, e->resource >> 16, e->resource & 0xffff,
			(unsigned int)(e->tick >> 32), (unsigned int)e->tick,
			(unsigned int)(e->a >> 32), (unsigned int)e->a,
			(unsigned int)(e->b >> 32), (unsigned int)e->b);
	}
	xil_printf("trace_dropped=0x%08x\r\n", eventDropped);
	xil_printf("=== RESEARCH_TRACE_END ===\r\n");
}

void ResearchAccountHostWrite(unsigned int nvmeBlockCount)
{
	researchStats.hostLogicalWriteBytes +=
		(unsigned long long)nvmeBlockCount * BYTES_PER_NVME_BLOCK;
}

void ResearchGcStart(unsigned int dieNo, unsigned int victimBlock)
{
	/* Another GC invocation may be enqueued before an earlier erase completes.
	 * Capture each invocation on its terminating erase instead of one active flag. */
	gcStartTime[dieNo] = ResearchNow();
	researchStats.gcCount++;
	gcMigrated[dieNo] = 0;
	RecordEvent(1, Vdie2PchTranslation(dieNo), Vdie2PwayTranslation(dieNo), victimBlock, 0);
}

void ResearchGcMigration(unsigned int dieNo)
{
	researchStats.gcMigrationPages++;
	gcMigrated[dieNo]++;
}

void ResearchGcReqCreated(unsigned int dieNo, unsigned int reqSlotTag)
{
	if(reqPoolPtr->reqPool[reqSlotTag].reqCode == REQ_CODE_ERASE)
	{
		reqPoolPtr->reqPool[reqSlotTag].gcRunStartTime = gcStartTime[dieNo];
		reqPoolPtr->reqPool[reqSlotTag].gcRunMigrationPages = gcMigrated[dieNo];
	}
}

static unsigned long long GcPhaseClock(unsigned int ch, unsigned int way,
	unsigned long long now)
{
	unsigned long long value = gcPhaseTotal[ch][way];
	if(phaseActive[ch][way] && phaseOrigin[ch][way] == REQ_ORIGIN_GC)
		value += now - phaseStart[ch][way];
	return value;
}

void ResearchNandEnqueue(unsigned int reqSlotTag, unsigned int chNo, unsigned int wayNo)
{
	unsigned int origin;

	origin = reqPoolPtr->reqPool[reqSlotTag].reqOpt.reqOrigin;
	reqPoolPtr->reqPool[reqSlotTag].enqueueTime = ResearchNow();
	reqPoolPtr->reqPool[reqSlotTag].gcPhaseBaseline = GcPhaseClock(chNo, wayNo,
		reqPoolPtr->reqPool[reqSlotTag].enqueueTime);
	reqPoolPtr->reqPool[reqSlotTag].reqOpt.researchIssued = 0;
	reqPoolPtr->reqPool[reqSlotTag].reqOpt.gcConflict = REQ_GC_CONFLICT_NONE;

	if(origin == REQ_ORIGIN_GC)
	{
		gcPendingPerDie[chNo][wayNo]++;
		gcPendingPerChannel[chNo]++;
	}
	else if(origin == REQ_ORIGIN_HOST)
	{
		researchStats.hostNandReqCount++;
		if(gcPendingPerDie[chNo][wayNo])
			reqPoolPtr->reqPool[reqSlotTag].reqOpt.gcConflict = REQ_GC_CONFLICT_DIE;
		else if(gcPendingPerChannel[chNo])
			reqPoolPtr->reqPool[reqSlotTag].reqOpt.gcConflict = REQ_GC_CONFLICT_CHANNEL;
	}
}

void ResearchNandIssue(unsigned int reqSlotTag, unsigned int chNo, unsigned int wayNo)
{
	unsigned long long waitCycles, overlap, now;
	unsigned int conflict, origin;

	now = ResearchNow();
	origin = reqPoolPtr->reqPool[reqSlotTag].reqOpt.reqOrigin;
	if(!reqPoolPtr->reqPool[reqSlotTag].reqOpt.researchIssued)
	{
		reqPoolPtr->reqPool[reqSlotTag].reqOpt.researchIssued = 1;
		if(origin == REQ_ORIGIN_HOST)
		{
			waitCycles = now - reqPoolPtr->reqPool[reqSlotTag].enqueueTime;
			overlap = GcPhaseClock(chNo, wayNo, now) - reqPoolPtr->reqPool[reqSlotTag].gcPhaseBaseline;
			researchStats.hostQueueWaitCycles += waitCycles;
			if(overlap)
			{
				researchStats.hostSameDieGcIssueOverlapReqCount++;
				researchStats.hostSameDieGcIssueOverlapCycles += overlap;
			}
#if RESEARCH_TRACE_LEVEL >= 2
			RecordEvent(3, chNo, wayNo, waitCycles, overlap);
#endif
		}
	}
	/* A read has separate trigger and transfer phases; retries are phases too. */
	phaseActive[chNo][wayNo] = 1;
	phaseOrigin[chNo][wayNo] = origin;
	phaseCode[chNo][wayNo] = reqPoolPtr->reqPool[reqSlotTag].reqCode;
	phaseStart[chNo][wayNo] = now;
#if RESEARCH_TRACE_LEVEL >= 2
	RecordEvent(4, chNo, wayNo, origin, phaseCode[chNo][wayNo]);
#endif
	conflict = reqPoolPtr->reqPool[reqSlotTag].reqOpt.gcConflict;
	if(conflict == REQ_GC_CONFLICT_NONE)
		return;

	waitCycles = ResearchNow() - reqPoolPtr->reqPool[reqSlotTag].enqueueTime;
	if(conflict == REQ_GC_CONFLICT_DIE)
	{
		researchStats.gcDieBlockedReqCount++;
		researchStats.gcDieBlockedCycles += waitCycles;
	}
	else if(conflict == REQ_GC_CONFLICT_CHANNEL)
	{
		researchStats.gcChannelBlockedReqCount++;
		researchStats.gcChannelBlockedCycles += waitCycles;
	}

	reqPoolPtr->reqPool[reqSlotTag].reqOpt.gcConflict = REQ_GC_CONFLICT_NONE;
}

void ResearchNandPhaseComplete(unsigned int chNo, unsigned int wayNo)
{
	unsigned long long elapsed;
	if(!phaseActive[chNo][wayNo]) return;
	elapsed = ResearchNow() - phaseStart[chNo][wayNo];
	if(phaseOrigin[chNo][wayNo] == REQ_ORIGIN_GC)
	{
		gcPhaseTotal[chNo][wayNo] += elapsed;
		researchStats.gcIssuedPhaseCycles += elapsed;
	}
#if RESEARCH_TRACE_LEVEL >= 2
	RecordEvent(5, chNo, wayNo, phaseOrigin[chNo][wayNo], elapsed);
#endif
	phaseActive[chNo][wayNo] = 0;
}

void ResearchNandComplete(unsigned int reqSlotTag, unsigned int chNo, unsigned int wayNo, unsigned int success)
{
	unsigned int origin, reqCode;
	unsigned long long elapsed;

	origin = reqPoolPtr->reqPool[reqSlotTag].reqOpt.reqOrigin;
	reqCode = reqPoolPtr->reqPool[reqSlotTag].reqCode;

	if(success && reqCode == REQ_CODE_WRITE)
	{
		if(origin == REQ_ORIGIN_GC)
			researchStats.gcNandProgramPages++;
		else if(origin == REQ_ORIGIN_HOST)
			researchStats.hostNandProgramPages++;
	}

	if(origin == REQ_ORIGIN_HOST)
	{
		if(success && (reqCode == REQ_CODE_READ_TRANSFER || reqCode == REQ_CODE_READ))
			researchStats.hostNandReadPages++;
		if(!success) researchStats.hostFailedReqCount++;
	}
	if(origin != REQ_ORIGIN_GC)
		return;

	if(gcPendingPerDie[chNo][wayNo])
		gcPendingPerDie[chNo][wayNo]--;
	if(gcPendingPerChannel[chNo])
		gcPendingPerChannel[chNo]--;

	if(success && (reqCode == REQ_CODE_READ_TRANSFER || reqCode == REQ_CODE_READ))
		researchStats.gcReadPages++;
	if(success && reqCode == REQ_CODE_ERASE)
		researchStats.gcEraseCount++;
	if(!success)
		researchStats.gcFailedReqCount++;

	if(reqCode == REQ_CODE_ERASE)
	{
		elapsed = ResearchNow() - reqPoolPtr->reqPool[reqSlotTag].gcRunStartTime;
		researchStats.gcExecutionCycles += elapsed;
		if(elapsed > researchStats.gcMaxExecutionCycles)
			researchStats.gcMaxExecutionCycles = elapsed;
		RecordEvent(2, chNo, wayNo, reqPoolPtr->reqPool[reqSlotTag].gcRunMigrationPages, elapsed);
	}
}
