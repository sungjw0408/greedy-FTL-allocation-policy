#ifndef RESEARCH_STATS_H_
#define RESEARCH_STATS_H_

#include "ftl_config.h"

typedef struct _RESEARCH_STATS {
	unsigned long long hostLogicalWriteBytes;
	unsigned long long hostNandProgramPages;
	unsigned long long gcNandProgramPages;
	unsigned long long gcReadPages;
	unsigned long long gcMigrationPages;
	unsigned long long gcEraseCount;
	unsigned long long gcCount;
	unsigned long long gcFailedReqCount;
	unsigned long long gcExecutionCycles;
	unsigned long long gcMaxExecutionCycles;
	unsigned long long gcDieBlockedReqCount;
	unsigned long long gcDieBlockedCycles;
	unsigned long long gcChannelBlockedReqCount;
	unsigned long long gcChannelBlockedCycles;
	unsigned long long hostNandReqCount;
	unsigned long long hostNandReadPages;
	unsigned long long hostFailedReqCount;
	unsigned long long hostQueueWaitCycles;
	unsigned long long hostSameDieGcIssueOverlapReqCount;
	unsigned long long hostSameDieGcIssueOverlapCycles;
	unsigned long long gcIssuedPhaseCycles;
} RESEARCH_STATS;

extern volatile RESEARCH_STATS researchStats;

void ResearchStatsInit(void);
void ResearchStatsReset(void);
void ResearchStatsPrint(void);
void ResearchTracePrint(void);
void ResearchMark(unsigned int marker);
unsigned int ResearchStatsIdle(void);

void ResearchAccountHostWrite(unsigned int nvmeBlockCount);
void ResearchGcStart(unsigned int dieNo, unsigned int victimBlock);
void ResearchGcMigration(unsigned int dieNo);
void ResearchGcReqCreated(unsigned int dieNo, unsigned int reqSlotTag);

void ResearchNandEnqueue(unsigned int reqSlotTag, unsigned int chNo, unsigned int wayNo);
void ResearchNandIssue(unsigned int reqSlotTag, unsigned int chNo, unsigned int wayNo);
void ResearchNandPhaseComplete(unsigned int chNo, unsigned int wayNo);
void ResearchNandComplete(unsigned int reqSlotTag, unsigned int chNo, unsigned int wayNo, unsigned int success);

#endif /* RESEARCH_STATS_H_ */
