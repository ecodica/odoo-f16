# -*- coding: utf-8 -*-
# backported by Goran Kliska from V17 originally to sql.py but now it is moved to separate file
# so that there is no ambiguity between this class and psycopg2.sql.SQL in places
# where latter is expected

from psycopg2.sql import SQL
from typing import Iterable
from .misc import named_to_positional_printf

from odoo.tools.query import IDENT_RE

class SQL:
    """ An object that wraps SQL code with its parameters, like::

        sql = SQL("UPDATE TABLE foo SET a = %s, b = %s", 'hello', 42)
        cr.execute(sql)

    The code is given as a ``%``-format string, and supports either positional
    arguments (with `%s`) or named arguments (with `%(name)s`). Escaped
    characters (like ``"%%"``) are not supported, though. The arguments are
    meant to be merged into the code using the `%` formatting operator.

    The SQL wrapper is designed to be composable: the arguments can be either
    actual parameters, or SQL objects themselves::

        sql = SQL(
            "UPDATE TABLE %s SET %s",
            SQL.identifier(tablename),
            SQL("%s = %s", SQL.identifier(columnname), value),
        )

    The combined SQL code is given by ``sql.code``, while the corresponding
    combined parameters are given by the list ``sql.params``. This allows to
    combine any number of SQL terms without having to separately combine their
    parameters, which can be tedious, bug-prone, and is the main downside of
    `psycopg2.sql <https://www.psycopg.org/docs/sql.html>`.

    The second purpose of the wrapper is to discourage SQL injections. Indeed,
    if ``code`` is a string literal (not a dynamic string), then the SQL object
    made with ``code`` is guaranteed to be safe, provided the SQL objects
    within its parameters are themselves safe.
    """
    __slots__ = ('__code', '__args')

    # pylint: disable=keyword-arg-before-vararg
    def __new__(cls, code: (str | SQL) = "", /, *args, **kwargs):
        if isinstance(code, SQL):
            return code

        # validate the format of code and parameters
        if args and kwargs:
            raise TypeError("SQL() takes either positional arguments, or named arguments")
        if args:
            code % tuple("" for arg in args)
        elif kwargs:
            code, args = named_to_positional_printf(code, kwargs)

        self = object.__new__(cls)
        self.__code = code
        self.__args = args
        return self

    @property
    def code(self) -> str:
        """ Return the combined SQL code string. """
        stack = []  # stack of intermediate results
        for node in self.__postfix():
            if not isinstance(node, SQL):
                stack.append("%s")
            elif arity := len(node.__args):
                stack[-arity:] = [node.__code % tuple(stack[-arity:])]
            else:
                stack.append(node.__code)
        return stack[0]

    @property
    def params(self) -> list:
        """ Return the combined SQL code params as a list of values. """
        return [node for node in self.__postfix() if not isinstance(node, SQL)]

    def __postfix(self):
        """ Return a postfix iterator for the SQL tree ``self``. """
        stack = [(self, False)]
        while stack:
            node, ispostfix = stack.pop()
            if ispostfix or not isinstance(node, SQL):
                yield node
            else:
                stack.append((node, True))
                stack.extend((arg, False) for arg in reversed(node.__args))

    def __repr__(self):
        return f"SQL({', '.join(map(repr, [self.code, *self.params]))})"

    def __bool__(self):
        return bool(self.__code)

    def __eq__(self, other):
        return self.code == other.code and self.params == other.params

    def __iter__(self):
        """ Yields ``self.code`` and ``self.params``. This was introduced for
        backward compatibility, as it enables to access the SQL and parameters
        by deconstructing the object::

            sql = SQL(...)
            code, params = sql
        """
        yield self.code
        yield self.params

    def join(self, args: Iterable) -> SQL:
        """ Join SQL objects or parameters with ``self`` as a separator. """
        args = list(args)
        # optimizations for special cases
        if len(args) == 0:
            return SQL()
        if len(args) == 1:
            return args[0]
        if not self.__args:
            return SQL(self.__code.join("%s" for arg in args), *args)
        # general case: alternate args with self
        items = [self] * (len(args) * 2 - 1)
        for index, arg in enumerate(args):
            items[index * 2] = arg
        return SQL("%s" * len(items), *items)

    @classmethod
    def identifier(cls, name: str, subname: (str | None) = None) -> SQL:
        """ Return an SQL object that represents an identifier. """
        assert IDENT_RE.match(name), f"{name!r} invalid for SQL.identifier()"
        if subname is None:
            return cls(f'"{name}"')
        assert IDENT_RE.match(subname), f"{subname!r} invalid for SQL.identifier()"
        return cls(f'"{name}"."{subname}"')
