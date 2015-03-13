# -*- coding: utf-8 -*-

import time
import base64
import itertools
from datetime import datetime
from dateutil.relativedelta import relativedelta
from operator import itemgetter
from traceback import format_exception
from sys import exc_info
from openerp.tools.safe_eval import safe_eval as eval
import re
from openerp.addons.decimal_precision import decimal_precision as dp

from openerp import api
from openerp.report import render_report
from openerp.tools.translate import _
from openerp.exceptions import UserError
from openerp import models, fields, api, _

_intervalTypes = {
    'hours': lambda interval: relativedelta(hours=interval),
    'days': lambda interval: relativedelta(days=interval),
    'months': lambda interval: relativedelta(months=interval),
    'years': lambda interval: relativedelta(years=interval),
}

DT_FMT = '%Y-%m-%d %H:%M:%S'


class MarketingCampaign(models.Model):
    _name = "marketing.campaign"
    _description = "Marketing Campaign"

    @api.multi
    def _count_segments(self):
        res = {}
        try:
            for segments in self:
                res[segments.id] = len(segments.segment_ids)
        except:
            pass
        return res

    name = fields.Char(string='Name', required=True)
    object_id = fields.Many2one(comodel_name='ir.model', string='Resource', required=True,
                                help="Choose the resource on which you want \
this campaign to be run")
    partner_field_id = fields.Many2one(comodel_name='ir.model.fields', string='Partner Field',
                                       domain="[('model_id', '=', object_id), ('ttype', '=', 'many2one'), ('relation', '=', 'res.partner')]",
                                       help="The generated workitems will be linked to the partner related to the record. "
                                       "If the record is the partner itself leave this field empty. "
                                              "This is useful for reporting purposes, via the Campaign Analysis or Campaign Follow-up views.")
    unique_field_id = fields.Many2one(comodel_name='ir.model.fields', string='Unique Field',
                                      domain="[('model_id', '=', object_id), ('ttype', 'in', ['char','int','many2one','text','selection'])]",
                                      help='If set, this field will help segments that work in "no duplicates" mode to avoid '
                                             'selecting similar records twice. Similar records are records that have the same value for '
                                             'this unique field. For example by choosing the "email_from" field for CRM Leads you would prevent '
                                             'sending the same campaign to the same email address again. If not set, the "no duplicates" segments '
                                             "will only avoid selecting the same record again if it entered the campaign previously. "
                                             "Only easily comparable fields like textfields, integers, selections or single relationships may be used.")
    mode = fields.Selection([('test', 'Test Directly'),
                             ('test_realtime', 'Test in Realtime'),
                             ('manual', 'With Manual Confirmation'),
                             ('active', 'Normal')],
                            'Mode', required=True, default='test', help="""Test - It creates and process all the activities directly (without waiting for the delay on transitions) but does not send emails or produce reports.
Test in Realtime - It creates and processes all the activities directly but does not send emails or produce reports.
With Manual Confirmation - the campaigns runs normally, but the user has to validate all workitem manually.
Normal - the campaign runs normally and automatically sends all emails and reports (be very careful with this mode, you're live!)""")
    state = fields.Selection([('draft', 'New'),
                              ('running', 'Running'),
                              ('cancelled', 'Cancelled'),
                              ('done', 'Done')],
                             'Status', copy=False, default='draft')
    activity_ids = fields.One2many(comodel_name='marketing.campaign.activity',
                                   inverse_name='campaign_id', string='Activities')
    fixed_cost = fields.Float(
        string='Fixed Cost', help="Fixed cost for running this campaign. You may also specify variable cost and revenue on each campaign activity. Cost and Revenue statistics are included in Campaign Reporting.", digits_compute=dp.get_precision('Product Price'))
    segment_ids = fields.One2many(
        comodel_name='marketing.campaign.segment', inverse_name='campaign_id', string='Segments', readonly=False)
    segments_count = fields.Integer(
        compute='_count_segments', string='Segments')

    @api.multi
    def state_running_set(self):
        # TODO check that all subcampaigns are running
        self.ensure_one()
        if not self.activity_ids:
            raise UserError(
                _("The campaign cannot be started. There are no activities in it."))

        has_start = False
        has_signal_without_from = False

        for activity in self.activity_ids:
            if activity.start:
                has_start = True
            if activity.signal and len(activity.from_ids) == 0:
                has_signal_without_from = True

        if not has_start and not has_signal_without_from:
            raise UserError(
                _("The campaign cannot be started. It does not have any starting activity. Modify campaign's activities to mark one as the starting point."))

        return self.write({'state': 'running'})

    @api.multi
    def state_done_set(self):
        # TODO check that this campaign is not a subcampaign in running mode.
        segment_ids = self.env['marketing.campaign.segment'].search(
            [('campaign_id', 'in', self.ids), ('state', '=', 'running')])
        if segment_ids:
            raise UserError(
                _("The campaign cannot be marked as done before all segments are closed."))
        self.write({'state': 'done'})
        return True

    @api.multi
    def state_cancel_set(self):
        # TODO check that this campaign is not a subcampaign in running mode.
        self.write({'state': 'cancelled'})
        return True

    # dead code
    def signal(self, cr, uid, model, res_id, signal, run_existing=True, context=None):
        record = self.pool[model].browse(cr, uid, res_id, context)
        return self._signal(cr, uid, record, signal, run_existing, context)

    # dead code
    def _signal(self, cr, uid, record, signal, run_existing=True, context=None):
        if not signal:
            raise ValueError('Signal cannot be False.')

        Workitems = self.pool.get('marketing.campaign.workitem')
        domain = [('object_id.model', '=', record._name),
                  ('state', '=', 'running')]
        campaign_ids = self.search(cr, uid, domain, context=context)
        for campaign in self.browse(cr, uid, campaign_ids, context=context):
            for activity in campaign.activity_ids:
                if activity.signal != signal:
                    continue

                data = dict(activity_id=activity.id,
                            res_id=record.id,
                            state='todo')
                wi_domain = [(k, '=', v) for k, v in data.items()]

                wi_ids = Workitems.search(cr, uid, wi_domain, context=context)
                if wi_ids:
                    if not run_existing:
                        continue
                else:
                    partner = self._get_partner_for(campaign, record)
                    if partner:
                        data['partner_id'] = partner.id
                    wi_id = Workitems.create(cr, uid, data, context=context)
                    wi_ids = [wi_id]
                Workitems.process(cr, uid, wi_ids, context=context)
        return True

    def _get_partner_for(self, campaign, record):
        partner_field = campaign.partner_field_id.name
        if partner_field:
            return getattr(record, partner_field)
        elif campaign.object_id.model == 'res.partner':
            return record
        return None

    # prevent duplication until the server properly duplicates several levels
    # of nested o2m
    @api.multi
    def copy(self, *args):
        raise UserError(_('Duplicating campaigns is not supported.'))

    @api.one
    def _find_duplicate_workitems(self, record, campaign_rec):
        """Finds possible duplicates workitems for a record in this campaign, based on a uniqueness
           field.

           :param record: browse_record to find duplicates workitems for.
           :param campaign_rec: browse_record of campaign
        """
        Workitems = self.env['marketing.campaign.workitem']
        duplicate_workitem_domain = [('res_id', '=', record.id),
                                     ('campaign_id', '=', campaign_rec.id)]
        unique_field = campaign_rec.unique_field_id
        if unique_field:
            unique_value = getattr(record, unique_field.name, None)
            if unique_value:
                if unique_field.ttype == 'many2one':
                    unique_value = unique_value.id
                similar_res_ids = self.env[campaign_rec.object_id.model].search(
                    [(unique_field.name, '=', unique_value)])
                if similar_res_ids:
                    duplicate_workitem_domain = [('res_id', 'in', similar_res_ids),
                                                 ('campaign_id', '=', campaign_rec.id)]
        return Workitems.search(duplicate_workitem_domain)


