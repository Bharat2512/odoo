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

""" High-level objects for fields. """

import base64
from copy import copy
from datetime import date, datetime
import logging

from openerp.tools import float_round, ustr, html_sanitize, lazy_property
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT as DATE_FORMAT
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT

DATE_LENGTH = len(date.today().strftime(DATE_FORMAT))
DATETIME_LENGTH = len(datetime.now().strftime(DATETIME_FORMAT))

_logger = logging.getLogger(__name__)


def default(value):
    """ Return a compute function that provides a constant default value. """
    def compute(field, records):
        for record in records:
            record[field.name] = value

    return compute


def compute_related(field, records):
    """ Compute the related `field` on `records`. """
    for record in records:
        value = record
        for name in field.related:
            value = value[name]
        record[field.name] = value

def inverse_related(field, records):
    """ Inverse the related `field` on `records`. """
    for record in records:
        other = record
        for name in field.related[:-1]:
            other = other[name]
        other[field.related[-1]] = record[field.name]

def search_related(field, operator, value):
    """ Determine the domain to search on `field`. """
    return [('.'.join(field.related), operator, value)]


def _invoke_model(func, model):
    """ hack for invoking a callable with a model in both API styles """
    try:
        return func(model)
    except TypeError:
        return func(model, *scope.args)


class MetaField(type):
    """ Metaclass for field classes. """
    _class_by_type = {}

    def __init__(cls, name, bases, attrs):
        super(MetaField, cls).__init__(name, bases, attrs)
        if cls.type:
            cls._class_by_type[cls.type] = cls


