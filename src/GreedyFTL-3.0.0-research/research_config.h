#ifndef RESEARCH_CONFIG_H_
#define RESEARCH_CONFIG_H_

/* 0: counters only; 1: GC/marker events; 2: NAND phases and Host queue waits.
 * All events are buffered in DRAM. Never dump them during a timed workload. */
#ifndef RESEARCH_TRACE_LEVEL
#define RESEARCH_TRACE_LEVEL 1
#endif
#ifndef RESEARCH_TRACE_CAPACITY
#define RESEARCH_TRACE_CAPACITY 2048
#endif
#if RESEARCH_TRACE_LEVEL < 0 || RESEARCH_TRACE_LEVEL > 2
#error "RESEARCH_TRACE_LEVEL must be 0, 1, or 2"
#endif
#if RESEARCH_TRACE_CAPACITY < 1
#error "RESEARCH_TRACE_CAPACITY must be positive"
#endif
#endif
