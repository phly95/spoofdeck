/*
 * sc2_gate_audit_64.c — 64-bit no-op stub for LD_AUDIT.
 * Does absolutely nothing. The 32-bit patcher does the real work.
 */
#define _GNU_SOURCE
#include <link.h>

unsigned int la_version(unsigned int version) {
    return version;
}

void la_preinit(uintptr_t *cookie) {
    /* intentionally empty — do NOT strip LD_AUDIT */
}

unsigned int la_objopen(struct link_map *map, Lmid_t lmid, uintptr_t *cookie) {
    return 0;
}
