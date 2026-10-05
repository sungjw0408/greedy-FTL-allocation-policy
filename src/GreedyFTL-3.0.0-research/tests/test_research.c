#include <assert.h>
#include <string.h>
#include "firmware_mock.h"

unsigned long long mockNow;
static REQ_POOL pool;
P_REQ_POOL reqPoolPtr = &pool;
unsigned int notCompletedNandReqCnt, blockedReqCnt;
NVME_DMA_REQUEST_QUEUE nvmeDmaReqQ;
SLICE_REQUEST_QUEUE sliceReqQ;

int main(void)
{
	nvmeDmaReqQ.headReq = sliceReqQ.headReq = REQ_SLOT_TAG_NONE;
	assert(ResearchStatsIdle());
	blockedReqCnt = 1;
	assert(!ResearchStatsIdle());
	blockedReqCnt = 0;
	mockNow = 0;
	ResearchStatsReset();
	mockNow = 10;
	ResearchGcStart(0, 123);
	ResearchGcMigration(0);
	pool.reqPool[0].reqOpt.reqOrigin = REQ_ORIGIN_GC;
	pool.reqPool[0].reqCode = REQ_CODE_READ;
	ResearchNandEnqueue(0, 0, 0);
	pool.reqPool[3].reqOpt.reqOrigin = REQ_ORIGIN_GC;
	pool.reqPool[3].reqCode = REQ_CODE_ERASE;
	ResearchGcReqCreated(0, 3);
	ResearchNandEnqueue(3, 0, 0);
	mockNow = 20;
	ResearchNandIssue(0, 0, 0);
	mockNow = 30;
	pool.reqPool[1].reqOpt.reqOrigin = REQ_ORIGIN_HOST;
	pool.reqPool[1].reqCode = REQ_CODE_READ;
	ResearchNandEnqueue(1, 0, 0);
	mockNow = 50;
	ResearchNandPhaseComplete(0, 0);
	mockNow = 60;
	pool.reqPool[0].reqCode = REQ_CODE_READ_TRANSFER;
	ResearchNandIssue(0, 0, 0);
	mockNow = 70;
	ResearchNandPhaseComplete(0, 0);
	ResearchNandComplete(0, 0, 0, 1);
	ResearchNandIssue(3, 0, 0);
	mockNow = 75;
	ResearchNandPhaseComplete(0, 0);
	ResearchNandComplete(3, 0, 0, 1);
	mockNow = 80;
	ResearchNandIssue(1, 0, 0);
	assert(researchStats.hostNandReqCount == 1);
	assert(researchStats.hostQueueWaitCycles == 50);
	assert(researchStats.gcDieBlockedReqCount == 1);
	assert(researchStats.gcDieBlockedCycles == 50);
	assert(researchStats.hostSameDieGcIssueOverlapCycles == 35);
	assert(researchStats.hostSameDieGcIssueOverlapReqCount == 1);
	assert(researchStats.gcIssuedPhaseCycles == 45);
	assert(researchStats.gcExecutionCycles == 65);
	assert(researchStats.gcEraseCount == 1);
	assert(researchStats.gcReadPages == 1);
	mockNow = 90;
	ResearchNandPhaseComplete(0, 0);
	mockNow = 100;
	pool.reqPool[1].reqCode = REQ_CODE_READ_TRANSFER;
	ResearchNandIssue(1, 0, 0);
	mockNow = 110;
	ResearchNandPhaseComplete(0, 0);
	ResearchNandComplete(1, 0, 0, 1);
	assert(researchStats.hostQueueWaitCycles == 50); /* transfer not counted twice */
	assert(researchStats.hostNandReadPages == 1);
	ResearchStatsReset();
	mockNow = 120;
	ResearchNandEnqueue(0, 0, 0); /* pending GC but never issued */
	ResearchNandEnqueue(1, 0, 0);
	mockNow = 160;
	ResearchNandIssue(1, 0, 0);
	assert(researchStats.gcDieBlockedCycles == 40);
	assert(researchStats.hostSameDieGcIssueOverlapCycles == 0);
	ResearchNandPhaseComplete(0, 0);
	/* Different way on the same channel is a pending-channel proxy only. */
	pool.reqPool[2].reqOpt.reqOrigin = REQ_ORIGIN_HOST;
	pool.reqPool[2].reqCode = REQ_CODE_WRITE;
	ResearchNandEnqueue(2, 0, 1);
	mockNow = 180;
	ResearchNandIssue(2, 0, 1);
	assert(researchStats.gcChannelBlockedReqCount == 1);
	assert(researchStats.gcChannelBlockedCycles == 20);
	ResearchNandPhaseComplete(0, 1);
	ResearchNandComplete(2, 0, 1, 0);
	assert(researchStats.hostFailedReqCount == 1);
	assert(researchStats.hostNandProgramPages == 0);
	ResearchStatsReset();
	/* Two GCs queued on the same die retain independent start timestamps. */
	mockNow = 200;
	ResearchGcStart(0, 11);
	ResearchGcMigration(0);
	pool.reqPool[4].reqOpt.reqOrigin = REQ_ORIGIN_GC;
	pool.reqPool[4].reqCode = REQ_CODE_ERASE;
	ResearchGcReqCreated(0, 4);
	ResearchNandEnqueue(4, 0, 0);
	mockNow = 210;
	ResearchGcStart(0, 12);
	pool.reqPool[5].reqOpt.reqOrigin = REQ_ORIGIN_GC;
	pool.reqPool[5].reqCode = REQ_CODE_ERASE;
	ResearchGcReqCreated(0, 5);
	ResearchNandEnqueue(5, 0, 0);
	mockNow = 250;
	ResearchNandComplete(4, 0, 0, 1);
	mockNow = 270;
	ResearchNandComplete(5, 0, 0, 1);
	assert(researchStats.gcCount == 2);
	assert(researchStats.gcExecutionCycles == 110);
	assert(researchStats.gcMaxExecutionCycles == 60);
	ResearchMark(42);
	ResearchStatsPrint();
	ResearchTracePrint();
	puts("PASS: firmware telemetry, phase splitting, queue overlap, error accounting");
	return 0;
}