class Field(object):
    """ Base class of all fields. """
    __metaclass__ = MetaField

    _ready = False              # whether the field has been completely set up
    interface = False           # whether the field is created by the ORM

    name = None                 # name of the field
    model_name = None           # name of the model of this field
    type = None                 # type of the field (string)
    relational = False          # whether the field is a relational one
    inverse_field = None        # inverse field (object), if it exists

    store = True                # whether the field is stored in database
    depends = ()                # collection of field dependencies
    compute = None              # name of model method that computes value
    inverse = None              # name of model method that inverses field
    search = None               # name of model method that searches on field
    related = None              # sequence of field names, for related fields

    string = None               # field label
    help = None                 # field tooltip
    readonly = False
    required = False
    groups = False              # csv list of group xml ids

    # attributes passed when converting from/to a column
    _attrs = ('string', 'help', 'readonly', 'required', 'groups')

    # attributes exported by get_description()
    _desc0 = ('type', 'store')
    _desc1 = ('depends', 'related', 'string', 'help', 'readonly', 'required', 'groups')

    def __init__(self, string=None, **kwargs):
        kwargs['string'] = string
        for attr, value in kwargs.iteritems():
            setattr(self, attr, value)

    def copy(self, **kwargs):
        """ make a copy of `self`, possibly modified with parameters `kwargs` """
        field = copy(self)
        for attr, value in kwargs.iteritems():
            setattr(field, attr, value)
        lazy_property.reset_all(field)      # reset all lazy properties on field
        return field

    def set_model_name(self, model_name, name):
        """ assign the model and field names of `self` """
        self.model_name = model_name
        self.name = name
        if not self.string:
            self.string = name.replace('_', ' ').capitalize()

    def setup_related(self):
        """ Setup the attributes of the related field `self`. """
        # fix the type of self.related if necessary
        if isinstance(self.related, basestring):
            self.related = tuple(self.related.split('.'))

        # check type consistency
        model = self.model
        for name in self.related[:-1]:
            model = model[name]
        field = model._fields[self.related[-1]]
        if self.type != field.type:
            raise Warning("Type of related field %s is inconsistent with %s" % (self, field))

        # determine dependencies, compute, inverse, and search
        self.depends = ('.'.join(self.related),)
        self.compute = compute_related
        self.inverse = inverse_related
        self.search = search_related

        # copy attributes from field to self (readonly, required, etc.)
        field.complete_setup()
        for attr in self._attrs:
            if not getattr(self, attr) and getattr(field, attr):
                setattr(self, attr, getattr(field, attr))

    def __str__(self):
        return "%s.%s" % (self.model_name, self.name)

    @lazy_property
    def model(self):
        """ return the model instance of `self` """
        return scope.model(self.model_name)

    def get_description(self):
        """ Return a dictionary that describes the field `self`. """
        desc = {}
        for arg in self._desc0:
            desc[arg] = getattr(self, arg)
        for arg in self._desc1:
            if getattr(self, arg, None):
                desc[arg] = getattr(self, arg)
        return desc

    @classmethod
    def from_column(cls, column):
        """ return a field for interfacing the low-level field `column` """
        # delegate to the subclass corresponding to the column type, or Field
        # for unknown column types
        field_class = cls._class_by_type.get(column._type, Field)
        field = field_class._from_column(column)
        field.interface = True
        return field

    @classmethod
    def _from_column(cls, column):
        # generic implementation
        kwargs = dict((attr, getattr(column, attr)) for attr in cls._attrs)
        if cls is Field:
            kwargs['type'] = column._type
        return cls(**kwargs)

    def to_column(self):
        """ return a low-level field object corresponding to `self` """
        assert self.store
        kwargs = self._to_column()
        return getattr(fields, self.type)(**kwargs)

    def _to_column(self):
        """ return a kwargs dictionary to pass to the column class """
        return dict((attr, getattr(self, attr)) for attr in self._attrs)

    def __get__(self, instance, owner):
        """ read the value of field `self` for the record `instance` """
        if instance is None:
            return self         # the field is accessed through the class owner
        assert instance._name == self.model_name

        with instance._scope:
            if instance:
                # non-null records: get value through their cache
                return instance._record_cache[self.name]
            else:
                # null records: return null value
                return self.null()

    def __set__(self, instance, value):
        """ set the value of field `self` for the record `instance` """
        assert instance._name == self.model_name
        with instance._scope:
            # adapt value to the cache level, and set it through the cache
            value = self.convert_to_cache(value)
            instance._record_cache[self.name] = value

    def null(self):
        """ return the null value for this field """
        return False

    def convert_to_cache(self, value):
        """ convert `value` to the cache level; `value` may come from an
            assignment, or have the format of methods :meth:`BaseModel.read` or
            :meth:`BaseModel.write`
        """
        return value

    def convert_to_read(self, value):
        """ convert `value` from the cache to a value as returned by method
            :meth:`BaseModel.read`
        """
        return value

    def convert_to_write(self, value):
        """ convert `value` from the cache to a valid value for method
            :meth:`BaseModel.write`
        """
        return self.convert_to_read(value)

    def convert_to_export(self, value):
        """ convert `value` from the cache to a valid value for export. """
        return bool(value) and ustr(value)

    #
    # Management of the computation of field values.
    #

    def compute_value(self, records):
        """ Invoke the compute method on `records`. """
        batch = len(records) > 1
        recompute = bool(records & scope.recomputation.todo(self))
        for cache in records._caches:
            cache.set_busy(self.name, batch=batch, recompute=recompute)

        if isinstance(self.compute, basestring):
            getattr(records, self.compute)()
        elif callable(self.compute):
            self.compute(self, records)
        else:
            raise Warning("No way to compute %s on %s" % (self, records))

    def read_value(self, records):
        """ Read the value of `self` for `records` from the database. """
        name = self.name
        column = records._columns[name]

        # fetch the records of this model without name in their cache
        fetch_recs = records.browse(records._model_cache.without_field(name))

        # prefetch all classic and many2one fields if column is one of them
        # Note: do not prefetch fields when records.pool._init is True, because
        # some columns may be missing from the database!
        if column._prefetch and not records.pool._init:
            fetch_fields = set(fname
                for fname, fcolumn in records._columns.iteritems()
                if fcolumn._classic_write and fcolumn._prefetch)
        else:
            fetch_fields = set((name,))

        # do not fetch the records/fields that have to be recomputed
        if scope.recomputation:
            for fname in list(fetch_fields):
                recs = scope.recomputation.todo(records._fields[fname])
                if records & recs:
                    fetch_fields.discard(fname)     # do not fetch that one
                else:
                    fetch_recs -= recs              # do not fetch recs

        # fetch records
        result = fetch_recs.read(list(fetch_fields), load='_classic_write')

        # method read is supposed to fetch the cache with the results
        if any(name not in record._record_cache for record in records):
            for data in result:
                record = records.browse(data['id'])
                record._update_cache({name: data[name]})

            failed = records.browse()
            for record in records:
                if name not in record._record_cache:
                    failed += record

            if failed:
                raise AccessError("Cannot read %s on %s." % (name, failed))

    def determine_value(self, record):
        """ Determine the value of `self` for `record`. """
        if self.store:
            # recompute field on record if required
            recs_todo = scope.recomputation.todo(self)
            if record in recs_todo:
                self.compute_value(recs_todo.exists())
                scope.recomputation.done(self, recs_todo)
            else:
                self.read_value(record)
        else:
            # compute self for the records without value for self in their cache
            recs = record.browse(record._model_cache.without_field(self.name))
            self.compute_value(recs)

    def determine_default(self, record):
        """ determine the default value of field `self` on `record` """
        record._record_cache.set_null(self.name)
        if self.compute:
            self.compute_value(record)

    def determine_inverse(self, records):
        """ Given the value of `self` on `records`, inverse the computation. """
        if isinstance(self.inverse, basestring):
            getattr(records, self.inverse)()
        elif callable(self.inverse):
            self.inverse(self, records)

    def determine_domain(self, operator, value):
        """ Return a domain representing a condition on `self`. """
        if isinstance(self.search, basestring):
            return getattr(self.model.browse(), self.search)(operator, value)
        elif callable(self.search):
            return self.search(self, operator, value)
        else:
            return [(self.name, operator, value)]

    #
    # Management of the recomputation of computed fields.
    #
    # Each field stores a set of triggers (`field`, `path`); when the field is
    # modified, it invalidates the cache of `field` and registers the records to
    # recompute based on `path`. See method `modified` below for details.
    #

    def complete_setup(self):
        """ Complete the setup of `self`: make it process its dependencies and
            store triggers on other fields to be recomputed.
        """
        if not self._ready:
            self._ready = True

            if self.related is not None:
                # setup all attributes of related field
                self.setup_related()
            else:
                # retrieve dependencies from compute method
                if isinstance(self.compute, basestring):
                    method = getattr(type(self.model), self.compute)
                else:
                    method = self.compute
                self.depends = getattr(method, '_depends', ())

            # put invalidation/recomputation triggers on dependencies
            for path in self.depends:
                self._depends_on_model(self.model, [], path.split('.'))

    def _depends_on_model(self, model, path0, path1):
        """ Make `self` depend on `model`; `path0 + path1` is a dependency of
            `self`, and `path0` is the sequence of field names from `self.model`
            to `model`.
        """
        name, tail = path1[0], path1[1:]
        if name == '*':
            # special case: add triggers on all fields of model
            fields = model._fields.values()
        else:
            fields = (model._fields[name],)

        for field in fields:
            field._add_trigger_for(self, path0, tail)

    @lazy_property
    def _triggers(self):
        """ List of pairs (`field`, `path`), where `field` is a field to
            recompute, and `path` is the dependency between `field` and `self`
            (dot-separated sequence of field names between `field.model` and
            `self.model`).
        """
        return []

    def _add_trigger_for(self, field, path0, path1):
        """ Add a trigger on `self` to recompute `field`; `path0` is the
            sequence of field names from `field.model` to `self.model`; ``path0
            + [self.name] + path1`` is a dependency of `field`.
        """
        self._triggers.append((field, '.'.join(path0) if path0 else 'id'))
        _logger.debug("Add trigger on field %s to recompute field %s", self, field)

    def modified(self, records):
        """ Notify that field `self` has been modified on `records`: invalidate
            the cache, and prepare the fields/records to recompute.
        """
        # invalidate cache for self
        ids = records.unbrowse()
        scope.invalidate(self.model_name, self.name, ids)

        # invalidate the fields that depend on self, and prepare their
        # recomputation
        for field, path in self._triggers:
            if field.store:
                with scope(user=SUPERUSER_ID, context={'active_test': False}):
                    target = field.model.search([(path, 'in', ids)])
                scope.invalidate(field.model_name, field.name, target.unbrowse())
                scope.recomputation.todo(field, target)
            else:
                scope.invalidate(field.model_name, field.name, None)

    def modified_draft(self, record):
        """ Same as :meth:`modified`, but in the case where `record` is a draft
            instance.
        """
        assert record.draft and len(record) == 1
        # invalidate cache for self
        cache = record._record_cache
        cache.pop(self.name, None)
        # invalidate dependent fields on record only
        for field, _path in self._triggers:
            if field.model_name == record._name:
                cache.pop(field.name, None)


