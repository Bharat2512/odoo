# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2013 OpenERP (<http://www.openerp.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

""" This module provides the elements for managing two different API styles,
    namely the "traditional" and "record" styles.

    In the "traditional" style, parameters like the database cursor, user id,
    context dictionary and record ids (usually denoted as ``cr``, ``uid``,
    ``context``, ``ids``) are passed explicitly to all methods. In the "record"
    style, those parameters are hidden in an execution environment (a "scope")
    and the methods only refer to model instances, which gives it a more object-
    oriented feel.

    For instance, the statements::

        model = self.pool.get(MODEL)
        ids = model.search(cr, uid, DOMAIN, context=context)
        for rec in model.browse(cr, uid, ids, context=context):
            print rec.name
        model.write(cr, uid, ids, VALUES, context=context)

    may also be written as::

        with Scope(cr, uid, context):       # cr, uid, context introduced once
            model = scope.model(MODEL)      # scope proxies the current scope
            recs = model.search(DOMAIN)     # search returns a recordset
            for rec in recs:                # iterate over the records
                print rec.name
            recs.write(VALUES)              # update all records in recs

    Methods written in the "traditional" style are automatically decorated,
    following some heuristics based on parameter names.


    .. _record-map-convention:

    Record-map convention
    ---------------------

    The decorators also provides support for "record-map" methods, i.e., methods
    with a specific calling convention: when called on a recordset, they return
    a list of results, each result corresponding to a record in the recordset.

    The following example illustrates the convention::

        y = model.browse([42, 43])              # y is a recordset
        y.method(args)                          # => ['foo', 'bar']

        x = model.browse(42)                    # x is a single record
        x.method(args)                          # => 'foo'

"""

__all__ = [
    'Meta', 'guess', 'noguess',
    'model', 'multi', 'one',
    'cr', 'cr_context', 'cr_uid', 'cr_uid_context',
    'cr_uid_id', 'cr_uid_id_context', 'cr_uid_ids', 'cr_uid_ids_context',
    'depends', 'returns',
]

from functools import wraps
import logging

_logger = logging.getLogger(__name__)


#
# The following attributes are used on methods:
#    method._api: decorator function, both on original and wrapping method
#    method._returns: set by @returns, both on original and wrapping method
#    method._orig: original method, on wrapping method only
#

class Meta(type):
    """ Metaclass that automatically decorates traditional-style methods by
        guessing their API. It also implements the inheritance of the
        :func:`returns` decorators.
    """

    def __new__(meta, name, bases, attrs):
        # dummy parent class to catch overridden methods decorated with 'returns'
        parent = type.__new__(meta, name, bases, {})

        for key, value in attrs.items():
            if not key.startswith('__') and callable(value):
                # make the method inherit from @returns decorators
                if not _get_returns(value) and _get_returns(getattr(parent, key, None)):
                    value = returns(getattr(parent, key))(value)
                    _logger.debug("Method %s.%s inherited @returns(%r)",
                                  name, value.__name__, _get_returns(value))

                # guess calling convention if none is given
                if not hasattr(value, '_api'):
                    value = guess(value)

                attrs[key] = value

        return type.__new__(meta, name, bases, attrs)


def depends(*args):
    """ Return a decorator that specifies the field dependencies of a "compute"
        method (for new-style function fields). Each argument must be a string
        that consists in a dot-separated sequence of field names.
    """
    def decorate(method):
        method._depends = args
        return method

    return decorate


def _get_returns(method):
    return getattr(method, '_returns', None)


def returns(model):
    """ Return a decorator for methods that return instances of `model`.

        :param model: a model name, ``'self'`` for the current model, or a method
            (in which case the model is taken from that method's decorator)

        The decorator adapts the method output to the api style: `id`, `ids` or
        ``False`` for the traditional style, and record, recordset or null for
        the record style::

            @model
            @returns('res.partner')
            def find_partner(self, arg):
                ...     # return some record

            # output depends on call style: traditional vs record style
            partner_id = model.find_partner(cr, uid, arg, context=context)
            partner_record = model.find_partner(arg)

        Note that the decorated method must satisfy that convention.

        Those decorators are automatically *inherited*: a method that overrides
        a decorated existing method will be decorated with the same
        ``@returns(model)``.
    """
    if callable(model):
        # model is a method, check its own @returns decoration
        model = _get_returns(model)
        if not model:
            return lambda method: method

    def decorate(method):
        if hasattr(method, '_orig'):
            # decorate the original method, and re-apply the api decorator
            origin = method._orig
            origin._returns = model
            return origin._api(origin)
        else:
            method._returns = model
            return method

    return decorate


