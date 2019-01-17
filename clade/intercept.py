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

import argparse
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

from clade.cmds import get_last_id
from clade.extensions.utils import load_conf_file

LIB = os.path.join(os.path.dirname(__file__), "libinterceptor", "lib")
LIB64 = os.path.join(os.path.dirname(__file__), "libinterceptor", "lib64")

class Interceptor():
    """Object for intercepting and parsing build commands.

    Attributes:
        command: A list of strings representing build command to run and intercept
        output: A path to the file where intercepted commands will be saved
        debug: A boolean enabling debug logging messages
        fallback: A boolean enabling fallback intercepting mode
        append: A boolean allowing to append intercepted commands to already existing file with commands

    Raises:
        NotImplementedError: Clade is launched on Windows
        RuntimeError: Clade installation is corrupted, or intercepting process failed
    """

    def __init__(self, command=[], cwd=os.getcwd(), output="cmds.txt", debug=False, fallback=False, append=False, conf=None):
        self.command = command
        self.cwd = cwd
        self.output = os.path.abspath(output)
        self.fallback = fallback
        self.append = append
        self.conf = conf if conf else dict()
        self.logger = self.__setup_logger(debug)

        if sys.platform == "win32":
            self.debugger = self.__find_debugger()
        elif self.fallback:
            self.wrapper = self.__find_wrapper()
            self.wrappers_dir = tempfile.mkdtemp()
            self.wrapper_postfix = ".clade"
        else:
            self.libinterceptor = self.__find_libinterceptor()

        if not self.append and os.path.exists(self.output):
            os.remove(self.output)

        self.env = self.__setup_env()

    def __setup_logger(self, debug):
        logger = logging.getLogger("Clade-intercept")

        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s clade Intercept: %(message)s", "%H:%M:%S"))

        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if debug else logging.INFO)

        return logger

    def __find_debugger(self):
        debugger = os.path.join(os.path.dirname(__file__), "libinterceptor", "debugger.exe")

        if not os.path.exists(debugger):
            raise RuntimeError("debugger is not found in {!r}".format(debugger))

        self.logger.debug("Path to the debugger: {!r}".format(debugger))

        return debugger

    def __find_libinterceptor(self):
        if sys.platform == "linux":
            libinterceptor = self.__find_libinterceptor_linux()
        elif sys.platform == "darwin":
            libinterceptor = self.__find_libinterceptor_darwin()
        else:
            raise NotImplementedError("To use Clade on {!r} please run it with fallback mode enabled".format(sys.platform))

        return libinterceptor

    def __find_libinterceptor_linux(self):
        libinterceptor_name = "libinterceptor.so"
        libinterceptor = os.path.join(os.path.dirname(__file__), "libinterceptor", libinterceptor_name)

        if not os.path.exists(libinterceptor):
            raise RuntimeError("libinterceptor is not found in {!r}".format(libinterceptor))

        # Multilib support
        path = os.path.join(LIB, libinterceptor_name)
        path64 = os.path.join(LIB64, libinterceptor_name)

        if os.path.exists(path) and os.path.exists(path64):
            libinterceptor = libinterceptor_name
            self.logger.debug("Path to libinterceptor library locations: {!r}, {!r}".format(path, path64))
        else:
            self.logger.debug("Path to libinterceptor library location: {!r}".format(libinterceptor))

        return libinterceptor

    def __find_libinterceptor_darwin(self):
        libinterceptor = os.path.join(os.path.dirname(__file__), "libinterceptor", "libinterceptor.dylib")

        if not os.path.exists(libinterceptor):
            raise RuntimeError("libinterceptor is not found in {!r}".format(libinterceptor))

        self.logger.debug("Path to libinterceptor library location: {!r}".format(libinterceptor))

        return libinterceptor

    def __find_wrapper(self):
        wrapper = os.path.join(os.path.dirname(__file__), "libinterceptor", "wrapper")

        if not os.path.exists(wrapper):
            raise RuntimeError("wrapper is not found in {!r}".format(wrapper))

        self.logger.debug("Path to the wrapper: {!r}".format(wrapper))

        return wrapper

    def __create_wrappers(self):
        if not self.fallback or not sys.platform == "win32":
            return

        self.__create_path_wrappers()
        self.__create_exe_wrappers()

    def __create_path_wrappers(self):
        self.logger.debug("Create temporary directory for wrappers: {!r}".format(self.wrappers_dir))

        if os.path.exists(self.wrappers_dir):
            shutil.rmtree(self.wrappers_dir)

        os.makedirs(self.wrappers_dir)

        paths = os.environ.get("PATH", "").split(os.pathsep)

        counter = 0
        self.logger.debug("Walk through every directory in PATH to create wrappers: {!r}".format(paths))
        for path in paths:
            try:
                for file in os.listdir(path):
                    if os.access(os.path.join(path, file), os.X_OK):
                        try:
                            os.symlink(self.wrapper, os.path.join(self.wrappers_dir, file))
                            counter += 1
                        except FileExistsError:
                            continue
            except FileNotFoundError:
                continue

        self.logger.debug("{} path wrappers were created".format(counter))

    def __create_exe_wrappers(self):
        wrap_list = self.conf.get("Interceptor.wrap_list", [])
        self.logger.debug("Wrap list: {!r}".format(wrap_list))

        for path in wrap_list:
            if os.path.isfile(path):
                self.__create_exe_wrapper(path)
            elif os.path.isdir(path):
                if self.conf.get("Interceptor.recursive_wrap"):
                    for root, _, filenames in os.walk(path):
                        for filename in filenames:
                            self.__create_exe_wrapper(os.path.join(root, filename))
                else:
                    for file in os.listdir(path):
                        self.__create_exe_wrapper(os.path.join(path, file))
            else:
                self.logger.error("{!r} file or directory from 'Interceptor.wrap_list' option does not exist".format(path))
                sys.exit(-1)

    def __create_exe_wrapper(self, path):
        if not(os.path.isfile(path) and os.access(path, os.X_OK) and not os.path.basename(path) == "wrapper"):
            return

        self.logger.debug("Create exe wrapper: {!r}".format(path))

        try:
            os.rename(path, path + self.wrapper_postfix)
            os.symlink(self.wrapper, path)
        except PermissionError:
            self.logger.warning("You do not have permissions to modify {!r}".format(path))
        except Exception as e:
            self.logger.warning(e)

    def __delete_wrappers(self):
        if not self.fallback:
            return

        self.logger.debug("Delete temporary directory with wrappers: {!r}".format(self.wrappers_dir))
        if os.path.exists(self.wrappers_dir):
            shutil.rmtree(self.wrappers_dir)

        self.logger.debug("Delete all other wrapper files")
        wrap_list = self.conf.get("Interceptor.wrap_list", [])

        for path in wrap_list:
            if os.path.isfile(path):
                self.__delete_exe_wrapper(path)
            elif os.path.isdir(path):
                if self.conf.get("Interceptor.recursive_wrap"):
                    for root, _, filenames in os.walk(path):
                        for filename in filenames:
                            self.__delete_exe_wrapper(os.path.join(root, filename))
                else:
                    for file in os.listdir(path):
                        self.__delete_exe_wrapper(os.path.join(path, file))

    def __delete_exe_wrapper(self, path):
        if not(os.path.isfile(path) and os.access(path, os.X_OK) and not path.endswith(self.wrapper_postfix)):
            return

        try:
            if os.path.isfile(path + self.wrapper_postfix):
                self.logger.debug("Delete exe wrapper: {!r}".format(path))
                os.remove(path)
                os.rename(path + self.wrapper_postfix, path)
        except PermissionError:
            return
        except Exception as e:
            self.logger.warning(e)

    def __setup_env(self):
        env = dict(os.environ)

        if sys.platform == "win32":
            pass
        elif self.fallback:
            env["PATH"] = self.wrappers_dir + os.pathsep + os.environ.get("PATH", "")
            self.logger.debug("Add directory with wrappers to PATH: {!r}".format(env["PATH"]))
        else:
            if sys.platform == "darwin":
                self.logger.debug("Set 'DYLD_INSERT_LIBRARIES' environment variable value")
                env["DYLD_INSERT_LIBRARIES"] = self.libinterceptor
                env["DYLD_FORCE_FLAT_NAMESPACE"] = "1"
            elif sys.platform == "linux":
                self.logger.debug("Set 'LD_PRELOAD' environment variable value")
                env["LD_PRELOAD"] = self.libinterceptor

                env["LD_LIBRARY_PATH"] = env.get("LD_LIBRARY_PATH", "") + ":" + LIB64 + ":" + LIB
                self.logger.debug("Set LD_LIBRARY_PATH environment variable value as {!r}".format(env["LD_LIBRARY_PATH"]))

        self.logger.debug("Set 'CLADE_INTERCEPT' environment variable value")
        env["CLADE_INTERCEPT"] = self.output

        # Prepare environment variables for PID graph
        last_used_id = get_last_id(self.output)
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(last_used_id.encode())
        env["CLADE_ID_FILE"] = f.name
        env["CLADE_PARENT_ID"] = "0"

        return env

    def execute(self):
        """Execute intercepting of build commands.

        Returns:
            0 if everything went successful and error code otherwise
        """

        try:
            self.__create_wrappers()

            if sys.platform == "win32":
                self.command.insert(0, self.debugger)
                self.logger.debug("Execute {!r} command with the following environment: {!r}".format(self.command, self.env))
                return subprocess.call(self.command, env=self.env, shell=False, cwd=self.cwd)
            else:
                shell_command = " ".join([shlex.quote(x) for x in self.command])
                self.logger.debug("Execute {!r} command with the following environment: {!r}".format(shell_command, self.env))
                return subprocess.call(shell_command, env=self.env, shell=True, cwd=self.cwd)
        finally:
            self.__delete_wrappers()


def parse_args(args):
    parser = argparse.ArgumentParser()

    parser.add_argument("-o", "--output", help="a path to the FILE where intercepted commands will be saved", metavar='FILE', default="cmds.txt")
    parser.add_argument("-d", "--debug", help="enable debug logging messages", action="store_true")
    parser.add_argument("-f", "--fallback", help="enable fallback intercepting mode (not supported on Windows)", action="store_true")
    parser.add_argument("-a", "--append", help="append intercepted commands to existing cmds.txt file", action="store_true")
    parser.add_argument("-c", "--config", help="a path to the JSON file with configuration", metavar='JSON', default=None)
    parser.add_argument(dest="command", nargs=argparse.REMAINDER, help="build command to run and intercept")

    args = parser.parse_args(args)

    if not args.command:
        sys.exit("Build command is missing")

    return args


def main(args=sys.argv[1:]):
    args = parse_args(args)

    i = Interceptor(command=args.command, output=args.output, debug=args.debug,
                    fallback=args.fallback, append=args.append, conf=load_conf_file(args.config))
    sys.exit(i.execute())


if __name__ == "__main__":
    main(sys.argv[1:])