class MarketingCampaignSegment(models.Model):
    _name = "marketing.campaign.segment"
    _description = "Campaign Segment"
    _order = "name"

    @api.multi
    def _get_next_sync(self):
        # next auto sync date is same for all segments
        sync_job = self.env['ir.model.data'].get_object(
            'marketing_campaign', 'ir_cron_marketing_campaign_every_day')
        for record in self:
            record.date_next_sync = sync_job.nextcall or False

    name = fields.Char(string='Name', required=True)
    campaign_id = fields.Many2one(
        comodel_name='marketing.campaign', string='Campaign', required=True, select=1, ondelete="cascade")
    object_id = fields.Many2one(
        related='campaign_id.object_id', string='Resource')
    ir_filter_id = fields.Many2one(comodel_name='ir.filters', string='Filter', ondelete="restrict",
                                   help="Filter to select the matching resource records that belong to this segment. "
                                   "New filters can be created and saved using the advanced search on the list view of the Resource. "
                                   "If no filter is set, all records are selected without filtering. "
                                   "The synchronization mode may also add a criterion to the filter.")
    sync_last_date = fields.Datetime(
        string='Last Synchronization', help="Date on which this segment was synchronized last time (automatically or manually)")
    sync_mode = fields.Selection([('create_date', 'Only records created after last sync'),
                                  ('write_date',
                                   'Only records modified after last sync (no duplicates)'),
                                  ('all', 'All records (no duplicates)')],
                                 string='Synchronization mode', default='create_date', help="Determines an additional criterion to add to the filter when selecting new records to inject in the campaign. "
                                 '"No duplicates" prevents selecting records which have already entered the campaign previously.'
                                 'If the campaign has a "unique field" set, "no duplicates" will also prevent selecting records which have '
                                 'the same value for the unique field as other records that already entered the campaign.')
    state = fields.Selection([('draft', 'New'),
                              ('cancelled', 'Cancelled'),
                              ('running', 'Running'),
                              ('done', 'Done')],
                             'Status', copy=False, default='draft')
    date_run = fields.Datetime(
        string='Launch Date', help="Initial start date of this segment.")
    date_done = fields.Datetime(
        string='End Date', help="Date this segment was last closed or cancelled.")
    date_next_sync = fields.Datetime(compute='_get_next_sync', string='Next Synchronization',
                                     help="Next time the synchronization job is scheduled to run automatically")

    @api.multi
    def _check_model(self):
        for obj in self:
            if not obj.ir_filter_id:
                return True
            if obj.campaign_id.object_id.model != obj.ir_filter_id.model_id:
                return False
        return True

    _constraints = [
        (_check_model, 'Model of filter must be same as resource model of Campaign ', [
         'ir_filter_id,campaign_id']),
    ]

    @api.one
    def onchange_campaign_id(self, campaign_id):
        res = {'domain': {'ir_filter_id': []}}
        campaign_pool = self.env['marketing.campaign']
        if campaign_id:
            campaign = campaign_pool.browse(campaign_id)
            model_name = self.env['ir.model'].read(
                [campaign.object_id.id], ['model'])
            if model_name:
                mod_name = model_name[0]['model']
                res['domain'] = {'ir_filter_id': [('model_id', '=', mod_name)]}
        else:
            res['value'] = {'ir_filter_id': False}
        return res

    @api.multi
    def state_running_set(self):
        segment = self
        vals = {'state': 'running'}
        if not segment.date_run:
            vals['date_run'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self.write(vals)
        return True

    @api.multi
    def state_done_set(self):
        wi_ids = self.env['marketing.campaign.workitem'].search(
            [('state', '=', 'todo'), ('segment_id', 'in', self.ids)])
        wi_ids.env['marketing.campaign.workitem'].write({'state': 'cancelled'})
        self.write(
            {'state': 'done', 'date_done': time.strftime('%Y-%m-%d %H:%M:%S')})
        return True

    @api.multi
    def state_cancel_set(self):
        wi_ids = self.env['marketing.campaign.workitem'].search(
            [('state', '=', 'todo'), ('segment_id', 'in', self.ids)])
        wi_ids.env['marketing.campaign.workitem'].write({'state': 'cancelled'})
        self.write(
            {'state': 'cancelled', 'date_done': time.strftime('%Y-%m-%d %H:%M:%S')})
        return True

    @api.multi
    def synchroniz(self, *args):
        self.process_segment()
        return True

    @api.multi
    def process_segment(self):
        Workitems = self.env['marketing.campaign.workitem']
        Campaigns = self.env['marketing.campaign']
        if not self:
            self = self.search([('state', '=', 'running')])

        action_date = time.strftime('%Y-%m-%d %H:%M:%S')
        campaigns = set()
        for segment in self:
            if segment.campaign_id.state != 'running':
                continue

            campaigns.add(segment.campaign_id.id)
            act_ids = self.env['marketing.campaign.activity'].search(
                [('start', '=', True), ('campaign_id', '=', segment.campaign_id.id)])
            model_obj = self.env[segment.object_id.model]
            criteria = []
            if segment.sync_last_date and segment.sync_mode != 'all':
                criteria += [(segment.sync_mode, '>', segment.sync_last_date)]
            if segment.ir_filter_id:
                criteria += eval(segment.ir_filter_id.domain)
            object_ids = model_obj.search(criteria)

            # XXX TODO: rewrite this loop more efficiently without doing 1
            # search per record!
            for record in object_ids:
                # avoid duplicate workitem for the same resource
                if segment.sync_mode in ('write_date', 'all'):
                    if Campaigns._find_duplicate_workitems(record, segment.campaign_id):
                        continue

                wi_vals = {
                    'segment_id': segment.id,
                    'date': action_date,
                    'state': 'todo',
                    'res_id': record.id
                }

                partner = self.env['marketing.campaign']._get_partner_for(
                    segment.campaign_id, record)
                if partner:
                    wi_vals['partner_id'] = partner.id

                for act_id in act_ids:
                    wi_vals['activity_id'] = act_id.id
                    Workitems.create(wi_vals)

            self.write({'sync_last_date': action_date})
        Workitems.process_all(list(campaigns))
        return True


class MarketingCampaignActivity(models.Model):
    _name = "marketing.campaign.activity"
    _order = "name"
    _description = "Campaign Activity"

    _action_types = [
        ('email', 'Email'),
        ('report', 'Report'),
        ('action', 'Custom Action'),
        # TODO implement the subcampaigns.
        # TODO implement the subcampaign out. disallow out transitions from
        # subcampaign activities ?
        #('subcampaign', 'Sub-Campaign'),
    ]

    name = fields.Char(string='Name', required=True)
    campaign_id = fields.Many2one(comodel_name='marketing.campaign', string='Campaign',
                                  required=True, ondelete='cascade', select=1)
    object_id = fields.Many2one(
        related='campaign_id.object_id', string='Object', readonly=True)
    start = fields.Boolean(
        string='Start', help="This activity is launched when the campaign starts.", select=True)
    condition = fields.Text(string='Condition', size=256, required=True, default='True',
                            help="Python expression to decide whether the activity can be executed, otherwise it will be deleted or cancelled."
                            "The expression may use the following [browsable] variables:\n"
                            "   - activity: the campaign activity\n"
                            "   - workitem: the campaign workitem\n"
                            "   - resource: the resource object this campaign item represents\n"
                            "   - transitions: list of campaign transitions outgoing from this activity\n"
                            "...- re: Python regular expression module")
    type = fields.Selection(selection=_action_types, string='Type', required=True, default='email',
                            help="""The type of action to execute when an item enters this activity, such as:
- Email: send an email using a predefined email template
- Report: print an existing Report defined on the resource item and save it into a specific directory
- Custom Action: execute a predefined action, e.g. to modify the fields of the resource record
""")
    email_template_id = fields.Many2one(comodel_name='mail.template', string='Email Template',
                                        help='The email to send when this activity is activated')
    report_id = fields.Many2one(comodel_name='ir.actions.report.xml', string='Report',
                                help='The report to generate when this activity is activated', )
    report_directory_id = fields.Many2one(comodel_name='document.directory', string='Directory',
                                          help="This folder is used to store the generated reports")
    server_action_id = fields.Many2one(comodel_name='ir.actions.server', string='Action',
                                       help="The action to perform when this activity is activated")
    to_ids = fields.One2many(comodel_name='marketing.campaign.transition',
                             inverse_name='activity_from_id',
                             string='Next Activities')
    from_ids = fields.One2many(comodel_name='marketing.campaign.transition',
                               inverse_name='activity_to_id',
                               string='Previous Activities')
    variable_cost = fields.Float(string='Variable Cost', help="Set a variable cost if you consider that every campaign item that has reached this point has entailed a certain cost. You can get cost statistics in the Reporting section",
                                 digits_compute=dp.get_precision('Product Price'))
    revenue = fields.Float(string='Revenue', help="Set an expected revenue if you consider that every campaign item that has reached this point has generated a certain revenue. You can get revenue statistics in the Reporting section",
                           digits_compute=dp.get_precision('Account'))
    signal = fields.Char(string='Signal',
                         help='An activity with a signal can be called programmatically. Be careful, the workitem is always created when a signal is sent')
    keep_if_condition_not_met = fields.Boolean(string="Don't Delete Workitems",
                                               help="By activating this option, workitems that aren't executed because the condition is not met are marked as cancelled instead of being deleted.")

    @api.model
    def search(self, args, offset=0, limit=None, order=None, count=False):
        segment_id = self.env.context.get('segment_id')
        if segment_id:
            Segment = self.env['marketing.campaign.segment'].browse(segment_id)
            return Segment.campaign_id.activity_ids.ids
        return super(MarketingCampaignActivity, self).search(args=args, offset=offset, limit=limit, order=order, count=count)

    # dead code
    def _process_wi_report(self, cr, uid, activity, workitem, context=None):
        report_data, format = render_report(
            cr, uid, [], activity.report_id.report_name, {}, context=context)
        attach_vals = {
            'name': '%s_%s_%s' % (activity.report_id.report_name,
                                  activity.name, workitem.partner_id.name),
            'datas_fname': '%s.%s' % (activity.report_id.report_name,
                                      activity.report_id.report_type),
            'parent_id': activity.report_directory_id.id,
            'datas': base64.encodestring(report_data),
            'file_type': format
        }
        self.pool.get('ir.attachment').create(cr, uid, attach_vals)
        return True

    @api.multi
    def _process_wi_email(self, activity, workitem):
        return activity.email_template_id.send_mail(workitem.res_id)[0]

    # dead code
    def _process_wi_action(self, cr, uid, activity, workitem, context=None):
        if context is None:
            context = {}
        server_obj = self.pool.get('ir.actions.server')

        action_context = dict(context,
                              active_id=workitem.res_id,
                              active_ids=[workitem.res_id],
                              active_model=workitem.object_id.model,
                              workitem=workitem)
        server_obj.run(cr, uid, [activity.server_action_id.id],
                       context=action_context)
        return True

    @api.multi
    def process(self, act_id, wi_id):
        activity = self.browse(act_id)
        method = '_process_wi_%s' % (activity.type,)
        action = getattr(self, method, None)
        if not action:
            raise NotImplementedError(
                'Method %r is not implemented on %r object.' % (method, self))

        workitem_obj = self.env['marketing.campaign.workitem']
        workitem = workitem_obj.browse(wi_id)
        return action(activity, workitem)


class MarketingCampaignTransition(models.Model):
    _name = "marketing.campaign.transition"
    _description = "Campaign Transition"

    _interval_units = [
        ('hours', 'Hour(s)'),
        ('days', 'Day(s)'),
        ('months', 'Month(s)'),
        ('years', 'Year(s)'),
    ]

    @api.multi
    def _get_name(self, fn, args):
        # name formatters that depend on trigger
        formatters = {
            'auto': _('Automatic transition'),
            'time': _('After %(interval_nbr)d %(interval_type)s'),
            'cosmetic': _('Cosmetic'),
        }
        # get the translations of the values of selection field 'interval_type'
        fields = self.fields_get(['interval_type'])
        interval_type_selection = dict(fields['interval_type']['selection'])

        result = dict.fromkeys(self.ids, False)
        for trans in self:
            values = {
                'interval_nbr': trans.interval_nbr,
                'interval_type': interval_type_selection.get(trans.interval_type, ''),
            }
            result[trans.id] = formatters[trans.trigger] % values
        return result

    @api.multi
    def _delta(self):
        assert len(self.ids) == 1
        transition = self
        if transition.trigger != 'time':
            raise ValueError('Delta is only relevant for timed transition.')
        return relativedelta(**{str(transition.interval_type): transition.interval_nbr})

    name = fields.Char(compute=_get_name, string='Name', size=128)
    activity_from_id = fields.Many2one(
        comodel_name='marketing.campaign.activity', string='Previous Activity', select=1, required=True, ondelete="cascade")
    activity_to_id = fields.Many2one(
        comodel_name='marketing.campaign.activity', string='Next Activity', required=True, ondelete="cascade")
    interval_nbr = fields.Integer(
        string='Interval Value', required=True, default=1)
    interval_type = fields.Selection(selection=_interval_units, string='Interval Unit',
                                     required=True, default='days')
    trigger = fields.Selection([('auto', 'Automatic'),
                                ('time', 'Time'),
                                # fake plastic transition
                                ('cosmetic', 'Cosmetic'),
                                ],
                               string='Trigger', required=True, default='time',
                               help="How is the destination workitem triggered")

    @api.multi
    def _check_campaign(self):
        for obj in self:
            if obj.activity_from_id.campaign_id != obj.activity_to_id.campaign_id:
                return False
        return True

    _constraints = [
        (_check_campaign, 'The To/From Activity of transition must be of the same Campaign ',
         ['activity_from_id,activity_to_id']),
    ]

    _sql_constraints = [
        ('interval_positive', 'CHECK(interval_nbr >= 0)',
         'The interval must be positive or zero')
    ]


class MarketingCampaignWorkitem(models.Model):
    _name = "marketing.campaign.workitem"
    _description = "Campaign Workitem"

    @api.multi
    def _res_name_get(self):
        for wi in self:
            if not wi.res_id:
                continue
            proxy = self.env[wi.object_id.model].browse(wi.res_id)
            if not proxy.exists():
                continue
            ng = proxy.name_get()
            if ng:
                wi.res_name = ng[0][1]
            else:
                wi.res_name = '/'

    def _resource_search(self, operator, val):
        """Returns id of workitem whose resource_name matches with the given name"""
        print 'operator, val=================', operator, val
        if not len(args):
            return []

        condition_name = None
        # for domain_item in args:
        # we only use the first domain criterion and ignore all the rest
        # including operators
        if args:
            condition_name = [None, domain_item[1], domain_item[2]]
            # break

        assert condition_name, "Invalid search domain for marketing_campaign_workitem.res_name. It should use 'res_name'"

        self.cr.execute("""select w.id, w.res_id, m.model  \
                                from marketing_campaign_workitem w \
                                    left join marketing_campaign_activity a on (a.id=w.activity_id)\
                                    left join marketing_campaign c on (c.id=a.campaign_id)\
                                    left join ir_model m on (m.id=c.object_id)
                                    """)
        res = self.cr.fetchall()
        workitem_map = {}
        matching_workitems = []
        for id, res_id, model in res:
            workitem_map.setdefault(model, {}).setdefault(
                res_id, set()).add(id)
        for model, id_map in workitem_map.iteritems():
            model_pool = self.env[model]
            condition_name[0] = model_pool._rec_name
            condition = [('id', 'in', id_map.keys()), condition_name]
            for res_id in model_pool.search(condition):
                matching_workitems.extend(id_map[res_id])
        return [('id', 'in', list(set(matching_workitems)))]

    segment_id = fields.Many2one(
        comodel_name='marketing.campaign.segment', string='Segment', readonly=True)
    activity_id = fields.Many2one(
        comodel_name='marketing.campaign.activity', string='Activity', readonly=True)
    campaign_id = fields.Many2one(
        related='activity_id.campaign_id', string='Campaign', readonly=True, store=True)
    object_id = fields.Many2one(
        related='activity_id.campaign_id.object_id', string='Resource', select=1, readonly=True, store=True)
    res_id = fields.Integer(string='Resource ID', select=1, readonly=True)
    res_name = fields.Char(
        compute='_res_name_get', string='Resource Name', search='_resource_search', size=64)
    date = fields.Datetime(
        string='Execution Date', help='If date is not set, this workitem has to be run manually', readonly=True, default=False)
    partner_id = fields.Many2one(
        comodel_name='res.partner', string='Partner', select=1, readonly=True)
    state = fields.Selection([('todo', 'To Do'),
                              ('cancelled', 'Cancelled'),
                              ('exception', 'Exception'),
                              ('done', 'Done'),
                              ], default='todo', string='Status', readonly=True, copy=False)
    error_msg = fields.Text(string='Error Message', readonly=True)

    @api.multi
    def button_draft(self):
        for wi in self:
            if wi.state in ('exception', 'cancelled'):
                wi.write({'state': 'todo'})
        return True

    @api.multi
    def button_cancel(self):
        for wi in self:
            if wi.state in ('todo', 'exception'):
                wi.write({'state': 'cancelled'})
        return True

    @api.multi
    def _process_one(self):
        if self.state != 'todo':
            return False

        activity = self.activity_id
        proxy = self.env[self.object_id.model]
        object_id = proxy.browse(self.res_id)

        eval_context = {
            'activity': activity,
            'workitem': self,
            'object': object_id,
            'resource': object_id,
            'transitions': activity.to_ids,
            're': re,
        }
        try:
            condition = activity.condition
            campaign_mode = self.campaign_id.mode
            if condition:
                if not eval(condition, eval_context):
                    if activity.keep_if_condition_not_met:
                        self.write({'state': 'cancelled'})
                    else:
                        self.unlink()
                    return
            result = True
            if campaign_mode in ('manual', 'active'):
                Activities = self.env['marketing.campaign.activity']
                result = Activities.process(activity.id, self.id)

            values = dict(state='done')
            if not self.date:
                values['date'] = datetime.now().strftime(DT_FMT)
            self.write(values)

            if result:
                # process _chain
                self.refresh()       # reload
                date = datetime.strptime(self.date, DT_FMT)

                for transition in activity.to_ids:
                    if transition.trigger == 'cosmetic':
                        continue
                    launch_date = False
                    if transition.trigger == 'auto':
                        launch_date = date
                    elif transition.trigger == 'time':
                        launch_date = date + transition._delta()

                    if launch_date:
                        launch_date = launch_date.strftime(DT_FMT)
                    values = {
                        'date': launch_date,
                        'segment_id': self.segment_id.id,
                        'activity_id': transition.activity_to_id.id,
                        'partner_id': self.partner_id.id,
                        'res_id': self.res_id,
                        'state': 'todo',
                    }
                    wi_id = self.create(values).id

                    # Now, depending on the trigger and the campaign mode
                    # we know whether we must run the newly created workitem.
                    #
                    # rows = transition trigger \ colums = campaign mode
                    #
                    #           test    test_realtime     manual      normal (active)
                    # time       Y            N             N           N
                    # cosmetic   N            N             N           N
                    # auto       Y            Y             N           Y
                    #

                    run = (transition.trigger == 'auto'
                           and campaign_mode != 'manual') \
                        or (transition.trigger == 'time'
                            and campaign_mode == 'test')
                    if run:
                        new_wi = self.browse(wi_id)
                        new_wi._process_one()
        except Exception:
            tb = "".join(format_exception(*exc_info()))
            self.write({'state': 'exception', 'error_msg': tb})

    @api.multi
    def process(self):
        for wi in self:
            wi._process_one()
        return True

    @api.multi
    def process_all(self, camp_ids=None):
        camp_obj = self.env['marketing.campaign']
        if camp_ids is None:
            camp_ids = camp_obj.search([('state', '=', 'running')])
        for camp in camp_obj.browse(camp_ids):
            if camp.mode == 'manual':
                # manual states are not processed automatically
                continue
            while True:
                domain = [
                    ('campaign_id', '=', camp.id), ('state', '=', 'todo'), ('date', '!=', False)]
                if camp.mode in ('test_realtime', 'active'):
                    domain += [('date', '<=',
                                time.strftime('%Y-%m-%d %H:%M:%S'))]
                workitem_ids = self.search(domain)
                if not workitem_ids.ids:
                    break
                workitem_ids.process()
        return True

    @api.multi
    def preview(self, *args):
        res = {}
        wi_obj = self
        if wi_obj.activity_id.type == 'email':
            view_id = self.env['ir.model.data'].get_object_reference(
                'mail', 'email_template_preview_form')
            res = {
                'name': _('Email Preview'),
                'view_type': 'form',
                'view_mode': 'form,tree',
                'res_model': 'email_template.preview',
                'view_id': False,
                'context': self.env.context,
                'views': [(view_id and view_id[1] or 0, 'form')],
                'type': 'ir.actions.act_window',
                'target': 'new',
                'nodestroy': True,
                'context': "{'template_id':%d,'default_res_id':%d}" %
                (wi_obj.activity_id.email_template_id.id,
                 wi_obj.res_id)
            }

        elif wi_obj.activity_id.type == 'report':
            datas = {
                'ids': [wi_obj.res_id],
                'model': wi_obj.object_id.model
            }
            res = {
                'type': 'ir.actions.report.xml',
                'report_name': wi_obj.activity_id.report_id.report_name,
                'datas': datas,
            }
        else:
            raise UserError(
                _('The current step for this item has no email or report to preview.'))
        return res


class MailTemplate(models.Model):
    _inherit = "mail.template"

    model_id = fields.Many2one(
        default=lambda self: self.env.context.get('object_id', False))

    # TODO: add constraint to prevent disabling / disapproving an email
    # account used in a running campaign


class ReportXml(models.Model):
    _inherit = 'ir.actions.report.xml'

    @api.model
    def search(self, args, offset=0, limit=None, order=None, count=False):
        object_id = self.env.context.get('object_id')
        if object_id:
            model = self.env['ir.model'].browse(object_id).model
            args.append(('model', '=', model))
        return super(ReportXml, self).search(args=args, offset=offset, limit=limit, order=order, count=count)