# constant converters
_CONVERT_ID = lambda self, value: value
_CONVERT_BROWSE = lambda self, value: self.browse(value)
_CONVERT_UNBROWSE = lambda self, value: value.unbrowse()


def _returns_new(method):
    """ Return a function `convert(self, value)` that adapts `value` from
        traditional-style to record-style returning convention of `method`.
    """
    model = _get_returns(method)
    if model:
        if model == 'self':
            return _CONVERT_BROWSE
        else:
            return lambda self, value: self.pool[model].browse(value)
    else:
        return _CONVERT_ID


def _returns_old(method):
    """ Return a function `convert(self, value)` that adapts `value` from
        traditional-style to record-style returning convention of `method`.
    """
    model = _get_returns(method)
    if model:
        return _CONVERT_UNBROWSE
    else:
        return _CONVERT_ID


def _make_wrapper(method, old_api, new_api):
    """ return a wrapper for a method that combines both api styles
        :param method: the original method
        :param old_api: the function that implements the traditional-style api
        :param new_api: the function that implements the record-style api
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        cr = kwargs.get('cr', args and args[0])
        if isinstance(cr, Cursor):
            return old_api(self, *args, **kwargs)
        else:
            return new_api(self, *args, **kwargs)

    # propagate some openerp attributes to the wrapper
    for attr in ('_api', '_depends', '_returns', 'clear_cache'):
        if hasattr(method, attr):
            setattr(wrapper, attr, getattr(method, attr))
    wrapper._orig = method
    return wrapper


def _context_args_kwargs(method, args, kwargs):
    """ extract the context argument out of `args` and `kwargs`
        :param method: the method to call
        :param args: positional arguments without `self` (tuple)
        :param kwargs: keyword arguments (dictionary)
        :return: tuple `(context, args, kwargs)`
            where both `args` and `kwargs` are free of context argument
    """
    if 'context' in kwargs:
        context = kwargs.pop('context')
        return context, args, kwargs
    elif len(args) + len(kwargs) > method.func_code.co_argcount - 1:
        # heuristics: context is given as an extra argument in args
        return args[-1], args[:-1], kwargs
    else:
        # context defaults to None
        return None, args, kwargs


def _get_one(value):
    """ if `value` is a list with one element, return that element; otherwise
        return `value`
    """
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def model(method):
    """ Decorate a record-style method where `self` is any instance with scope
        (model, record or recordset). Such a method::

            @api.model
            def method(self, args):
                ...

        may be called in both record and traditional styles, like::

            model.method(args)
            model.method(cr, uid, args, context=context)
    """
    method._api = model
    convert = _returns_old(method)

    def old_api(self, cr, uid, *args, **kwargs):
        context, args, kwargs = _context_args_kwargs(method, args, kwargs)
        with Scope(cr, uid, context):
            value = method(self, *args, **kwargs)
            return convert(self, value)

    return _make_wrapper(method, old_api, method)


def multi(method):
    """ Decorate a record-style method where `self` is a recordset. Such a
        method::

            @api.multi
            def method(self, args):
                ...

        may be called in both record and traditional styles, like::

            recs = model.recordset(ids)

            # the following calls are equivalent
            recs.method(args)
            model.method(cr, uid, ids, args, context=context)

        This decorator supports the :ref:`record-map-convention`.
    """
    method._api = multi
    convert = _returns_old(method)

    def old_api(self, cr, uid, ids, *args, **kwargs):
        context, args, kwargs = _context_args_kwargs(method, args, kwargs)
        with Scope(cr, uid, context):
            value = new_api(self.browse(ids), *args, **kwargs)
            return convert(self, value)

    def new_api(self, *args, **kwargs):
        if self.is_record():
            return _get_one(method(self.to_recordset(), *args, **kwargs))
        else:
            return method(self, *args, **kwargs)

    return _make_wrapper(method, old_api, new_api)


def one(method):
    """ Decorate a record-style method where `self` is a single record. The
        resulting method follows the :ref:`record-map-convention`.
        Such a method::

            @api.one
            def method(self, args):
                return self.name

        may be called in both record and traditional styles, like::

            rec = model.record(id)

            # the following calls are equivalent
            rec.method(args)
            model.method(cr, uid, rec.id, args, context=context)
    """
    method._api = one
    convert = _returns_old(method)

    def old_api(self, cr, uid, ids, *args, **kwargs):
        context, args, kwargs = _context_args_kwargs(method, args, kwargs)
        with Scope(cr, uid, context):
            value = new_api(self.browse(ids), *args, **kwargs)
            return convert(self, value)

    def new_api(self, *args, **kwargs):
        if self.is_record():
            return method(self, *args, **kwargs)
        else:
            return [method(rec, *args, **kwargs) for rec in self]

    return _make_wrapper(method, old_api, new_api)


def cr(method):
    """ Decorate a traditional-style method that takes `cr` as a parameter.
        Such a method may be called in both record and traditional styles, like::

            obj.method(args)            # record style
            obj.method(cr, args)        # traditional style
    """
    method._api = cr
    convert = _returns_new(method)

    def old_api(self, cr, *args, **kwargs):
        with Scope(cr, SUPERUSER_ID, None):
            return method(self, cr, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        value = method(self, cr, *args, **kwargs)
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def cr_context(method):
    """ Decorate a traditional-style method that takes `cr`, `context` as parameters. """
    method._api = cr_context
    convert = _returns_new(method)

    def old_api(self, cr, *args, **kwargs):
        with Scope(cr, SUPERUSER_ID, kwargs.get('context')):
            return method(self, cr, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        kwargs = dict(kwargs, context=context)
        value = method(self, cr, *args, **kwargs)
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def cr_uid(method):
    """ Decorate a traditional-style method that takes `cr`, `uid` as parameters. """
    method._api = cr_uid
    convert = _returns_new(method)

    def old_api(self, cr, uid, *args, **kwargs):
        with Scope(cr, uid, None):
            return method(self, cr, uid, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        value = method(self, cr, uid, *args, **kwargs)
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def cr_uid_context(method):
    """ Decorate a traditional-style method that takes `cr`, `uid`, `context` as
        parameters. Such a method may be called in both record and traditional
        styles, like::

            obj.method(args)
            obj.method(cr, uid, args, context=context)
    """
    method._api = cr_uid_context
    convert = _returns_new(method)

    def old_api(self, cr, uid, *args, **kwargs):
        with Scope(cr, uid, kwargs.get('context')):
            return method(self, cr, uid, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        kwargs = dict(kwargs, context=context)
        value = method(self, cr, uid, *args, **kwargs)
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def cr_uid_id(method):
    """ Decorate a traditional-style method that takes `cr`, `uid`, `id` as
        parameters. Such a method may be called in both record and traditional
        styles. The resulting method follows the :ref:`record-map-convention`.
    """
    method._api = cr_uid_id
    convert = _returns_new(method)

    def old_api(self, cr, uid, id, *args, **kwargs):
        with Scope(cr, uid, None):
            return method(self, cr, uid, id, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        if self.is_record():
            value = method(self, cr, uid, self.id, *args, **kwargs)
        else:
            value = [method(self, cr, uid, rec.id, *args, **kwargs) for rec in self]
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def cr_uid_id_context(method):
    """ Decorate a traditional-style method that takes `cr`, `uid`, `id`,
        `context` as parameters. The resulting method follows the
        :ref:`record-map-convention`. Such a method::

            @api.cr_uid_id
            def method(self, cr, uid, id, args, context=None):
                ...

        may be called in both record and traditional styles, like::

            rec = model.record(id)

            # the following calls are equivalent
            rec.method(args)
            model.method(cr, uid, id, args, context=context)
    """
    method._api = cr_uid_id_context
    convert = _returns_new(method)

    def old_api(self, cr, uid, id, *args, **kwargs):
        with Scope(cr, uid, kwargs.get('context')):
            return method(self, cr, uid, id, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        kwargs = dict(kwargs, context=context)
        if self.is_record():
            value = method(self, cr, uid, self.id, *args, **kwargs)
        else:
            value = [method(self, cr, uid, rec.id, *args, **kwargs) for rec in self]
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def cr_uid_ids(method):
    """ Decorate a traditional-style method that takes `cr`, `uid`, `ids` as
        parameters. Such a method may be called in both record and traditional
        styles. This decorator supports the :ref:`record-map-convention`.
    """
    method._api = cr_uid_ids
    convert = _returns_new(method)

    def old_api(self, cr, uid, ids, *args, **kwargs):
        with Scope(cr, uid, None):
            return method(self, cr, uid, ids, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        if self.is_record():
            value = _get_one(method(self, cr, uid, [self.id], *args, **kwargs))
        else:
            value = method(self, cr, uid, map(int, self), *args, **kwargs)
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def cr_uid_ids_context(method):
    """ Decorate a traditional-style method that takes `cr`, `uid`, `ids`,
        `context` as parameters. Such a method::

            @api.cr_uid_ids_context
            def method(self, cr, uid, ids, args, context=None):
                ...

        may be called in both record and traditional styles, like::

            recs = model.recordset(ids)

            # the following calls are equivalent
            recs.method(args)
            model.method(cr, uid, ids, args, context=context)

        This decorator supports the :ref:`record-map-convention`.
        It is generally not necessary, see :func:`guess`.
    """
    method._api = cr_uid_ids_context
    convert = _returns_new(method)

    def old_api(self, cr, uid, ids, *args, **kwargs):
        with Scope(cr, uid, kwargs.get('context')):
            return method(self, cr, uid, ids, *args, **kwargs)

    def new_api(self, *args, **kwargs):
        cr, uid, context = scope
        kwargs = dict(kwargs, context=context)
        if self.is_record():
            value = _get_one(method(self, cr, uid, [self.id], *args, **kwargs))
        else:
            value = method(self, cr, uid, map(int, self), *args, **kwargs)
        return convert(self, value)

    return _make_wrapper(method, old_api, new_api)


def noguess(method):
    """ Decorate a method to prevent any effect from :func:`guess`. """
    method._api = False
    return method


def guess(method):
    """ Decorate `method` to make it callable in both traditional and record
        styles. This decorator is applied automatically by the model's
        metaclass, and has no effect on already-decorated methods.

        The API style is determined by heuristics on the parameter names: ``cr``
        or ``cursor`` for the cursor, ``uid`` or ``user`` for the user id,
        ``id`` or ``ids`` for a list of record ids, and ``context`` for the
        context dictionary. If a traditional API is recognized, one of the
        decorators :func:`cr`, :func:`cr_context`, :func:`cr_uid`,
        :func:`cr_uid_context`, :func:`cr_uid_id`, :func:`cr_uid_id_context`,
        :func:`cr_uid_ids`, :func:`cr_uid_ids_context` is applied on the method.

        Method calls are considered traditional style when their first parameter
        is a database cursor.
    """
    # introspection on argument names to determine api style
    argnames = method.func_code.co_varnames[:method.func_code.co_argcount]
    if len(argnames) < 4:
        argnames = argnames + (None,) * (4 - len(argnames))

    if argnames[0] == 'self':
        if argnames[1] in ('cr', 'cursor'):
            if argnames[2] in ('uid', 'user'):
                if argnames[3] == 'ids':
                    if 'context' in argnames:
                        return cr_uid_ids_context(method)
                    else:
                        return cr_uid_ids(method)
                elif argnames[3] == 'id':
                    if 'context' in argnames:
                        return cr_uid_id_context(method)
                    else:
                        return cr_uid_id(method)
                elif 'context' in argnames:
                    return cr_uid_context(method)
                else:
                    return cr_uid(method)
            elif 'context' in argnames:
                return cr_context(method)
            else:
                return cr(method)

    # no wrapping by default
    return noguess(method)


# keep those imports here in order to handle cyclic dependencies correctly
from openerp import SUPERUSER_ID
from openerp.osv.scope import Scope, proxy as scope
from openerp.sql_db import Cursor
