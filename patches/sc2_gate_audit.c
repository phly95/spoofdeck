/*
 * sc2_gate_audit.c — LD_AUDIT library to spoof BLE controller as USB
 *
 * Instead of patching 7+ code layers, this finds the controller struct in
 * memory and patches its state fields so Steam treats it as a USB controller:
 *   [esi+0x17c] = 1  (haptic gate open)
 *   [esi+0x10c] = 1  (transport type = USB dongle)
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

/* Controller struct field offsets (from scheduler disassembly) */
#define OFF_GATE     0x17c  /* [esi+0x17c] — haptic gate (0=BLE, 1=USB) */
#define OFF_TRANSPORT 0x10c /* [esi+0x10c] — transport type (0=BLE, 1=USB) */
#define OFF_HAPTIC_A 0xa0   /* [esi+0xa0] — haptic active flag */

/* Size bounds for controller struct (from code analysis) */
#define STRUCT_MIN_SIZE 0x400
#define STRUCT_MAX_SIZE 0x1000

static uintptr_t g_code_base = 0;
static uintptr_t g_code_end = 0;
static volatile int g_patched = 0;

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

/* Check if a pointer looks like it could be a vtable into steamclient.so */
static int is_valid_vtable(uintptr_t ptr) {
    return (ptr >= g_code_base && ptr < g_code_end);
}

/* Check if memory at addr looks like a controller struct candidate.
 * Requirements:
 *   - [addr+0] is a valid vtable pointer into steamclient.so code
 *   - [addr+0x17c] = 0 (BLE gate, not set)
 *   - [addr+0x10c] = 0 (BLE transport)
 *   - Struct is a reasonable size (no invalid page accesses)
 */
static int is_controller_struct(uintptr_t addr) {
    uintptr_t vtable;
    uint8_t gate, transport;

    /* Read vtable pointer */
    memcpy(&vtable, (void *)addr, sizeof(vtable));
    if (!is_valid_vtable(vtable))
        return 0;

    /* Read gate and transport fields */
    gate = *(volatile uint8_t *)(addr + OFF_GATE);
    transport = *(volatile uint8_t *)(addr + OFF_TRANSPORT);

    /* For BLE controller, both should be 0 */
    if (gate != 0 || transport != 0)
        return 0;

    return 1;
}

/* Scan a memory region for controller struct candidates */
static void scan_region(uintptr_t start, uintptr_t end) {
    long page_size = sysconf(_SC_PAGESIZE);

    for (uintptr_t addr = start; addr < end; addr += page_size) {
        /* Quick check: first 4 bytes must be a valid vtable pointer */
        uintptr_t maybe_vtable;
        memcpy(&maybe_vtable, (void *)addr, sizeof(maybe_vtable));
        if (!is_valid_vtable(maybe_vtable))
            continue;

        /* Found a candidate — verify it */
        if (!is_controller_struct(addr))
            continue;

        /* Found the controller struct! Patch the state fields */
        /* Make the page writable */
        uintptr_t page_start = addr & ~(page_size - 1);
        if (mprotect((void *)page_start, page_size * 2, PROT_READ | PROT_WRITE) != 0)
            continue;

        /* Patch gate and transport to USB values */
        *(volatile uint8_t *)(addr + OFF_GATE) = 1;
        *(volatile uint8_t *)(addr + OFF_TRANSPORT) = 1;

        /* Restore page protection */
        mprotect((void *)page_start, page_size * 2, PROT_READ);

        g_patched = 1;
    }
}

/* Background scanner thread */
static void *scanner_thread(void *arg) {
    (void)arg;

    /* Wait for steamclient.so to be loaded */
    for (int i = 0; i < 200 && g_code_base == 0; i++)
        usleep(50000);

    if (g_code_base == 0) return NULL;

    /* Keep scanning until we find and patch the controller struct */
    int attempts = 0;
    while (!g_patched && attempts < 600) {
        /* Read /proc/self/maps to find writable regions */
        FILE *maps = fopen("/proc/self/maps", "r");
        if (!maps) { usleep(100000); attempts++; continue; }

        char line[512];
        while (fgets(line, sizeof(line), maps)) {
            unsigned long start, end;
            char perms[5];
            if (sscanf(line, "%lx-%lx %4s", &start, &end, perms) != 3)
                continue;

            /* Only scan writable regions (heap, data) */
            if (perms[1] != 'w') continue;

            /* Skip the code section itself */
            if (start >= g_code_base && start < g_code_end) continue;

            scan_region(start, end);
            if (g_patched) break;
        }
        fclose(maps);

        if (!g_patched) usleep(200000); /* 200ms between scans */
        attempts++;
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
    if (g_patched) return 0;

    const char *name = map->l_name ? map->l_name : "";
    if (strstr(name, "steamclient.so")) {
        /* Record the code section range */
        g_code_base = map->l_addr;

        /* Find the end of the code section from ELF headers */
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

        /* Start the scanner thread */
        pthread_t tid;
        pthread_create(&tid, NULL, scanner_thread, NULL);
        pthread_detach(tid);
    }
    return 0;
}
