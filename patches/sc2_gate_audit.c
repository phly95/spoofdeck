/*
 * sc2_gate_audit.c — LD_AUDIT: hook scheduler to find real controller,
 * then redirect its vtable to a patched copy.
 *
 * Phase 1: Hook 0x123e5fb (gate check), log esi when gate==1
 * Phase 2: After capturing esi, redirect its vtable to patched copy
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
#include <signal.h>

static uintptr_t g_code_base = 0;
static uintptr_t g_scheduler_gate_check = 0;  /* 0x123e5fb + base */

/* The controller address we capture from the scheduler */
static volatile uintptr_t g_captured_esi = 0;
static volatile int g_controller_found = 0;

/* Vtable patched copy */
static void *g_vt_copy = 0;

#define VTABLE_A_VADDR 0x02e6ce2c
#define VTABLE_C_VADDR 0x02e6c940

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

/*
 * Signal handler: called when scheduler gate check fires.
 * We use SIGTRAP via int3 breakpoint at the gate check address.
 *
 * The breakpoint at 0x123e5fb fires BEFORE the gate comparison.
 * At this point, esi contains the controller pointer.
 *
 * We can't easily read registers from a signal handler in 32-bit,
 * so instead we use a different approach:
 *
 * Patch the instruction at 0x123e5fb to call our trampoline.
 */

/* Trampoline: called from the patched gate check site.
 * The original instruction is:
 *   123e5fb: cmp BYTE PTR [esi+0x17c], 0x0
 * We replace it with a call to this function.
 *
 * We use inline asm to capture esi. */
static void __attribute__((used)) capture_esi_from_asm(uint32_t esi_val);

asm(
    ".globl capture_esi_from_asm\n"
    "capture_esi_from_asm:\n"
    "  push %eax\n"
    "  push %ebx\n"
    "  mov  %edi, %ebx\n"  /* esi is callee-saved, edi might hold it */
    "  call capture_esi_real\n"
    "  pop  %ebx\n"
    "  pop  %eax\n"
    "  ret\n"
);

/* Better approach: just scan and poll.
 * Use the first few seconds after launch to poll esi candidates.
 * The scheduler is called frequently, so we can intercept it
 * by setting a hardware breakpoint via ptrace from a helper thread.
 *
 * Actually, the simplest approach that works:
 * Use the SIGTRAP + ptrace approach from a monitoring thread.
 */

/* Monitoring thread: use ptrace to set breakpoint at gate check */
static void *monitor_thread(void *arg) {
    (void)arg;

    for (int i = 0; i < 400 && g_code_base == 0; i++)
        usleep(150000);
    if (g_code_base == 0) return NULL;

    uintptr_t vt_a = g_code_base + VTABLE_A_VADDR;
    uintptr_t vt_c = g_code_base + VTABLE_C_VADDR;

    fprintf(stderr, "[sc2_audit] base=%p vt_a=%p vt_c=%p\n",
            (void *)g_code_base, (void *)vt_a, (void *)vt_c);

    /* Wait for Steam to fully initialize */
    sleep(5);

    /* Instead of hooking, let's try a different strategy:
     * Find the controller by looking for objects that:
     * 1. Have vtable A
     * 2. Have gate=1, transport=1
     * 3. Have a non-zero value at +0x38 that looks like a vtable pointer
     * 4. Have a field at +0x3c or +0x44 that is a code pointer
     * 5. The field at +0x04 should be 3 (the controller state machine state)
     *
     * From the candidates we saw:
     *   bc=0 [04]=0x00000003 [38]=0xcc390e2c  -- likely controller
     *   bc=3 [04]=0x00007d00 [38]=0x00000001  -- likely NOT controller
     *
     * The controller should have [0x04]=3 (connected state) and
     * [0x38] pointing to a vtable-like address.
     */

    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return NULL;

    char line[512];
    uintptr_t best_controller = 0;
    int best_score = -1;

    while (fgets(line, sizeof(line), maps)) {
        unsigned long start, end;
        char perms[5];
        if (sscanf(line, "%lx-%lx %4s", &start, &end, perms) != 3) continue;
        if (perms[1] != 'w') continue;

        for (uintptr_t addr = start; addr < end - 0x200; addr += 4) {
            uintptr_t vt;
            memcpy(&vt, (void *)addr, sizeof(vt));
            if (vt != vt_a) continue;

            uint8_t gate      = *(volatile uint8_t *)(addr + 0x17c);
            uint8_t transport = *(volatile uint8_t *)(addr + 0x10c);
            uint32_t bc       = *(volatile uint32_t *)(addr + 0xbc);
            uint32_t f04      = *(volatile uint32_t *)(addr + 0x04);
            uint32_t f38      = *(volatile uint32_t *)(addr + 0x38);

            if (gate != 1 || transport != 1) continue;
            if (bc > 10) continue;

            /* Score each candidate */
            int score = 0;
            if (f04 == 3) score += 10;      /* controller state 3 = active */
            if (f38 > g_code_base && f38 < g_code_base + 0x3000000) score += 5; /* vtable-like ptr */
            if (bc == 0) score += 3;         /* initial classification */

            if (score > best_score) {
                best_score = score;
                best_controller = addr;
                fprintf(stderr, "[sc2_audit]   best candidate so far: 0x%08x score=%d bc=%d [04]=0x%08x [38]=0x%08x\n",
                        (uint32_t)addr, score, bc, f04, f38);
            }
        }
    }
    fclose(maps);

    if (!best_controller || best_score < 5) {
        fprintf(stderr, "[sc2_audit] No strong controller candidate found (best score=%d)\n", best_score);
        return NULL;
    }

    fprintf(stderr, "[sc2_audit] Best controller candidate: 0x%08x score=%d\n",
            (uint32_t)best_controller, best_score);

    /* Create patched vtable copy */
    size_t vt_size = 0x200;
    void *vt_copy = malloc(vt_size);
    if (!vt_copy) return NULL;
    memcpy(vt_copy, (void *)vt_a, vt_size);

    uint32_t old74 = *(volatile uint32_t *)(vt_a + 0x74);
    uint32_t new74 = *(volatile uint32_t *)(vt_c + 0x74);
    uint32_t old84 = *(volatile uint32_t *)(vt_a + 0x84);
    uint32_t new84 = *(volatile uint32_t *)(vt_c + 0x84);

    ((uint32_t *)vt_copy)[0x74 / 4] = new74;
    ((uint32_t *)vt_copy)[0x84 / 4] = new84;

    fprintf(stderr, "[sc2_audit] Patched copy: [0x74] 0x%08x->0x%08x [0x84] 0x%08x->0x%08x\n",
            old74, new74, old84, new84);

    /* Redirect */
    *(uintptr_t *)best_controller = (uintptr_t)vt_copy;
    uintptr_t verify = *(volatile uintptr_t *)best_controller;

    if (verify == (uintptr_t)vt_copy) {
        fprintf(stderr, "[sc2_audit] VTABLE REDIRECTED to 0x%08x\n", (uint32_t)vt_copy);
        g_vt_copy = vt_copy;
        g_captured_esi = best_controller;
        g_controller_found = 1;
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

        fprintf(stderr, "[sc2_audit] steamclient.so at %p\n", (void *)g_code_base);

        pthread_t tid;
        pthread_create(&tid, NULL, monitor_thread, NULL);
        pthread_detach(tid);
    }
    return 0;
}