class Boolean(Field):
    """ Boolean field. """
    type = 'boolean'

    def convert_to_cache(self, value):
        return bool(value)

    def convert_to_export(self, value):
        return ustr(value)


class Integer(Field):
    """ Integer field. """
    type = 'integer'

    def convert_to_cache(self, value):
        return int(value or 0)


class Float(Field):
    """ Float field. """
    type = 'float'
    digits = None                       # None, (precision, scale), or callable

    _attrs = Field._attrs + ('digits',)
    _desc1 = Field._desc1 + ('digits',)

    @classmethod
    def _from_column(cls, column):
        column.digits_change(scope.cr)      # determine column.digits
        kwargs = dict((attr, getattr(column, attr)) for attr in cls._attrs)
        return cls(**kwargs)

    def to_column(self):
        if callable(self.digits):
            self.digits = self.digits(scope.cr)
        return super(Float, self).to_column()

    def convert_to_cache(self, value):
        # apply rounding here, otherwise value in cache may be wrong!
        if self.digits:
            return float_round(float(value or 0.0), precision_digits=self.digits[1])
        else:
            return float(value or 0.0)


class _String(Field):
    """ Abstract class for string fields. """
    translate = False

    _attrs = Field._attrs + ('translate',)
    _desc1 = Field._desc1 + ('translate',)


