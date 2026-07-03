/*
 * sc2_gate_audit.c — LD_AUDIT library to patch Steam Client 0x8F haptic gate
 *
 * Patches four blocking conditions in the haptic scheduler function:
 *   1. Primary gate: jne -> jmp at vaddr 0x0123e602 (file 0x0123d602)
 *   2. BLOCK1: param_4==0 check: je -> nop nop at vaddr 0x0123e89a (file 0x0123d89a)
 *   3. BLOCK2: [esi+0x10c] transport check: je -> jmp at vaddr 0x0123e8b6 (file 0x0123d8b6)
 *   4. BLOCK5: secondary [esi+0x10c] check: je -> nop nop nop nop nop nop at vaddr 0x0123e6df (file 0x0123d6df)
 *
 * Follows SLSsteam's proven pattern for LD_AUDIT injection.
 *
 * Build (32-bit):
 *   gcc -m32 -shared -fPIC -o sc2_gate_audit.so sc2_gate_audit.c
 */

#define _GNU_SOURCE
#include <link.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <fcntl.h>

/* Patch targets (vaddr offsets into steamclient.so) */
#define GATE_VADDR      0x0123e602  /* jne -> jmp */
#define BLOCK1_VADDR    0x0123e89a  /* je -> nop nop */
#define BLOCK2_VADDR    0x0123e8b6  /* je -> jmp */
#define BLOCK5_VADDR    0x0123e6df  /* je -> nop*6 */

static int g_patched = 0;

static void strip_from_ld_audit(void) {
    unsetenv("LD_AUDIT");
}

static int is_steam_process(void) {
    char comm[16] = {0};
    int fd = open("/proc/self/comm", O_RDONLY);
    if (fd >= 0) {
        read(fd, comm, sizeof(comm) - 1);
        close(fd);
    }
    size_t len = strlen(comm);
    if (len > 0 && comm[len-1] == '\n') comm[len-1] = '\0';
    return (strcmp(comm, "steam") == 0);
}

static int patch_bytes(uintptr_t base, uintptr_t vaddr,
                       const uint8_t *expected, const uint8_t *replacement,
                       size_t expect_len, size_t repl_len) {
    uintptr_t target = base + vaddr;
    long page_size = sysconf(_SC_PAGESIZE);
    uintptr_t page_start = target & ~(page_size - 1);

    if (mprotect((void *)page_start, page_size, PROT_READ | PROT_WRITE | PROT_EXEC) != 0)
        return 0;

    uint8_t *insn = (uint8_t *)target;
    if (memcmp(insn, expected, expect_len) != 0) {
        mprotect((void *)page_start, page_size, PROT_READ | PROT_EXEC);
        return 0;
    }

    memcpy(insn, replacement, repl_len);
    mprotect((void *)page_start, page_size, PROT_READ | PROT_EXEC);
    return 1;
}

static void do_patch(uintptr_t base) {
    if (g_patched || base == 0) return;

    int ok = 0;

    /* Patch 1: Primary gate - jne -> jmp */
    uint8_t gate_exp[] = {0x0f, 0x85};
    uint8_t gate_repl[] = {0xe9, 0x91};
    ok += patch_bytes(base, GATE_VADDR, gate_exp, gate_repl, 2, 2);

    /* Patch 2: BLOCK1 - param_4==0 check - je -> nop nop */
    uint8_t b1_exp[] = {0x74};
    uint8_t b1_repl[] = {0x90, 0x90};
    ok += patch_bytes(base, BLOCK1_VADDR, b1_exp, b1_repl, 1, 2);

    /* Patch 3: BLOCK2 - transport check - je -> jmp (force main path) */
    uint8_t b2_exp[] = {0x74};
    uint8_t b2_repl[] = {0xeb};
    ok += patch_bytes(base, BLOCK2_VADDR, b2_exp, b2_repl, 1, 1);

    /* Patch 4: BLOCK5 - secondary transport check - je -> nop*6 */
    uint8_t b5_exp[] = {0x0f, 0x84};
    uint8_t b5_repl[] = {0x90, 0x90, 0x90, 0x90, 0x90, 0x90};
    ok += patch_bytes(base, BLOCK5_VADDR, b5_exp, b5_repl, 2, 6);

    g_patched = (ok > 0);
}

unsigned int la_version(unsigned int version) {
    return version;
}

void la_preinit(uintptr_t *cookie) {
    if (!is_steam_process()) return;
    strip_from_ld_audit();
}

unsigned int la_objopen(struct link_map *map, Lmid_t lmid, uintptr_t *cookie) {
    if (g_patched) return 0;
    const char *name = map->l_name ? map->l_name : "";
    if (strstr(name, "steamclient.so")) {
        do_patch(map->l_addr);
    }
    return 0;
}
