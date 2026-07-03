/*
 * sc2_gate_patch_64.c — 64-bit LD_PRELOAD that patches 32-bit steamclient.so
 *
 * The Steam bootstrap process is 64-bit. It eventually execs the 32-bit
 * ubuntu12_32/steam binary which loads steamclient.so. Since LD_PRELOAD
 * must match ELF class, we provide a 64-bit library.
 *
 * This library installs an LD_PRELOAD interposition on execve() that
 * sets LD_PRELOAD for the 32-bit child process.
 *
 * Build:
 *   gcc -m64 -shared -fPIC -o sc2_gate_patch_64.so sc2_gate_patch_64.c
 *
 * Usage:
 *   LD_PRELOAD=./sc2_gate_patch_64.so /usr/games/steam
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>

static const char *PATCH_PATH = "/home/philip/spoofdeck-modified/patches/sc2_gate_patch.so";

typedef int (*execve_fn)(const char *, char *const[], char *const[]);
static execve_fn real_execve = NULL;

static int patched_execve(const char *pathname, char *const argv[], char *const envp[]) {
    if (!real_execve) {
        real_execve = (execve_fn)dlsym(RTLD_NEXT, "execve");
    }

    /* Check if this is the 32-bit steam binary */
    if (pathname && strstr(pathname, "ubuntu12_32/steam")) {
        /* Build new envp with our LD_PRELOAD prepended */
        int envc = 0;
        while (envp[envc]) envc++;

        char **new_envp = malloc((envc + 3) * sizeof(char *));
        if (!new_envp) return real_execve(pathname, argv, envp);

        int idx = 0;
        new_envp[idx++] = strdup("LD_PRELOAD=" PATCH_PATH);

        /* Copy existing env, skip any existing LD_PRELOAD */
        for (int i = 0; i < envc; i++) {
            if (strncmp(envp[i], "LD_PRELOAD=", 11) != 0) {
                new_envp[idx++] = strdup(envp[i]);
            }
        }
        new_envp[idx] = NULL;

        fprintf(stderr, "[sc2_gate_patch_64] Injecting LD_PRELOAD into ubuntu12_32/steam\n");
        int ret = real_execve(pathname, argv, new_envp);

        /* Cleanup on failure */
        for (int i = 0; i < idx; i++) free(new_envp[i]);
        free(new_envp);
        return ret;
    }

    return real_execve(pathname, argv, envp);
}

__attribute__((constructor))
static void init(void) {
    real_execve = (execve_fn)dlsym(RTLD_NEXT, "execve");
    /* Also patch __xexecve if present */
}