class Char(_String):
    """ Char field. """
    type = 'char'
    size = None

    _attrs = _String._attrs + ('size',)
    _desc1 = _String._desc1 + ('size',)

    def convert_to_cache(self, value):
        return bool(value) and ustr(value)[:self.size]


class Text(_String):
    """ Text field. """
    type = 'text'


class Html(_String):
    """ Html field. """
    type = 'html'

    def convert_to_cache(self, value):
        return bool(value) and html_sanitize(value)


class Date(Field):
    """ Date field. """
    type = 'date'

    def convert_to_cache(self, value):
        if isinstance(value, (date, datetime)):
            value = value.strftime(DATE_FORMAT)
        elif value:
            # check the date format
            value = value[:DATE_LENGTH]
            datetime.strptime(value, DATE_FORMAT)
        return value or False


class Datetime(Field):
    """ Datetime field. """
    type = 'datetime'

    def convert_to_cache(self, value):
        if isinstance(value, (date, datetime)):
            value = value.strftime(DATETIME_FORMAT)
        elif value:
            # check the datetime format
            value = value[:DATETIME_LENGTH]
            datetime.strptime(value, DATETIME_FORMAT)
        return value or False


class Binary(Field):
    """ Binary field. """
    type = 'binary'

    def convert_to_cache(self, value):
        return value or False


class Selection(Field):
    """ Selection field. """
    type = 'selection'
    selection = None        # [(value, string), ...], model method or method name

    _attrs = Field._attrs + ('selection',)

    def __init__(self, selection, string=None, **kwargs):
        """ Selection field.

            :param selection: specifies the possible values for this field.
                It is given as either a list of pairs (`value`, `string`), or a
                model method, or a method name.
        """
        super(Selection, self).__init__(selection=selection, string=string, **kwargs)

    def get_description(self):
        desc = super(Selection, self).get_description()
        desc['selection'] = self.get_selection()
        return desc

    def _to_column(self):
        kwargs = super(Selection, self)._to_column()
        if isinstance(self.selection, basestring):
            method = self.selection
            kwargs['selection'] = lambda self, *args, **kwargs: getattr(self, method)(*args, **kwargs)
        return kwargs

    def get_selection(self):
        """ return the selection list (pairs (value, string)) """
        value = self.selection
        if isinstance(value, basestring):
            value = getattr(self.model, value)()
        elif callable(value):
            value = _invoke_model(value, self.model)
        return value

    def get_values(self):
        """ return a list of the possible values """
        return [item[0] for item in self.get_selection()]

    def convert_to_cache(self, value):
        if value in self.get_values():
            return value
        elif not value:
            return False
        raise ValueError("Wrong value for %s: %r" % (self, value))

    def convert_to_export(self, value):
        if not isinstance(self.selection, list):
            # FIXME: this reproduces an existing buggy behavior!
            return value
        for item in self.get_selection():
            if item[0] == value:
                return item[1]
        return False


