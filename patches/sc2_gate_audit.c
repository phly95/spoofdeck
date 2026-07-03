/*
 * sc2_gate_audit.c — LD_AUDIT library to patch Steam Client 0x8F haptic gate
 *
 * Follows SLSsteam's proven pattern:
 * 1. la_preinit: Strip ourselves from LD_AUDIT, only patch in "steam" process
 * 2. la_objopen: Patch when steamclient.so is loaded via dlopen
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
#include <limits.h>

/* File offset of the jne instruction in ubuntu12_32/steamclient.so
 * cmp byte [esi+0x17c], 0 at vaddr 0x0123e5fb (7 bytes)
 * jne rel32 at vaddr 0x0123e602 */
#define GATE_JNE_VADDR 0x0123e602

static int g_patched = 0;

/* Remove our library from LD_AUDIT to prevent re-injection in child processes.
 * This is what SLSsteam does in cleanEnvVar(). */
static void strip_from_ld_audit(void) {
    const char *var = getenv("LD_AUDIT");
    if (!var) return;

    /* Simple approach: unset LD_AUDIT entirely. The 32-bit ld.so already loaded us. */
    unsetenv("LD_AUDIT");
}

static int is_steam_process(void) {
    /* Read /proc/self/comm to check process name */
    char comm[16] = {0};
    int fd = open("/proc/self/comm", O_RDONLY);
    if (fd >= 0) {
        read(fd, comm, sizeof(comm) - 1);
        close(fd);
    }
    /* Strip trailing newline */
    size_t len = strlen(comm);
    if (len > 0 && comm[len-1] == '\n') comm[len-1] = '\0';

    return (strcmp(comm, "steam") == 0);
}

static void do_patch(uintptr_t base) {
    if (g_patched || base == 0) return;

    uintptr_t target = base + GATE_JNE_VADDR;
    long page_size = sysconf(_SC_PAGESIZE);
    uintptr_t page_start = target & ~(page_size - 1);

    if (mprotect((void *)page_start, page_size, PROT_READ | PROT_WRITE | PROT_EXEC) != 0)
        return;

    uint8_t *insn = (uint8_t *)target;

    /* Verify: must be jne (0f 85) */
    if (insn[0] != 0x0f || insn[1] != 0x85) {
        mprotect((void *)page_start, page_size, PROT_READ | PROT_EXEC);
        return;
    }

    /* Patch: jne (0f 85 90 02 00 00) -> jmp (e9 91 02 00 00 90)
     * jne is 6 bytes, jmp is 5 bytes + nop. Offset +1. */
    insn[0] = 0xe9;
    insn[1] = 0x91;
    insn[2] = 0x02;
    insn[3] = 0x00;
    insn[4] = 0x00;
    insn[5] = 0x90;

    mprotect((void *)page_start, page_size, PROT_READ | PROT_EXEC);
    g_patched = 1;
}

unsigned int la_version(unsigned int version) {
    return version;
}

void la_preinit(uintptr_t *cookie) {
    /* Only run in the main steam process */
    if (!is_steam_process()) return;

    /* Strip ourselves from LD_AUDIT to prevent re-injection in child processes */
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
