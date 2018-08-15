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
from clade.extensions.info import Info
from clade.extensions.cc import CC
from clade.extensions.ld import LD
from clade.extensions.cmd_graph import CmdGraph
from clade.extensions.src_graph import SrcGraph
from clade.extensions.callgraph import Callgraph
from clade.extensions.macros import Macros
from clade.extensions.variables import Variables
from clade.extensions.typedefs import Typedefs
from clade.extensions.functions import Functions
from clade.extensions.storage import Storage


workdir = None
configuration = None


def setup(work_dir, conf=None):
    global workdir
    global configuration
    workdir = work_dir
    configuration = conf


def initialize_extensions(work_dir, cmd_file, conf=None):
    setup(work_dir, conf)
    for cls in (CmdGraph, SrcGraph, Info, Callgraph, Variables, Macros, Typedefs):
        inst = cls(workdir, configuration)
        inst.parse(cmd_file)


def get_cc(identifier):
    return CC(workdir).load_cmd_by_id(identifier)


def get_cc_opts(identifier):
    return CC(workdir).load_opts_by_id(identifier)


def get_cc_deps(identifier):
    return CC(workdir).load_deps_by_id(identifier)


def get_ld(identifier):
    return LD(workdir).load_cmd_by_id(identifier)


class CommandGraph:

    def __init__(self):
        self.graph = CmdGraph(workdir, configuration).load_cmd_graph()

    @property
    def LDs(self):
        return ((desc['id'], desc) for desc in LD(workdir).load_all_cmds())

    def get_ccs_for_ld(self, identifier):
        ccs = dict()
        identifier = str(identifier)
        todo_commands = list(self.graph[identifier]['using'])
        while todo_commands:
            current = todo_commands.pop(0)
            current_type = self.graph[current]['type']

            if current_type == 'CC':
                desc = get_cc(current)
                if not any(f.endswith('.S') for f in desc['in']):
                    ccs[current] = desc
            todo_commands.extend(self.graph[current]['using'])
        return list(ccs.items())


class SourceGraph:

    def __init__(self):
        self.graph = SrcGraph(workdir, configuration).load_src_graph()

    def get_sizes(self, files):
        return {f: self.graph[f]['loc'] for f in files}

    def get_ccs_by_file(self, file):
        ccs = (get_cc(identifier) for identifier in self.graph[file]['compiled_in'])
        return [cc for cc in ccs if cc['in'][0] == file]


class FileStorage:

    def __init__(self):
        self._storage = Storage(workdir, configuration)

    @property
    def storage_dir(self):
        return self._storage.get_storage_dir()

    def convert_path(self, clade_path):
        return os.path.join(self.storage_dir, clade_path)

    def normal_path(self, clade_path):
        if os.path.isabs(clade_path):
            return self.convert_path(clade_path)
        else:
            return clade_path


class CallGraph:

    def __init__(self):
        self._graph = Callgraph(workdir, configuration)

    @property
    def graph(self):
        return self._graph.load_callgraph()

    def partial_graph(self, files=None):
        graph = self.graph
        if files is None:
            return graph
        elif isinstance(files, list) or isinstance(files, set):
            afiles = set(files)
            return {f: data for f, data in graph.items() for p, desc in data.items()
                    if p in files or set(desc.get('called_in', {})).intersection(afiles)}
        else:
            raise TypeError("Provide None, list or set but not {!r} to filter files".format(type(files).__name__))


class TypeDefinitions:

    def __init__(self, files):
        self._graph = Typedefs(workdir, configuration)
        self._files = files

    @property
    def graph(self):
        return self._graph.load_typedefs(self._files)


class VariableInitializations:

    def __init__(self, files):
        self._obj = Variables(workdir, configuration)
        self._files = files

    @property
    def vars(self):
        return self._obj.load_variables(self._files)

    @property
    def used_vars_functions(self):
        return self._used_vars_functions(self._files)

    @staticmethod
    def _used_vars_functions(files=None):
        data = Variables(workdir, configuration).load_used_in_vars()
        if files is None:
            return data
        elif isinstance(files, list) or isinstance(files, set):
            afiles = set(files)
            return {f: {k: set(used_in).intersection(afiles) for k, used_in in fs.items()
                        if f in afiles or set(used_in).intersection(afiles)} for f, fs in data.items()}
        else:
            raise TypeError("Provide None, list or set but not {!r} to filter files".format(type(files).__name__))


class FunctionsScopes:

    def __init__(self, files=None):
        self.fs = Functions(workdir, configuration)
        self._files = files

    @property
    def funcs_to_scope(self):
        return self._funcs_to_scope(self._files)

    @property
    def scope_to_funcs(self):
        return self._scope_to_funcs(self._files)

    def _funcs_to_scope(self, files=None):
        data = self.fs.load_functions()
        if files is None:
            return data
        elif isinstance(files, list) or isinstance(files, set):
            files = set(files)
            return {func: {scope: scopes[scope] for scope in scopes
                           if scope in files or set(scopes[scope].get('declared_in', set())).intersection(files)}
                    for func, scopes in data.items()}
        else:
            raise TypeError("Provide None, list or set but not {!r} to filter files".format(type(files).__name__))

    def _scope_to_funcs(self, files=None):
        data = self.fs.load_functions()
        if files is None:
            return data
        elif isinstance(files, list) or isinstance(files, set):
            return {scope: {func: funcs[func] for func in funcs
                            if scope in files or set(funcs[func].get('declared_in', set())).intersection(files)}
                    for scope, funcs in data.items()}
        else:
            raise TypeError("Provide None, list or set but not {!r} to filter files".format(type(files).__name__))


class MacroExpansions:

    def __init__(self, white_list=None, files=None):
        self.data = Macros(workdir, configuration)
        self._white_list = white_list
        self._files = files

    @property
    def macros(self):
        data = self.data.load_macros_expansions(self._files)
        if self._white_list:
            return {f: {m: desc for m, desc in macros.items() if m in self._white_list} for f, macros in data.items()}
        else:
            return data