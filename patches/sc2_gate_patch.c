/*
 * sc2_gate_patch.c — LD_PRELOAD patch for Steam Client 0x8F haptic gate
 *
 * Patches the gate check at vaddr 0x0123e602 in ubuntu12_32/steamclient.so:
 *   Original: 0f 85 90 02 00 00  (jne +0x290 — jump if gate!=0)
 *   Patched:  e9 91 02 00 00 90  (jmp +0x291 — always jump)
 *
 * This makes the jump unconditional so BLE controllers (gate==0) get 0x8F
 * dispatch. USB/Dongle controllers (gate!=0) already took this jump, so
 * they are unaffected.
 *
 * Build (must be 32-bit to match steamclient.so):
 *   gcc -m32 -shared -fPIC -o sc2_gate_patch.so sc2_gate_patch.c -lpthread
 *
 * Usage:
 *   LD_PRELOAD=./sc2_gate_patch.so /usr/games/steam
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <errno.h>
#include <pthread.h>

/* File offset of the jne instruction in steamclient.so
 * cmp byte [esi+0x17c], 0 is at file offset 0x123d5fb (7 bytes)
 * jne rel32 follows immediately at file offset 0x123d602 */
#define GATE_JNE_FILE_OFFSET 0x0123d602

static volatile int g_patched = 0;

static void apply_patch(void) {
    if (g_patched) return;

    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return;

    char line[512];
    uintptr_t mapping_start = 0;
    unsigned long mapping_file_offset = 0;

    while (fgets(line, sizeof(line), maps)) {
        if (strstr(line, "steamclient.so")) {
            unsigned long start, end;
            unsigned long file_offset;
            char perms[5];
            if (sscanf(line, "%lx-%lx %4s %lx", &start, &end, perms, &file_offset) == 4) {
                /* Check if our target file offset falls within this mapping */
                if (GATE_JNE_FILE_OFFSET >= file_offset &&
                    GATE_JNE_FILE_OFFSET < file_offset + (end - start)) {
                    mapping_start = (uintptr_t)start;
                    mapping_file_offset = file_offset;
                    break;
                }
            }
        }
    }
    fclose(maps);

    if (mapping_start == 0) return;

    /* Target = mapping_start + (target_file_offset - mapping_file_offset) */
    uintptr_t target = mapping_start + (GATE_JNE_FILE_OFFSET - mapping_file_offset);

    long page_size = sysconf(_SC_PAGESIZE);
    uintptr_t page_start = target & ~(page_size - 1);

    if (mprotect((void *)page_start, page_size, PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
        fprintf(stderr, "[sc2_gate_patch] mprotect failed: %s\n", strerror(errno));
        return;
    }

    uint8_t *insn = (uint8_t *)target;
    if (insn[0] != 0x0f || insn[1] != 0x85) {
        fprintf(stderr, "[sc2_gate_patch] Unexpected bytes at 0x%lx: %02x %02x (expected 0f 85)\n",
                target, insn[0], insn[1]);
        return;
    }

    /* Patch: jne (0f 85 90 02 00 00) -> jmp (e9 91 02 00 00 90)
     * jne is 6 bytes, jmp is 5 bytes + nop. Offset adjusts by +1. */
    insn[0] = 0xe9;  /* jmp rel32 opcode */
    insn[1] = 0x91;  /* offset low byte (0x291 = 0x290 + 1) */
    insn[2] = 0x02;
    insn[3] = 0x00;
    insn[4] = 0x00;
    insn[5] = 0x90;  /* nop padding (jne was 6 bytes, jmp is 5) */

    mprotect((void *)page_start, page_size, PROT_READ | PROT_EXEC);

    g_patched = 1;
    fprintf(stderr, "[sc2_gate_patch] Patched jne->jmp at 0x%lx (mapping=0x%lx file_off=0x%lx)\n", target, (unsigned long)mapping_start, mapping_file_offset);
}

static void *patch_thread(void *arg) {
    (void)arg;
    for (int i = 0; i < 200 && !g_patched; i++) {
        usleep(50000);
        apply_patch();
    }
    if (!g_patched)
        fprintf(stderr, "[sc2_gate_patch] Failed to find steamclient.so after 10s\n");
    return NULL;
}

__attribute__((constructor))
static void init(void) {
    pthread_t tid;
    pthread_create(&tid, NULL, patch_thread, NULL);
    pthread_detach(tid);
}
