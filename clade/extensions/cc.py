# Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shlex
import subprocess

from clade.extensions.compiler import Compiler
from clade.extensions.opts import cc_preprocessor_opts


class CC(Compiler):
    """Class for parsing CC build commands."""

    __version__ = "1"

    def parse(self, cmds_file):
        super().parse(cmds_file, self.conf.get("CC.which_list", []))

    def parse_cmd(self, cmd):
        cmd_id = cmd["id"]

        parsed_cmd = super().parse_cmd(cmd, self.name)

        if not parsed_cmd["out"] and "-c" in parsed_cmd["opts"]:
            for cmd_in in parsed_cmd["in"]:
                # Output file is located inside "cwd" directory,
                # not near cmd_in
                # For example, gcc -c work/1.c will produce 1.o file,
                # not work/1.o
                cmd_out = os.path.join(
                    parsed_cmd["cwd"],
                    os.path.basename(os.path.splitext(cmd_in)[0] + ".o"),
                )
                parsed_cmd["out"].append(cmd_out)

        if self.is_bad(parsed_cmd):
            self.dump_bad_cmd_by_id(cmd_id, parsed_cmd)
            return

        self.debug("Parsed command: {}".format(parsed_cmd))

        if self.conf.get(
            "Compiler.preprocess_cmds"
        ) and self.is_a_compilation_command(parsed_cmd):
            pre = self.__preprocess_cmd(parsed_cmd)
            self.debug("Preprocessed files: {}".format(pre))
            self.store_pre_files(pre, parsed_cmd["cwd"])

            for file in pre:
                if os.path.exists(file):
                    os.remove(file)

        deps = self.__get_deps(cmd_id, parsed_cmd)
        self.debug("Dependencies: {}".format(deps))
        self.dump_deps_by_id(cmd_id, deps)
        self.dump_cmd_by_id(cmd_id, parsed_cmd)

        if self.conf.get(
            "Compiler.store_deps"
        ) and self.is_a_compilation_command(parsed_cmd):
            self.store_deps_files(deps, parsed_cmd["cwd"])

    def __get_deps(self, cmd_id, cmd):
        """Get a list of CC command dependencies."""
        deps = []

        for cmd_in in cmd["in"]:
            self.debug("Collecting dependencies for {!r} file".format(cmd_in))
            deps_file = self.__collect_deps(cmd_id, cmd, cmd_in)

            # Remove duplicates
            for dep in [d for d in self.__parse_deps(deps_file) if d not in deps]:
                deps.append(dep)

        return deps

    def __collect_deps(self, cmd_id, cmd, cmd_in):
        deps_file = os.path.join(self.temp_dir, "{}-deps.txt".format(cmd_id))

        if self.conf.get("CC.with_system_header_files"):
            additional_opts = ["-Wp,-MD,{}".format(deps_file), "-M"]
        else:
            additional_opts = ["-Wp,-MMD,{}".format(deps_file), "-MM"]

        opts = cmd["opts"] + additional_opts
        command = [cmd["command"][0]] + opts + [cmd_in]

        # Do not execute a command that does not contain any input files
        if cmd["in"] and "-" not in cmd["in"]:
            self.debug("CWD: {!r}".format(cmd["cwd"]))
            self.debug("Executing command: {!r}".format(
                " ".join([shlex.quote(x) for x in command]))
            )
            subprocess.call(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=cmd["cwd"],
            )
        else:
            self.debug("Command does not contain any input files, skipping")

        return deps_file

    def __parse_deps(self, deps_file):
        deps = []

        if os.path.isfile(deps_file):
            self.debug("Parsing dependencies file {!r}".format(deps_file))
            with open(deps_file, encoding="utf8") as fp:
                for line in fp.readlines():
                    self.debug("Line: {!r}".format(line))
                    line = line.lstrip(" ")
                    line = line.rstrip(" \\\n")
                    line = line.rstrip(":")

                    if not line:
                        continue

                    # Split with non-escaped space
                    deps.extend(shlex.split(line))

            os.remove(deps_file)
        else:
            self.debug("File with dependencies does not exist")

        # Ignore first element (output file, .o)
        return deps[1:]

    def is_bad(self, cmd):
        if super().is_bad(cmd):
            return True

        if self.conf.get("CC.ignore_cc1", True) and (
            "-cc1" in cmd["opts"] or cmd["command"][0].endswith("cc1")
        ):
            return True

        return False

    def is_a_compilation_command(self, cmd):
        if not super().is_a_compilation_command(cmd):
            return False

        if "opts" not in cmd:
            opts = self.load_opts_by_id(cmd["id"])
        else:
            opts = cmd["opts"]

        if set(opts).intersection(cc_preprocessor_opts):
            return False

        return True

    def __preprocess_cmd(self, cmd):
        pre = []

        for cmd_in in cmd["in"]:
            if not os.path.isabs(cmd_in):
                cmd_in = os.path.join(cmd["cwd"], cmd_in)

            pre_file = os.path.splitext(cmd_in)[0] + ".i"
            command = (
                [cmd["command"][0]]
                + cmd["opts"]
                + ["-E"]
                + [cmd_in]
                + ["-o", pre_file]
                + self.conf.get("Compiler.extra_preprocessor_opts", [])
            )

            r = subprocess.check_call(
                command, cwd=cmd["cwd"], stderr=subprocess.DEVNULL
            )

            if not r:
                pre.append(pre_file)
            else:
                self.warning(
                    "Can't preprocess command with ID={!r} and input file {!r}".format(
                        cmd["id"], cmd_in
                    )
                )

        return pre
