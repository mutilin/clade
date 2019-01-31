# Copyright (c) 2019 ISP RAS (http://www.ispras.ru)
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
import sys
import re

from clade.extensions.common import Common
from clade.extensions.opts import requires_value
from clade.extensions.utils import common_main

# TODO: Suppport /E and /EP options (Preprocess to stdout)

# TODO: Suppport /FA and /Fa options (output assembler code, .cod or .asm)

# TODO: Support /Fe option (Name of the output EXE file)
# /Fe[pathname] /Fe: pathname

# TODO: Suppport /Fi option (Name of the output preprocessed code, .i)
# Option is used together with /P


class CL(Common):
    def __init__(self, work_dir, conf=None, preset="base"):
        super().__init__(work_dir, conf, preset)

    def parse(self, cmds_file):
        super().parse(cmds_file, self.conf.get("CL.which_list", []))

    def parse_cmd(self, cmd):
        self.debug("Parse: {}".format(cmd))
        parsed_cmd = self._get_cmd_dict(cmd)

        if self.name not in requires_value:
            raise RuntimeError(
                "Command type '{}' is not supported".format(self.name)
            )

        opts = iter(cmd["command"][1:])

        for opt in opts:
            if opt in requires_value[self.name]:
                val = next(opts)
                parsed_cmd["opts"].extend([opt, val])

                if opt == "/link":
                    while True:
                        val = next(opts)
                        if not val:
                            break
                        parsed_cmd["opts"].append(val)
            elif re.search(r"^/", opt):
                parsed_cmd["opts"].append(opt)
            else:
                parsed_cmd["in"].append(opt)

        if not parsed_cmd["out"] and "/c" in parsed_cmd["opts"]:
            for cmd_in in parsed_cmd["in"]:
                for opt in parsed_cmd["opts"]:
                    if re.search(r"/Fo", opt):
                        obj_path = re.sub(r"/Fo", "", opt)

                        if not os.path.isabs(obj_path):
                            obj_path = os.path.join(
                                parsed_cmd["cwd"], obj_path
                            )

                        if os.path.isfile(obj_path):
                            parsed_cmd["out"].append(obj_path)
                        elif os.path.exists(obj_path):
                            obj_name = os.path.basename(
                                os.path.splitext(cmd_in)[0] + ".obj"
                            )
                            parsed_cmd["out"].append(
                                os.path.join(obj_path, obj_name)
                            )
                        else:
                            raise RuntimeError(
                                "Can't determine output file of CL command"
                            )

                        break
                else:
                    obj_name = os.path.basename(
                        os.path.splitext(cmd_in)[0] + ".obj"
                    )
                    cmd_out = os.path.join(parsed_cmd["cwd"], obj_name)
                    parsed_cmd["out"].append(cmd_out)

        if self.is_bad(parsed_cmd):
            return

        self.debug("Parsed command: {}".format(parsed_cmd))
        self.dump_cmd_by_id(cmd["id"], parsed_cmd)


def main(args=sys.argv[1:]):
    common_main(CL, args)
