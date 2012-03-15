# -*- coding: utf-8 *-*

import re
import ast
import _ast

from ninja_ide.tools.completion import model


MODULES = {}


class Analyzer(object):

    __mapping = {
        _ast.Tuple: '__builtin__.tuple',
        _ast.List: '__builtin__.list',
        _ast.Str: '__builtin__.str',
        _ast.Dict: '__builtin__.dict',
        #Try to differenciate between int and float later
        _ast.Num: '__builtin__.int',
        _ast.Call: model.late_resolution,
        _ast.Name: model.late_resolution,
        _ast.Attribute: model.late_resolution,
    }

    def __init__(self):
        self._fixed_line = -1

    def collect_metadata(self, project_path):
        """Collect metadata from a project."""
        #TODO

    def _get_valid_module(self, source):
        """Try to parse the module and fix some errors if it has some."""
        astModule = None
        try:
            astModule = ast.parse(source)
        except SyntaxError, reason:
            line = reason.lineno - 1
            if line != self._fixed_line:
                self._fixed_line = line
                new_line = ''
                indent = re.match('^\s+', reason.text)
                if indent is not None:
                    new_line = indent.group() + 'pass'
                split_source = source.splitlines()
                split_source[line] = new_line
                source = '\n'.join(split_source)
                astModule = self._get_valid_module(source)
        return astModule

    def _resolve_late(self, module):
        """Resolve the late_resolution objects inside the module."""

    def analyze(self, source):
        """Analyze the source provided and create the proper structure."""
        astModule = self._get_valid_module(source)
        if astModule is None:
            return model.Module()
        self.content = source.split('\n')

        module = model.Module()
        for symbol in astModule.body:
            symbol_type = type(symbol)
            if symbol_type is ast.Assign:
                assigns = self._process_assign(symbol)[0]
                module.add_attributes(assigns)
            elif symbol_type in (ast.Import, ast.ImportFrom):
                module.add_imports(self._process_import(symbol))
            elif symbol_type is ast.ClassDef:
                module.add_class(self._process_class(symbol))
            elif symbol_type is ast.FunctionDef:
                module.add_function(self._process_function(symbol))
#        self.resolve_late(module)

        self.content = None
        return module

    def _process_assign(self, symbol):
        """Process an ast.Assign object to extract the proper info."""
        assigns = []
        attributes = []
        for var in symbol.targets:
            type_value = type(symbol.value)
            data_type = self.__mapping.get(type_value, None)
            line_content = self.content[symbol.lineno - 1]
            if data_type != model.late_resolution:
                type_value = None
            type_var = type(var)
            if type_var == ast.Attribute:
                data = (var.attr, symbol.lineno, data_type, line_content,
                    type_value)
                attributes.append(data)
            elif type_var == ast.Name:
                data = (var.id, symbol.lineno, data_type, line_content,
                    type_value)
                assigns.append(data)
        return (assigns, attributes)

    def _process_import(self, symbol):
        """Process an ast.Import and ast.ImportFrom object to extract data."""
        imports = []
        for imp in symbol.names:
            if type(symbol) is ast.ImportFrom:
                module_name = "%s.%s" % (symbol.module, imp.name)
            else:
                module_name = imp.name
            name = imp.asname
            if name is None:
                name = imp.name
            imports.append((name, module_name))
        return imports

    def _process_class(self, symbol):
        """Process an ast.ClassDef object to extract data."""
        clazz = model.Clazz(symbol.name)
        for base in symbol.bases:
            parent_name = []
            while type(base) is ast.Attribute:
                parent_name.append(base.attr)
                base = base.value
            name = '.'.join(reversed(parent_name))
            name = base.id if name == '' else ("%s.%s" % (base.id, name))
            clazz.bases.append(name)
        for decorator in symbol.decorator_list:
            clazz.decorators.append(decorator.id)
        # PARSE FUNCTIONS AND ATTRIBUTES
        for sym in symbol.body:
            type_sym = type(sym)
            if type_sym is ast.Assign:
                assigns = self._process_assign(sym)[0]
                clazz.add_attributes(assigns)
            elif type_sym is ast.FunctionDef:
                clazz.add_function(self._process_function(sym, clazz))
        return clazz

    def _process_function(self, symbol, parent=None):
        """Process an ast.FunctionDef object to extract data."""
        function = model.Function(symbol.name)
        #We are not going to collect data from decorators yet.
#        for decorator in symbol.decorator_list:
            #Decorators can be: Name, Call, Attributes
#            function.decorators.append(decorator.id)
        if symbol.args.vararg is not None:
            assign = model.Assign(symbol.args.vararg)
            assign.add_data(symbol.lineno, '__builtin__.list', None, None)
            function.args[assign.name] = assign
        if symbol.args.kwarg is not None:
            assign = model.Assign(symbol.args.kwarg)
            assign.add_data(symbol.lineno, '__builtin__.dict', None, None)
            function.args[assign.name] = assign
        #We store the arguments to compare with default backwards
        defaults = []
        for value in reversed(symbol.args.defaults):
            type_value = type(value)
            data_type = self.__mapping.get(type_value, None)
            if data_type != model.late_resolution:
                type_value = None
            defaults.append((data_type, type_value))
        for arg in reversed(symbol.args.args):
            if arg.id == 'self':
                continue
            assign = model.Assign(arg.id)
            data_type = (model.late_resolution, None)
            if defaults:
                data_type = defaults.pop()
            assign.add_data(symbol.lineno, data_type[0], None, data_type[1])
            function.args[assign.name] = assign
        for sym in symbol.body:
            type_sym = type(sym)
            if type_sym is ast.Assign:
                result = self._process_assign(sym)
                function.add_attributes(result[0])
                if parent is not None:
                    parent.add_attributes(result[1])
            elif type_sym is ast.FunctionDef:
                function.add_function(self._process_function(sym))
            else:
                #TODO: cover generators
                self._search_for_returns(function, sym)

        return function

    def _search_for_returns(self, function, symbol):
        """Search for return recursively inside the function."""
        type_symbol = type(symbol)
        if type_symbol is ast.Return:
            type_value = type(symbol.value)
            lineno = symbol.lineno
            data_type = self.__mapping.get(type_value, None)
            line_content = self.content[lineno - 1]
            if data_type != model.late_resolution:
                type_value = None
            function.add_return(lineno, data_type, line_content, type_value)
        elif type_symbol in (ast.If, ast.For, ast.TryExcept):
            for sym in symbol.body:
                self._search_for_returns(function, sym)
            for else_item in symbol.orelse:
                self._search_for_returns(function, else_item)
        elif type_symbol is ast.TryFinally:
            for sym in symbol.body:
                self._search_for_returns(function, sym)
            for else_item in symbol.finalbody:
                self._search_for_returns(function, else_item)
