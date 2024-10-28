/*
 * Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
 * Ivannikov Institute for System Programming of the Russian Academy of Sciences
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>

#include "which.h"
#include "env.h"
#include "client.h"
#include "lock.h"

#define DELIMITER "||"

//#define DMSG(...)  fprintf(stderr, __VA_ARGS__)
#define DMSG(...)  do{} while(0)

static void expand_newlines(char *dest, const char *src) {
    for (size_t i = 0; i < strlen(src); i++) {
        switch(src[i]) {
            case '\n':
                dest += sprintf(dest, "\\n");
                if (i + 1 < strlen(src) && src[i + 1] == '\r') {
                    i++;
                }
                break;
            case '\r':
                dest += sprintf(dest, "\\n");
                if (i + 1 < strlen(src) && src[i + 1] == '\n') {
                    i++;
                }
                break;

            default:
                *(dest++) = src[i];
        }
    }

    *dest = '\0';
}

// Returned buffer may be up to twice as large as necessary
static char *expand_newlines_alloc(const char *src) {
    char *dest = malloc(2 * strlen(src) + 1);
    expand_newlines(dest, src);
    return dest;
}

static char *prepare_exec_data(const char *path, char const *const argv[], char **envp) {
    unsigned args_len = 1, written_len = 0;

    // Concatenate all command-line arguments together using "||" as delimeter.
    for (const char *const *arg = argv; arg && *arg; arg++) {
        // Argument might be replaced by a new large string with escaped newlines
        args_len += 2 * strlen(*arg) + 1;
        // Each separator will require additional bytes
        if ((arg + 1) && *(arg + 1))
            args_len += strlen(DELIMITER);
    }

    // Get current working directory
    char *cwd = getcwd(NULL, 0);
    if (!cwd) {
        // DMSG("Couldn't get current working directory: %d\n", errno);
        cwd = "";
    }

    // Sometimes "path" contains incorrect values ("gcc" instead of "/usr/bin/gcc")
    char *correct_path = NULL;
    if (access(path, X_OK)) {
        correct_path = which(path);
    }

    if (!correct_path) {
        correct_path = (char *)path;
    }

    // Allocate memory to store the data + cwd + which + PID (50) + delimeters.
    char *data = malloc(args_len + strlen(cwd) + strlen(DELIMITER) * 3 + 50
                        + strlen(correct_path) + strlen("\n"));

    if (!data) {
        DMSG("Couldn't allocate memory\n");
        exit(EXIT_FAILURE);
    }

    char *parent_id = get_parent_id(envp);
    written_len += sprintf(data + written_len, "%s%s%s%s%s%s",
        cwd, DELIMITER,
        parent_id, DELIMITER,
        correct_path, DELIMITER
    );
    free(parent_id);

    // if cwd == "" then it wasn't returned by malloc inside getcwd
    if (cwd && cwd[0] != '\0') {
        free(cwd);
    }

    for (const char *const *arg = argv; arg && *arg; arg++) {
        char *exp_arg = expand_newlines_alloc(*arg);
        written_len += sprintf(data + written_len, "%s", exp_arg);
        free(exp_arg);

        if ((arg + 1) && *(arg + 1))
            written_len += sprintf(data + written_len, DELIMITER);
    }

    written_len += sprintf(data + written_len, "\n");

    return data;
}

static char *prepare_open_data(const char *path, int flags) {
    // Allocate memory to store the CMD_ID + existence + path + " " and "\n".
    char *data = malloc(sizeof(int) * 3 + strlen("   \n") + strlen(path));

    if (!data) {
        DMSG("Couldn't allocate memory\n");
        exit(EXIT_FAILURE);
    }

    int exists = 1;
    if (access(path, F_OK)) {
        exists = 0;
    }

    int cmd_id = get_cmd_id();

    sprintf(data, "%d %d %d %s\n", cmd_id, exists, flags, path);

    return data;
}

static char *prepare_env_data(char const *const envp[]) {
    unsigned envs_len = 1, written_len = 0;

    for (const char *const *env = envp; env && *env; env++) {
        envs_len += 2 * strlen(*env) + strlen("\n");
    }

    char *data = malloc(envs_len + strlen("\n"));

    if (!data) {
        DMSG("Couldn't allocate memory\n");
        exit(EXIT_FAILURE);
    }

    for (const char *const *env = envp; env && *env; env++) {
        char *exp_env = expand_newlines_alloc(*env);
        written_len += sprintf(data + written_len, "%s\n", exp_env);
        free(exp_env);
    }

    written_len += sprintf(data + written_len, "\n");

    return data;
}

static void store_data(const char *data, const char *data_file) {
    FILE *f = fopen(data_file, "a");
    if (!f) {
        DMSG("Couldn't open %s file\n", data_file);
        exit(EXIT_FAILURE);
    }

    fprintf(f, "%s", data);
    fclose(f);
}

void intercept_exec_call(const char *path, char const *const argv[], char **envp) {
    char *data_file = getenv_or_fail(CLADE_INTERCEPT_EXEC_ENV);
    char *env_vars_file = getenv(CLADE_ENV_VARS_ENV);

    clade_lock();

    // Data with intercepted command which will be stored
    char *data = prepare_exec_data(path, argv, envp);

    if (getenv(CLADE_PREPROCESS_ENV))
        send_data(data);
    else
        store_data(data, data_file);

    if (env_vars_file) {
        char *envs = prepare_env_data((char const *const *)envp);
        store_data(envs, env_vars_file);
        free(envs);
    }

    free(data);

    clade_unlock();
}

void intercept_open_call(const char *path, int flags) {
    char *data_file = getenv_or_fail(CLADE_INTERCEPT_OPEN_ENV);

    clade_lock();

    // Data with intercepted command which will be stored
    char *data = prepare_open_data(path, flags);
    store_data(data, data_file);
    free(data);

    clade_unlock();
}

bool endswith(const char *str, const char *end) {
  size_t l1 = strlen(end);
  size_t l2 = strlen(str);

  if(l1 > l2) {
    return false;
  }

  while (l1 > 0 && l2 > 0) {
    unsigned c1 = *(end + l1 - 1);
    unsigned c2 = *(str + l2 - 1);
    if (c1 != c2)
      return false;
    l1--;
    l2--;
  }
  return true;
}

char const *const compile_cmds[] = {"cc1", "as", "ld",
    "gcc",
    0 };

char const *const skipped_cmds[] = {"fixdep", "readelf", "objcopy",
    "vdso2c", "relocs", "sorttable",
    "mkcpustr", "mkpiggy", "tools/build",
    "objtool", "gen_init_cpio", "extract-cert",
    "genheaders", "asn1_compiler", "gen_crc32table",
    "conmakehash", "strip",
    "xargs", "objdump", "mk_elfconfig",
    "kallsyms", "scripts/unifdef", "scripts/ipe/polgen/polgen",
    "mktables", "gen_crc64table", "drivers/video/logo/pnmtologo",
    "dtc/dtc",
    0 };

bool should_skip(const char *path, char const *const argv[], char *const *envp) {
    DMSG("Exec %s\n", path);

    bool skip = false;
    bool compile = false;
    char *output = 0;
    char *deps = 0;
    bool ar = false;
    char *dumpdir = 0;
    char *dumpbase = 0;
    bool modpost = false;
    char *export = 0;

    const char *const *arg = argv;

    // check command name
    if(arg && *arg) {
        for(const char *const *cmd = compile_cmds; cmd && *cmd; cmd++) {
            if(endswith(*arg, *cmd)) {
                //skip compile command
                DMSG("Compile command with name %s\n", *arg);
                compile = true;
            }
        }

        for(const char *const *cmd = skipped_cmds; cmd && *cmd; cmd++) {
            if(endswith(*arg, *cmd)) {
                DMSG("Skip command '%s' with name %s\n", *cmd, *arg);
                skip = true;
            }
        }

        if(endswith(*arg, "ar")) {
            DMSG("Skip ar command with name %s\n", *arg);
            skip = true;
            ar = true;
        }

        if(endswith(*arg, "modpost")) {
            DMSG("Skip modpost command with name %s\n", *arg);
            skip = true;
            modpost = true;
        }

        arg++;
    }

    // process arguments
    for (; arg && *arg; arg++) {
        if(strstr(*arg, "empty.o")) {
            skip = false;
            DMSG("Keep scripts command with arg %s\n", *arg);
            break;
        }

        if(ar) {
            if(endswith(*arg, ".a")) {
                DMSG("Output library name %s\n", *arg);
                store_data("EMPTY LIB STUB", *arg);
            }
        }
        if(compile) {
            //mystub("option detected");
            if(strstr(*arg, "/dev/null")) {
                DMSG("Keep option-detection command with arg %s\n", *arg);
                skip = false;
                break;
            }

            if(strstr(*arg, "--version")) {
                DMSG("Keep version command with arg %s\n", *arg);
                skip = false;
                break;
            }

            if(!strcmp(*arg, "-o")) {
                if ((arg + 1) && *(arg + 1)) {
                    output = *(arg + 1);
                    //if(endswith(output, "mk_elfconfig")) {
                    //    DMSG("Keep scripts command with arg %s\n", output);
                    //    skip = false;
                    if(endswith(output, "bounds.s")) {
                        DMSG("Keep bounds.s command with arg %s\n", output);
                        skip = false;
                    } else {
                        skip = true;
                    }
                }
            }

            if(!strcmp(*arg, "-dumpdir")) {
                if ((arg + 1) && *(arg + 1)) {
                    dumpdir = *(arg + 1);
                }
            }

            if(!strcmp(*arg, "-dumpbase")) {
                if ((arg + 1) && *(arg + 1)) {
                    dumpbase = *(arg + 1);
                }
            }

            char *f = strstr(*arg, "-MMD,");
            if(f) {
                deps = f + 5;
            }
        }
        if(modpost) {
            if(!strcmp(*arg, "-o")) {
                if ((arg + 1) && *(arg + 1)) {
                    output = *(arg + 1);
                    if (endswith(output, "vmlinux.symvers")) {
                        DMSG("Need to generate vmlinux for arg %s\n", output);
                        export = ".vmlinux.export.c";
                        skip = true;
                    }
                }
            }
        }
    }

    if(skip) {
        if(compile) {
            if(output) {
                DMSG("Output %s\n", output);
                store_data("EMPTY OBJ STUB", output);
            }
            if(dumpbase) {
                if(endswith(dumpbase, "vmlinux.export.c")) {
                    DMSG("Dumpbase %s\n", dumpbase);
                    if(dumpdir) {
                        DMSG("Dumpdir %s\n", dumpdir);
                        size_t len = strlen(dumpdir) + strlen(dumpbase) + 2;
                        char file[len];
                        strcpy(file, dumpdir);
                        strcat(file, "/");
                        strcat(file, dumpbase);
                        store_data("//EMPTY C DUMP STUB", file);
                    } else {
                        store_data("//EMPTY C DUMP STUB", dumpbase);
                    }
                }
            }
            if(deps) {
                DMSG("Dep file %s\n", deps);
                store_data("EMPTY DEP STUB", deps);
            }
        }
        if(export) {
            DMSG("Export %s\n", export);
            store_data("EMPTY EXPORT STUB", export);
        }
    }

    return skip;
}
