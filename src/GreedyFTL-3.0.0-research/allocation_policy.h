#ifndef RESEARCH_ALLOCATION_POLICY_H_
#define RESEARCH_ALLOCATION_POLICY_H_

/* Called AFTER allocating a page and advancing currentPage. This exact helper
 * is exercised by the host C tests; validate physical ALLOC traces on-board too. */
static inline unsigned int ResearchNextAllocationDie(unsigned int currentDie,
	unsigned int ch, unsigned int way, unsigned int currentPage)
{
	(void)currentPage;
	(void)currentDie;
#if defined(ALLOCATION_POLICY_PAGE_FIRST)
	if(currentPage < USER_PAGES_PER_BLOCK)
		return currentDie;
#endif
#if defined(ALLOCATION_POLICY_WAY_FIRST)
	way++;
	if(way == USER_WAYS) { way = 0; ch = (ch + 1) % USER_CHANNELS; }
#else
	ch++;
	if(ch == USER_CHANNELS) { ch = 0; way = (way + 1) % USER_WAYS; }
#endif
	return Pcw2VdieTranslation(ch, way);
}
#endif
