/*
 * sc2_gate_audit.c — LD_AUDIT library: vtable swap experiment A→C
 *
 * Tests whether swapping the BLE vtable (A) to the scheduler-expected
 * vtable (C) makes haptic dispatch proceed.
 *
 * NO classification patch — clean A/B test.
 * Does NOT mprotect heap pages to RX — only writes if page is already writable.
 *
 * Build (32-bit):
 *   gcc -m32 -shared -fPIC -o sc2_gate_audit.so sc2_gate_audit.c -lpthread
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
#include <pthread.h>
#include <errno.h>
#include <elf.h>

static uintptr_t g_code_base = 0;
static uintptr_t g_code_end = 0;
static volatile int g_vtable_swapped = 0;

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

static int is_code_ptr(uintptr_t ptr) {
    return ptr >= g_code_base && ptr < g_code_end;
}

/*
 * Vtable addresses computed from ELF layout:
 *   Data segment: file_offset=0x2e4dc80, vaddr=0x02e4fc80
 *   Vtable A (BLE):     file_offset=0x2e6ae2c → vaddr=0x02e6ce2c
 *   Vtable C (expected): file_offset=0x2e6a940 → vaddr=0x02e6c940
 *
 * Runtime address = g_code_base + vaddr
 */
#define VTABLE_A_VADDR 0x02e6ce2c
#define VTABLE_C_VADDR 0x02e6c940

/* Controller struct field offsets */
#define OFF_VTABLE    0x00
#define OFF_GATE      0x17c
#define OFF_TRANSPORT 0x10c

