/*
 * sc2_gate_audit.c — LD_AUDIT library: vtable A entry patch (A→C entries)
 *
 * Patches only vtable A's entries at +0x74 and +0x84 to match vtable C.
 * This tests whether the scheduler's vtable integrity check is the only
 * blocker preventing haptic dispatch.
 *
 * NO classification patch. NO heap scan. Just two vtable entry patches.
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

/*
 * Vtable offsets from ELF layout:
 *   Data segment: file_offset=0x2e4d000, load segment starts at load_bias+0x02e4fc80
 *   Vtable A: file_offset=0x2e6ae2c -> vaddr=0x02e6ce2c
 *   Vtable C: file_offset=0x2e6a940 -> vaddr=0x02e6c940
 *
 * The runtime address within the r--p segment:
 *   segment_load_addr = (data_seg_start_in_maps) + (vtable_vaddr - data_seg_vaddr)
 *   Since the 3rd LOAD segment maps file_offset 0x2e4d000 at some runtime addr,
 *   and vtable vaddr = vaddr_of_segment + offset_within_segment:
 *     runtime_vtable = segment_runtime_base + (vtable_vaddr - segment_vaddr)
 *
 * Simpler: for a shared library loaded at load_bias,
 *   runtime_vaddr = load_bias + vaddr
 * But the segments are mapped with different offsets. The 3rd segment
 * (r--p, rodata) has vaddr 0x02e4fc80 mapped at load_bias + 0x02e4fc80.
 * Actually since the first LOAD has vaddr=0, load_bias IS the first segment's
 * load address, and for the 3rd segment, runtime_addr = load_bias + vaddr.
 */
#define VTABLE_A_VADDR 0x02e6ce2c
#define VTABLE_C_VADDR 0x02e6c940

/* Offsets within vtable to patch */
#define VT_ENTRY_74  0x74
#define VT_ENTRY_84  0x84

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

static void *patch_thread(void *arg) {
    (void)arg;

    for (int i = 0; i < 400 && g_code_base == 0; i++)
        usleep(150000);
    if (g_code_base == 0) {
        fprintf(stderr, "[sc2_audit] TIMEOUT\n");
        return NULL;
    }

    uintptr_t vt_a = g_code_base + VTABLE_A_VADDR;
    uintptr_t vt_c = g_code_base + VTABLE_C_VADDR;

    fprintf(stderr, "[sc2_audit] base=%p vt_a=%p vt_c=%p\n",
            (void *)g_code_base, (void *)vt_a, (void *)vt_c);

    /* Read vtable C entries we want to copy */
    uint32_t c74 = *(volatile uint32_t *)(vt_c + VT_ENTRY_74);
    uint32_t c84 = *(volatile uint32_t *)(vt_c + VT_ENTRY_84);
    fprintf(stderr, "[sc2_audit] patching vt_a[0x74]: 0x%08x -> 0x%08x\n",
            *(volatile uint32_t *)(vt_a + VT_ENTRY_74), c74);
    fprintf(stderr, "[sc2_audit] patching vt_a[0x84]: 0x%08x -> 0x%08x\n",
            *(volatile uint32_t *)(vt_a + VT_ENTRY_84), c84);

    /* The vtable lives in the r--p (rodata) segment — need mprotect */
    long page_size = sysconf(_SC_PAGESIZE);
    uintptr_t page = vt_a & ~(page_size - 1);

    if (mprotect((void *)page, page_size, PROT_READ | PROT_WRITE) != 0) {
        fprintf(stderr, "[sc2_audit] mprotect RW failed: %s\n", strerror(errno));
        return NULL;
    }

    *(volatile uint32_t *)(vt_a + VT_ENTRY_74) = c74;
    *(volatile uint32_t *)(vt_a + VT_ENTRY_84) = c84;

    /* Restore to read-only */
    mprotect((void *)page, page_size, PROT_READ);

    /* Verify */
    uint32_t v74 = *(volatile uint32_t *)(vt_a + VT_ENTRY_74);
    uint32_t v84 = *(volatile uint32_t *)(vt_a + VT_ENTRY_84);
    fprintf(stderr, "[sc2_audit] vt_a[0x74] now=0x%08x (expected 0x%08x) %s\n",
            v74, c74, v74 == c74 ? "OK" : "MISMATCH");
    fprintf(stderr, "[sc2_audit] vt_a[0x84] now=0x%08x (expected 0x%08x) %s\n",
            v84, c84, v84 == c84 ? "OK" : "MISMATCH");

    if (v74 == c74 && v84 == c84)
        fprintf(stderr, "[sc2_audit] VTABLE ENTRIES PATCHED SUCCESSFULLY\n");
    else
        fprintf(stderr, "[sc2_audit] VTABLE PATCH FAILED\n");

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

        fprintf(stderr, "[sc2_audit] steamclient.so at %p\n", (void *)g_code_base);

        pthread_t tid;
        pthread_create(&tid, NULL, patch_thread, NULL);
        pthread_detach(tid);
    }
    return 0;
}
