#include <assert.h>
#include <stdio.h>
#define USER_PAGES_PER_BLOCK 4
#define Pcw2VdieTranslation(ch, way) ((ch) + (way) * USER_CHANNELS)
#include "../allocation_policy.h"

int main(void)
{
	unsigned int die = 0, i, ch, way, cursor, expected;
	unsigned int pages[USER_CHANNELS * USER_WAYS] = {0};
	for(i = 0; i < USER_CHANNELS * USER_WAYS * USER_PAGES_PER_BLOCK * 3; i++)
	{
		cursor = i;
#if defined(ALLOCATION_POLICY_PAGE_FIRST)
		cursor /= USER_PAGES_PER_BLOCK;
#endif
#if defined(ALLOCATION_POLICY_WAY_FIRST)
		expected = ((cursor / USER_WAYS) % USER_CHANNELS) + (cursor % USER_WAYS) * USER_CHANNELS;
#else
		expected = (cursor % USER_CHANNELS) + ((cursor / USER_CHANNELS) % USER_WAYS) * USER_CHANNELS;
#endif
		assert(die == expected);
		ch = die % USER_CHANNELS;
		way = die / USER_CHANNELS;
		if(pages[die] == USER_PAGES_PER_BLOCK) pages[die] = 0;
		pages[die]++;
		die = ResearchNextAllocationDie(die, ch, way, pages[die]);
	}
	puts("PASS: actual allocation helper across page/die wraps");
	return 0;
}