static void *patch_thread(void *arg) {
    (void)arg;

    /* Wait for steamclient.so to load */
    for (int i = 0; i < 400 && g_code_base == 0; i++)
        usleep(150000);
    if (g_code_base == 0) {
        fprintf(stderr, "[sc2_audit] TIMEOUT: steamclient.so not loaded\n");
        return NULL;
    }

    uintptr_t vt_a = g_code_base + VTABLE_A_VADDR;
    uintptr_t vt_c = g_code_base + VTABLE_C_VADDR;

    fprintf(stderr, "[sc2_audit] base=%p vt_a=%p vt_c=%p\n",
            (void *)g_code_base, (void *)vt_a, (void *)vt_c);

    /* Verify vtable C exists and has reasonable entries */
    uint32_t c74 = *(volatile uint32_t *)(vt_c + 0x74);
    uint32_t c84 = *(volatile uint32_t *)(vt_c + 0x84);
    uint32_t c00 = *(volatile uint32_t *)(vt_c + 0x00);
    fprintf(stderr, "[sc2_audit] vt_c[0]=0x%08x vt_c[0x74]=0x%08x vt_c[0x84]=0x%08x\n",
            c00, c74, c84);

    if (!is_code_ptr(c00) || !is_code_ptr(c74) || !is_code_ptr(c84)) {
        fprintf(stderr, "[sc2_audit] vt_c entries don't look like code pointers — aborting\n");
        return NULL;
    }

    fprintf(stderr, "[sc2_audit] vt_c looks valid, scanning for controllers...\n");

    /* Wait for controllers to be created */
    sleep(3);

    /* Scan heap for controller objects with vtable A */
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return NULL;

    long page_size = sysconf(_SC_PAGESIZE);
    char line[512];
    int found = 0;

    while (fgets(line, sizeof(line), maps)) {
        unsigned long start, end;
        char perms[5];
        if (sscanf(line, "%lx-%lx %4s", &start, &end, perms) != 3) continue;
        if (perms[1] != 'w') continue;

        for (uintptr_t addr = start; addr < end - 0x200; addr += 4) {
            uintptr_t vt;
            memcpy(&vt, (void *)addr, sizeof(vt));
            if (vt != vt_a) continue;

            /* Quick controller filter */
            uint8_t gate = *(volatile uint8_t *)(addr + OFF_GATE);
            uint8_t transport = *(volatile uint8_t *)(addr + OFF_TRANSPORT);
            if (gate > 5 || transport > 5) continue;

            fprintf(stderr, "[sc2_audit] Candidate at %p (gate=%d trans=%d)\n",
                    (void *)addr, gate, transport);

            if (g_vtable_swapped == 0) {
                /* Swap vtable A → C (page is already rw-p, no mprotect needed) */
                *(uintptr_t *)addr = vt_c;

                uintptr_t verify;
                memcpy(&verify, (void *)addr, sizeof(verify));
                if (verify == vt_c) {
                    fprintf(stderr, "[sc2_audit] VTABLE SWAPPED A→C at %p\n", (void *)addr);
                    g_vtable_swapped = 1;
                } else {
                    fprintf(stderr, "[sc2_audit] SWAP VERIFY FAILED\n");
                }
            }
            found++;
        }
    }
    fclose(maps);

    if (found == 0)
        fprintf(stderr, "[sc2_audit] No controllers with vtable A found\n");
    else
        fprintf(stderr, "[sc2_audit] Found %d controller(s), swapped %d\n", found, g_vtable_swapped);

    /* Retry if no swap happened yet */
    for (int retry = 0; retry < 10 && g_vtable_swapped == 0; retry++) {
        fprintf(stderr, "[sc2_audit] Retry %d...\n", retry + 1);
        sleep(2);
        /* Re-read maps in case new regions appeared */
        maps = fopen("/proc/self/maps", "r");
        if (!maps) continue;
        while (fgets(line, sizeof(line), maps)) {
            unsigned long start, end;
            char perms[5];
            if (sscanf(line, "%lx-%lx %4s", &start, &end, perms) != 3) continue;
            if (perms[1] != 'w') continue;
            for (uintptr_t addr = start; addr < end - 0x200 && g_vtable_swapped == 0; addr += 4) {
                uintptr_t vt;
                memcpy(&vt, (void *)addr, sizeof(vt));
                if (vt != vt_a) continue;
                uint8_t gate = *(volatile uint8_t *)(addr + OFF_GATE);
                uint8_t transport = *(volatile uint8_t *)(addr + OFF_TRANSPORT);
                if (gate > 5 || transport > 5) continue;
                *(uintptr_t *)addr = vt_c;
                uintptr_t verify;
                memcpy(&verify, (void *)addr, sizeof(verify));
                if (verify == vt_c) {
                    fprintf(stderr, "[sc2_audit] VTABLE SWAPPED A→C at %p (retry)\n", (void *)addr);
                    g_vtable_swapped = 1;
                }
            }
        }
        fclose(maps);
    }

    return NULL;
}

unsigned int la_version(unsigned int version) {
    return version;
}

void la_preinit(uintptr_t *cookie) {
    if (!is_steam_process()) return;
    strip_from_ld_audit();
}

unsigned int la_objopen(struct link_map *map, Lmid_t lmid, uintptr_t *cookie) {
    if (g_code_base != 0) return 0;

    const char *name = map->l_name ? map->l_name : "";
    if (strstr(name, "steamclient.so")) {
        g_code_base = map->l_addr;

        Elf32_Ehdr *ehdr = (Elf32_Ehdr *)map->l_addr;
        Elf32_Phdr *phdr = (Elf32_Phdr *)((uintptr_t)ehdr + ehdr->e_phoff);
        uintptr_t max_end = 0;
        for (int i = 0; i < ehdr->e_phnum; i++) {
            if (phdr[i].p_type == PT_LOAD) {
                uintptr_t seg_end = map->l_addr + phdr[i].p_vaddr + phdr[i].p_memsz;
                if (seg_end > max_end) max_end = seg_end;
            }
        }
        g_code_end = max_end;

        fprintf(stderr, "[sc2_audit] steamclient.so at %p\n", (void *)g_code_base);

        pthread_t tid;
        pthread_create(&tid, NULL, patch_thread, NULL);
        pthread_detach(tid);
    }
    return 0;
}