class Reference(Selection):
    """ Reference field. """
    type = 'reference'
    size = 128

    _attrs = Selection._attrs + ('size',)

    def __init__(self, selection, string=None, **kwargs):
        """ Reference field.

            :param selection: specifies the possible model names for this field.
                It is given as either a list of pairs (`value`, `string`), or a
                model method, or a method name.
        """
        super(Reference, self).__init__(selection=selection, string=string, **kwargs)

    def convert_to_cache(self, value):
        if isinstance(value, BaseModel):
            if value._name in self.get_values() and len(value) <= 1:
                return value.scoped() or False
        elif isinstance(value, basestring):
            res_model, res_id = value.split(',')
            return scope.model(res_model).browse(int(res_id))
        elif not value:
            return False
        raise ValueError("Wrong value for %s: %r" % (self, value))

    def convert_to_read(self, value):
        return "%s,%s" % (value._name, value.id) if value else False

    def convert_to_export(self, value):
        return bool(value) and value.name_get()[0][1]


class _Relational(Field):
    """ Abstract class for relational fields. """
    relational = True
    comodel_name = None                 # name of model of values
    domain = None                       # domain for searching values
    context = None                      # context for searching values

    @lazy_property
    def comodel(self):
        """ return the comodel instance of `self` """
        return scope.model(self.comodel_name)

    def get_description(self):
        desc = super(_Relational, self).get_description()
        desc['relation'] = self.comodel_name
        desc['domain'] = self.domain(self.model) if callable(self.domain) else self.domain
        desc['context'] = self.context
        return desc

    def null(self):
        return self.comodel.browse()

    def _add_trigger_for(self, field, path0, path1):
        # overridden to traverse relations and manage inverse fields
        Field._add_trigger_for(self, field, path0, [])

        if self.inverse_field:
            # add trigger on inverse field, too
            Field._add_trigger_for(self.inverse_field, field, path0 + [self.name], [])

        if path1:
            # recursively traverse the dependency
            field._depends_on_model(self.comodel, path0 + [self.name], path1)

    def modified(self, records):
        # Invalidate cache for self.inverse_field, too. Note that recomputation
        # of fields that depend on self.inverse_field is already covered by the
        # triggers (see above).
        super(_Relational, self).modified(records)
        if self.inverse_field:
            inv = self.inverse_field
            scope.invalidate(inv.model_name, inv.name, None)


class Many2one(_Relational):
    """ Many2one field. """
    type = 'many2one'
    ondelete = None                     # defaults to 'set null' in ORM

    _attrs = Field._attrs + ('ondelete',)

    def __init__(self, comodel_name, string=None, **kwargs):
        super(Many2one, self).__init__(comodel_name=comodel_name, string=string, **kwargs)

    @lazy_property
    def inverse_field(self):
        for field in self.comodel._fields.itervalues():
            if isinstance(field, One2many) and field.inverse_field == self:
                return field
        return None

    @lazy_property
    def inherits(self):
        """ Whether `self` implements inheritance between model and comodel. """
        return self.name in self.model._inherits.itervalues()

    @classmethod
    def _from_column(cls, column):
        kwargs = dict((attr, getattr(column, attr)) for attr in cls._attrs)
        kwargs['comodel_name'] = column._obj
        return cls(**kwargs)

    def _to_column(self):
        kwargs = super(Many2one, self)._to_column()
        kwargs['obj'] = self.comodel_name
        kwargs['domain'] = self.domain or []
        return kwargs

    def convert_to_cache(self, value):
        if isinstance(value, BaseModel):
            if value._name == self.comodel_name and len(value) <= 1:
                return value.scoped()
            raise ValueError("Wrong value for %s: %r" % (self, value))
        elif isinstance(value, tuple):
            return self.comodel.browse(value[0])
        elif isinstance(value, dict):
            return self.comodel.new(value)
        else:
            return self.comodel.browse(value)

    def convert_to_read(self, value):
        return bool(value) and value.name_get()[0]

    def convert_to_write(self, value):
        return value.id

    def convert_to_export(self, value):
        return bool(value) and value.name_get()[0][1]

    def determine_default(self, record):
        super(Many2one, self).determine_default(record)
        if self.inherits:
            # special case: fields that implement inheritance between models
            value = record[self.name]
            if not value:
                # the default value cannot be null, use a new record instead
                record[self.name] = self.comodel.new()


