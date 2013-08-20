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

""" This module provides the implementation of the records cache.

    The cache is structured as a set of nested dictionaries indexed by model
    name, record id, and field name (in that order)::

        # access the value of a field of a given record
        value = cache[model_name][record_id][field_name]

    The cache of a given record is a mapping associating values to field names.
    That cache is not a simple dictionary: it is a read-through write-through
    cache: getting an element may issue a read(), and setting an element may
    issue a write()::

        # retrieve the cache of a given record
        record_cache = cache[model_name][record_id]

        # this statement may issue a read() to retrieve the value
        value = record_cache[field_name]

        # this statement may issue a write() to store the value in the database
        record_cache[field_name] = value

    Other behaviors are possible: getting an element may trigger an error while
    that element is being computed, etc.

"""


from collections import defaultdict, namedtuple
from pprint import pformat

#
# The design of the record cache is pretty simple. The cache does not store
# values directly, instead it has a "slot" for each field. That slot may contain
# a value and manages how to get/set that field in the cache.
#

#
# getter and setter functions for slots
#

def get_value(cache, name):
    """ Generic getter: read/compute value or get default. """
    record = cache.record
    if cache.id:
        record._fields[name].determine_value(record)
    else:
        record.add_default_value(name)
    return cache[name]

def get_null(cache, name):
    """ Getter for an implicit null value. """
    return cache.record._fields[name].null()

def get_busy(cache, name):
    """ Getter for a field being computed. """
    raise Warning("No value for field %s on %s" % (name, cache.record))

def get_batch(cache, name):
    """ Getter for a field being computed in batch. """
    record = cache.record
    record._fields[name].compute_value(record)
    return cache[name]

def set_value(cache, name, value):
    """ Generic setter: write value and store it into the cache. """
    record = cache.record
    field = record._fields[name]
    if not cache.id:
        field.modified_draft(record)
    elif field.store or field.inverse:
        record.write({name: field.convert_to_write(value)})
    cache.data[name] = ValueSlot.make(value)

def set_cache(cache, name, value):
    """ Cache setter: only store in cache. """
    cache.data[name] = ValueSlot.make(value)

# the Slot type encapsulates getter and setter functions
Slot = namedtuple('Slot', ('get', 'set'))

# empty slot
EmptySlot = Slot(get_value, set_value)
default_slot = lambda: EmptySlot

# slot implicitly containing null
NullSlot = Slot(get_null, set_value)

# slots for non-stored fields being computed
BusySlot = Slot(get_busy, set_cache)
BatchSlot = Slot(get_batch, set_cache)

# slots for stored fields being recomputed
BusyRecomputeSlot = Slot(get_busy, set_value)
BatchRecomputeSlot = Slot(get_batch, set_value)

class ValueSlot(Slot):
    """ Slot storing a value. """
    @classmethod
    def make(cls, value):
        return ValueSlot(lambda cache, name: value, set_value)


class RecordCache(object):
    """ Cache for the fields of a record in a given scope. """

    #
    # Note. RecordCache does not inherit collections.MutableMapping because
    # equality is not structural: cache1 == cache2 only if cache1 is cache2!
    #
    
    def __init__(self, model_cache, id):
        self.model_name = model_cache.name
        self.fields = model_cache.fields
        self.data = defaultdict(default_slot)
        self.id = id

    @property
    def record(self):
        scope = scope_proxy.current
        return scope.registry[self.model_name]._instance(scope, (self,))

    def __contains__(self, name):
        return isinstance(self.data.get(name), ValueSlot)

    def __getitem__(self, name):
        return self.data[name].get(self, name)

    def __setitem__(self, name, value):
        self.data[name].set(self, name, value)
        self.fields.add(name)

    def set_null(self, name):
        """ Set implicit value of `name` being null. """
        self.data[name] = NullSlot

    def set_busy(self, name, batch=False, recompute=False):
        """ Set the cache busy for field `name` when it is read/computed. """
        if batch:
            self.data[name] = BatchRecomputeSlot if recompute else BatchSlot
        else:
            self.data[name] = BusyRecomputeSlot if recompute else BusySlot

    def pop(self, name, default=None):
        slot = self.data.pop(name, None)
        return slot.get(self, name) if isinstance(slot, ValueSlot) else default

    def clear(self):
        self.data.clear()

    def __iter__(self):
        for name, slot in self.data.iteritems():
            if isinstance(slot, ValueSlot):
                yield name

    def iteritems(self):
        for name, slot in self.data.iteritems():
            if isinstance(slot, ValueSlot):
                yield name, slot.get(self, name)

    def __len__(self):
        return len(self.data)

    def dump(self):
        return dict(self.iteritems())


class ModelCache(defaultdict):
    """ Cache for the records of a given model in a given scope. It contains the
        caches of the records that have a non-null 'id'; caches for non-existing
        records are not retained.
    """
    def __init__(self, model_name):
        super(ModelCache, self).__init__()
        self.name = model_name
        self.fields = set()             # set of fields present in self

    def __missing__(self, id):
        record_cache = RecordCache(self, id)
        if id:
            self[id] = record_cache
        return record_cache

    def without_field(self, name):
        """ Return the ids of the records that do not have field `name` in their
            cache.
        """
        return iter(id for id, cache in self.iteritems() if name not in cache)

    def dump(self):
        """ Return a "dump" of the model cache. """
        return dict(
            (record_id, record_cache.dump())
            for record_id, record_cache in self.iteritems()
        )


class Cache(defaultdict):
    """ Cache for records in a given scope. """
    def __init__(self):
        super(Cache, self).__init__()

    def __missing__(self, model_name):
        self[model_name] = model_cache = ModelCache(model_name)
        return model_cache

    def invalidate(self, model_name, field_name, ids=None):
        """ Invalidate a field for the given record ids. """
        model_cache = self[model_name]
        if field_name in model_cache.fields:
            if ids is None:
                model_cache.fields.discard(field_name)
                for record_cache in model_cache.itervalues():
                    record_cache.pop(field_name, None)
            else:
                for id in ids:
                    model_cache[id].pop(field_name, None)

    def invalidate_all(self):
        """ Invalidate the whole cache. """
        # Note that record caches cannot be dropped from the cache, since they
        # are memoized in model instances.
        for model_cache in self.itervalues():
            model_cache.fields.clear()
            for record_cache in model_cache.itervalues():
                record_cache.clear()

    def dump(self):
        """ Return a "dump" of the cache. """
        return dict(
            (model_name, model_cache.dump())
            for model_name, model_cache in self.iteritems()
        )

    def check(self):
        """ self-check for validating the cache """
        scope = scope_proxy.current
        assert scope.cache is self

        # make a full copy of the cache, and invalidate it
        cache_dump = self.dump()
        self.invalidate_all()

        # re-fetch the records, and compare with their former cache
        invalids = []
        for model_name, model_dump in cache_dump.iteritems():
            model = scope.model(model_name)
            records = model.browse(model_dump)
            for record, record_dump in zip(records, model_dump.itervalues()):
                for field, value in record_dump.iteritems():
                    if record[field] != value:
                        info = {'cached': value, 'fetched': record[field]}
                        invalids.append((record, field, info))

        if invalids:
            raise Warning('Invalid cache for records\n' + pformat(invalids))


# keep those imports here in order to handle cyclic dependencies correctly
from openerp.exceptions import Warning
from openerp.osv.scope import proxy as scope_proxy
