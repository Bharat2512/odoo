odoo.define('base_calendar.base_calendar', function (require) {
"use strict";

var core = require('web.core');
var CalendarView = require('web_calendar.CalendarView');
var data = require('web.data');
var Dialog = require('web.Dialog');
var form_common = require('web.form_common');
var Model = require('web.DataModel');
var Notification = require('web.notification').Notification;
var session = require('web.session');
var WebClient = require('web.WebClient');
var widgets = require('web_calendar.widgets');

var FieldMany2ManyTags = core.form_widget_registry.get('many2many_tags');
var _t = core._t;
var _lt = core._lt;
var QWeb = core.qweb;

function reload_favorite_list(result) {
    var self = result;
    if (result.view) {
        self = result.view;
    }
    return session.is_bound
    .then(function() {
        var sidebar_items = {};
        var filter_value = session.partner_id;
        var filter_item = {
            value: filter_value,
            label: session.name + _lt(" [Me]"),
            color: self.get_color(filter_value),
            avatar_model: self.avatar_model,
            is_checked: true,
        };
        sidebar_items[filter_value] = filter_item;

        filter_item = {
            value: -1,
            label: _lt("Everybody's calendars"),
            color: self.get_color(-1),
            avatar_model: self.avatar_model,
            is_checked: false
        };
        sidebar_items[-1] = filter_item;
        //Get my coworkers/contacts
        return new Model("calendar.contacts")
            .query(["partner_id"])
            .filter([["user_id", "=",session.uid]])
            .all()
            .then(function(result) {
                _.each(result, function(item) {
                    filter_value = item.partner_id[0];
                    filter_item = {
                        value: filter_value,
                        label: item.partner_id[1],
                        color: self.get_color(filter_value),
                        avatar_model: self.avatar_model,
                        is_checked: true,
                        can_be_removed: true,
                    };
                    sidebar_items[filter_value] = filter_item;
                });

                self.all_filters = sidebar_items;
                self.now_filter_ids = $.map(self.all_filters, function(o) { return o.value; });

                self.sidebar.filter.events_loaded(self.get_all_filters_ordered());
                self.sidebar.filter.set_filters();
            });
    });
}

CalendarView.include({
    extraSideBar: function() {
        var result = this._super();
        if (this.useContacts) {
            var self = this;
            return result.then(reload_favorite_list.bind(this, this)).then(function () {
                self.sidebar.filter.initialize_m2o();
            });
        }
        return result;
    },
    get_all_filters_ordered: function() {
        var filters = this._super();
        if (this.useContacts) {
            var filter_me = _.first(_.values(this.all_filters));
            var filter_all = this.all_filters[-1];
            filters = [].concat(filter_me, _.difference(filters, [filter_me, filter_all]), filter_all);
        }
        return filters;
    }
});

var FieldMany2One = core.form_widget_registry.get('many2one');
var SidebarFilterM2O = FieldMany2One.extend({
    get_search_blacklist: function () {
        return this._super.apply(this, arguments).concat(this.filter_ids);
    },
    set_filter_ids: function (filter_ids) {
        this.filter_ids = filter_ids;
    },
});

widgets.SidebarFilter.include({
    events: _.extend(widgets.SidebarFilter.prototype.events, {
        'click .oe_remove_follower': 'destroy_filter',
    }),
    init: function () {
        this._super.apply(this, arguments);
        this.ds_contacts = new data.DataSet(this, 'calendar.contacts', session.context);
    },
    reinitialize_m2o: function() {
        this.dfm.destroy();
        this.initialize_m2o();
    },
    initialize_m2o: function() {
        this.dfm = new form_common.DefaultFieldManager(this);
        this.dfm.extend_field_desc({
            partner_id: {
                relation: "res.partner",
            },
        });
        this.m2o = new SidebarFilterM2O(this.dfm, {
            attrs: {
                class: 'o_add_favorite_calendar',
                name: "partner_id",
                type: "many2one",
                options: '{"no_open": True}',
                placeholder: _t("Add Favorite Calendar"),
            },
        });
        this.m2o.set_filter_ids(_.pluck(this.view.all_filters, 'value'));
        this.m2o.appendTo(this.$el);
        this.m2o.on('change:value', this, this.add_filter.bind(this));
    },
    add_filter: function() {
        var self = this;
        var defs = [];
        _.each(this.m2o.display_value, function(element, index) {
            if (session.partner_id !== index) {
                defs.push(self.ds_contacts.call("create", [{'partner_id': index}]));
            }
        });
        return $.when.apply(null, defs)
            .then(reload_favorite_list.bind(this, this)
            .then(this.reinitialize_m2o.bind(this))
            .then(this.trigger_up.bind(this, 'reload_events'));
    },
    destroy_filter: function(e) {
        var self = this;
        var id = $(e.currentTarget).data('id');

        Dialog.confirm(this, _t("Do you really want to delete this filter from favorites ?"), {
            confirm_callback: function() {
                self.ds_contacts.call('unlink_from_partner_id', [id])
                    .then(reload_favorite_list.bind(self, self))
                    .then(self.reinitialize_m2o.bind(self))
                    .then(self.trigger_up.bind(self, 'reload_events'));
            },
        });
    },
});

var CalendarNotification = Notification.extend({
    template: "CalendarNotification",

    init: function(parent, title, text, eid) {
        this._super(parent, title, text, true);
        this.eid = eid;

        this.events = _.extend(this.events || {}, {
            'click .link2event': function() {
                var self = this;

                this.rpc("/web/action/load", {
                    action_id: "calendar.action_calendar_event_notify",
                }).then(function(r) {
                    r.res_id = self.eid;
                    return self.do_action(r);
                });
            },

            'click .link2recall': function() {
                this.destroy(true);
            },

            'click .link2showed': function() {
                this.destroy(true);
                this.rpc("/calendar/notify_ack");
            },
        });
    },
});

WebClient.include({
    get_next_notif: function() {
        var self = this;

        this.rpc("/calendar/notify", {}, {shadow: true})
        .done(function(result) {
            _.each(result, function(res) {
                setTimeout(function() {
                    // If notification not already displayed, we create and display it (FIXME is this check usefull?)
                    if(self.$(".eid_" + res.event_id).length === 0) {
                        self.notification_manager.display(new CalendarNotification(self.notification_manager, res.title, res.message, res.event_id));
                    }
                }, res.timer * 1000);
            });
        })
        .fail(function(err, ev) {
            if(err.code === -32098) {
                // Prevent the CrashManager to display an error
                // in case of an xhr error not due to a server error
                ev.preventDefault();
            }
        });
    },
    check_notifications: function() {
        var self = this;
        this.get_next_notif();
        this.intervalNotif = setInterval(function() {
            self.get_next_notif();
        }, 5 * 60 * 1000);
    },
    //Override the show_application of addons/web/static/src/js/chrome.js       
    show_application: function() {
        this._super();
        this.check_notifications();
    },
    //Override addons/web/static/src/js/chrome.js       
    on_logout: function() {
        this._super();
        clearInterval(this.intervalNotif);
    },
});

var Many2ManyAttendee = FieldMany2ManyTags.extend({
    tag_template: "Many2ManyAttendeeTag",
    get_render_data: function (ids) {
        return this.dataset.call('get_attendee_detail', [ids, this.getParent().datarecord.id || false])
                           .then(process_data);

        function process_data(data) {
            return _.map(data, function (d) {
                return _.object(['id', 'display_name', 'status', 'color'], d);
            });
        }
    },
});

function showCalendarInvitation(db, action, id, view, attendee_data) {
    session.session_bind(session.origin).then(function () {
        if (session.session_is_valid(db) && session.username !== "anonymous") {
            window.location.href = _.str.sprintf('/web?db=%s#id=%s&view_type=form&model=calendar.event', db, id);
        } else {
            $("body").prepend(QWeb.render('CalendarInvitation', {attendee_data: JSON.parse(attendee_data)}));
        }
    });
}

core.form_widget_registry.add('many2manyattendee', Many2ManyAttendee);

return {
    showCalendarInvitation: showCalendarInvitation,
};

});