class _RelationalMulti(_Relational):
    """ Abstract class for relational fields *2many. """

    def convert_to_cache(self, value):
        if isinstance(value, BaseModel):
            if value._name == self.comodel_name:
                return value.scoped()
        elif isinstance(value, list):
            # value is a list of record ids or commands
            result = self.comodel.browse()
            for command in value:
                if not isinstance(command, (tuple, list)):
                    result += self.comodel.browse(command)
                elif command[0] == 0:
                    result += self.comodel.new(command[2])
                elif command[0] == 1:
                    record = self.comodel.browse(command[1])
                    record.draft = True
                    record.update(command[2])
                    result += record
                elif command[0] == 2:
                    pass
                elif command[0] == 3:
                    pass
                elif command[0] == 4:
                    result += self.comodel.browse(command[1])
                elif command[0] == 5:
                    result = self.comodel.browse()
                elif command[0] == 6:
                    result = self.comodel.browse(command[2])
            return result
        elif not value:
            return self.null()
        raise ValueError("Wrong value for %s: %s" % (self, value))

    def convert_to_read(self, value):
        return value.unbrowse()

    def convert_to_write(self, value):
        result = [(5,)]
        for record in value:
            if record.draft:
                values = record._convert_to_write(record.get_draft_values())
                command = (1, record.id, values) if record.id else (0, 0, values)
                result.append(command)
            else:
                result.append((4, record.id))
        return result

    def convert_to_export(self, value):
        return bool(value) and ','.join(name for id, name in value.name_get())


class One2many(_RelationalMulti):
    """ One2many field. """
    type = 'one2many'
    inverse_name = None                 # name of the inverse field

    def __init__(self, comodel_name, inverse_name=None, string=None, **kwargs):
        super(One2many, self).__init__(
            comodel_name=comodel_name, inverse_name=inverse_name, string=string, **kwargs)

    @lazy_property
    def inverse_field(self):
        return self.inverse_name and self.comodel._fields[self.inverse_name]

    def get_description(self):
        desc = super(One2many, self).get_description()
        desc['relation_field'] = self.inverse_name
        return desc

    @classmethod
    def _from_column(cls, column):
        kwargs = dict((attr, getattr(column, attr)) for attr in cls._attrs)
        # beware when getting parameters: column may be a function field
        kwargs['comodel_name'] = column._obj
        kwargs['inverse_name'] = getattr(column, '_fields_id', None)
        return cls(**kwargs)

    def _to_column(self):
        kwargs = super(One2many, self)._to_column()
        kwargs['obj'] = self.comodel_name
        kwargs['fields_id'] = self.inverse_name
        kwargs['domain'] = self.domain or []
        return kwargs


class Many2many(_RelationalMulti):
    """ Many2many field. """
    type = 'many2many'
    relation = None                     # name of table
    column1 = None                      # column of table referring to model
    column2 = None                      # column of table referring to comodel

    def __init__(self, comodel_name, relation=None, column1=None, column2=None,
                string=None, **kwargs):
        super(Many2many, self).__init__(comodel_name=comodel_name, relation=relation,
            column1=column1, column2=column2, string=string, **kwargs)

    @lazy_property
    def inverse_field(self):
        if not self.compute:
            expected = (self.relation, self.column2, self.column1)
            for field in self.comodel._fields.itervalues():
                if isinstance(field, Many2many) and \
                        (field.relation, field.column1, field.column2) == expected:
                    return field
        return None

    @classmethod
    def _from_column(cls, column):
        kwargs = dict((attr, getattr(column, attr)) for attr in cls._attrs)
        # beware when getting parameters: column may be a function field
        kwargs['comodel_name'] = column._obj
        kwargs['relation'] = getattr(column, '_rel', None)
        kwargs['column1'] = getattr(column, '_id1', None)
        kwargs['column2'] = getattr(column, '_id2', None)
        return cls(**kwargs)

    def _to_column(self):
        kwargs = super(Many2many, self)._to_column()
        kwargs['obj'] = self.comodel_name
        kwargs['rel'] = self.relation
        kwargs['id1'] = self.column1
        kwargs['id2'] = self.column2
        kwargs['domain'] = self.domain or []
        return kwargs


class Id(Field):
    """ Special case for field 'id'. """
    interface = True            # that field is always created by the ORM
    store = False
    readonly = True

    @classmethod
    def _from_column(cls, column):
        raise NotImplementedError()

    def __get__(self, instance, owner):
        if instance is None:
            return self         # the field is accessed through the class owner
        return instance._id

    def __set__(self, instance, value):
        raise NotImplementedError()


# imported here to avoid dependency cycle issues
from openerp import SUPERUSER_ID
from openerp.exceptions import AccessError, Warning
from openerp.osv import fields
from openerp.osv.orm import BaseModel
from openerp.osv.scope import proxy as scope
