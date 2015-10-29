# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
import datetime
from dateutil.relativedelta import relativedelta

from odoo import tools, _, models, api, fields
from odoo.exceptions import UserError


class FleetVehicleCost(models.Model):
    _name = 'fleet.vehicle.cost'
    _description = 'Cost related to a vehicle'
    _order = 'date desc, vehicle_id asc'

    name = fields.Char(related='vehicle_id.name', store=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', required=True,
                                 help='Vehicle concerned by this log')
    cost_subtype_id = fields.Many2one('fleet.service.type', string='Type',
                                      help='Cost type purchased with this cost')
    amount = fields.Float(string='Total Price')
    cost_type = fields.Selection([('contract', 'Contract'), ('services', 'Services'),
                                  ('fuel', 'Fuel'), ('other', 'Other')],
                                 string='Category of the cost', help='For internal purpose only',
                                 required=True, default='other')
    parent_id = fields.Many2one('fleet.vehicle.cost', string='Parent', help='Parent cost to this current cost')
    cost_ids = fields.One2many('fleet.vehicle.cost', 'parent_id', string='Included Services')
    odometer_id = fields.Many2one('fleet.vehicle.odometer', string='Odometer',
                                  help='Odometer measure of the vehicle at the moment of this log')
    odometer = fields.Float(compute='_compute_odometer', inverse='_inverse_odometer', string='Odometer Value',
                            help='Odometer measure of the vehicle at the moment of this log', store=True)
    odometer_unit = fields.Selection(related='vehicle_id.odometer_unit', string="Unit", readonly=True)
    date = fields.Date(help='Date when the cost has been executed', default=fields.Date.context_today)
    contract_id = fields.Many2one('fleet.vehicle.log.contract', string='Contract',
                                  help='Contract attached to this cost')
    auto_generated = fields.Boolean('Automatically Generated', readonly=True)

    @api.one
    @api.depends('odometer_id')
    def _compute_odometer(self):
        if self.odometer_id:
            self.odometer = self.odometer_id.value

    @api.one
    def _inverse_odometer(self):
        if not self.odometer:
            raise UserError(_('Emptying the odometer value of a vehicle is not allowed.'))
        odometer = self.env['fleet.vehicle.odometer'].create({
            'value': self.odometer,
            'date': self.date or fields.Date.context_today(self),
            'vehicle_id': self.vehicle_id.id})
        self.odometer_id = odometer.id

    @api.model
    def create(self, values):
        # make sure that the data are consistent with values of parent and contract records given
        if values.get('parent_id'):
            parent = self.browse(values['parent_id'])
            values['vehicle_id'] = parent.vehicle_id.id
            values['date'] = parent.date
            values['cost_type'] = parent.cost_type
        if values.get('contract_id'):
            contract = self.env['fleet.vehicle.log.contract'].browse(values['contract_id'])
            values['vehicle_id'] = contract.vehicle_id.id
            values['cost_subtype_id'] = contract.cost_subtype_id.id
            values['cost_type'] = contract.cost_type
        if values.get('odometer') == 0.0:
            # if received value for odometer is 0, then remove it from the data as it would result to the creation of a
            # odometer log with 0, which is to be avoided
            del(values['odometer'])
        return super(FleetVehicleCost, self).create(values)


class FleetVehicleTag(models.Model):
    _name = 'fleet.vehicle.tag'

    name = fields.Char(required=True)
    color = fields.Integer('Color Index')

    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Tag name already exists !"),
    ]


class FleetVehicleState(models.Model):
    _name = 'fleet.vehicle.state'
    _order = 'sequence asc'

    name = fields.Char(required=True)
    sequence = fields.Integer(help="Used to order the note stages")

    _sql_constraints = [('fleet_state_name_unique', 'unique(name)', 'State name already exists')]


class FleetVehicleModel(models.Model):

    _name = 'fleet.vehicle.model'
    _description = 'Model of a vehicle'
    _order = 'name asc'

    name = fields.Char('Model name', required=True)
    brand_id = fields.Many2one('fleet.vehicle.model.brand', 'Make', required=True, help='Make of the vehicle')
    vendors = fields.Many2many('res.partner', 'fleet_vehicle_model_vendors', 'model_id', 'partner_id', string='Vendors')
    image = fields.Binary(related='brand_id.image', string="Logo")
    image_medium = fields.Binary(related='brand_id.image_medium', string="Logo (medium)")
    image_small = fields.Binary(related='brand_id.image_small', string="Logo (small)")

    @api.multi
    def name_get(self):
        return self.mapped(lambda m: (m.id, '/'.join([m.brand_id.name, m.name])))


class FleetVehicleModelBrand(models.Model):
    _name = 'fleet.vehicle.model.brand'
    _description = 'Brand model of the vehicle'
    _order = 'name asc'

    name = fields.Char('Make', required=True)

    image = fields.Binary("Logo", attachment=True,
                          help="This field holds the image used as logo for the brand, limited to 1024x1024px.")
    image_medium = fields.Binary("Medium-sized image",
                                 compute='_compute_images', inverse='_inverse_image_medium', store=True, attachment=True,
                                 help="Medium-sized logo of the brand. It is automatically "
                                      "resized as a 128x128px image, with aspect ratio preserved. "
                                      "Use this field in form views or some kanban views.")
    image_small = fields.Binary("Small-sized image",
                                compute='_compute_images', inverse='_inverse_image_small', store=True, attachment=True,
                                help="Small-sized logo of the brand. It is automatically "
                                     "resized as a 64x64px image, with aspect ratio preserved. "
                                     "Use this field anywhere a small image is required.")

    @api.depends('image')
    def _compute_images(self):
        for rec in self:
            rec.image_medium = tools.image_resize_image_medium(rec.image)
            rec.image_small = tools.image_resize_image_small(rec.image)

    def _inverse_image_medium(self):
        for rec in self:
            rec.image = tools.image_resize_image_big(rec.image_medium)

    def _inverse_image_small(self):
        for rec in self:
            rec.image = tools.image_resize_image_big(rec.image_small)


class FleetVehicle(models.Model):

    _name = 'fleet.vehicle'
    _inherit = 'mail.thread'
    _description = 'Information on a vehicle'
    _order = 'license_plate asc'

    @api.model
    def _get_default_state(self):
        return self.env.ref('fleet.vehicle_state_active', raise_if_not_found=False)

    name = fields.Char(compute='_compute_vehicle_name', store=True)
    company_id = fields.Many2one('res.company', string='Company')
    license_plate = fields.Char(required=True, track_visibility='onchange',
                                help='License plate number of the vehicle (ie: plate number for a car)')
    vin_sn = fields.Char(string='Chassis Number', help='Unique number written on the vehicle motor (VIN/SN number)',
                         copy=False)
    driver_id = fields.Many2one('res.partner', string='Driver', track_visibility='onchange',
                                help='Driver of the vehicle')
    model_id = fields.Many2one('fleet.vehicle.model', string='Model', required=True, track_visibility='onchange',
                               help='Model of the vehicle')
    log_fuel = fields.One2many('fleet.vehicle.log.fuel', 'vehicle_id', string='Fuel Logs')
    log_services_ids = fields.One2many('fleet.vehicle.log.services', 'vehicle_id', string='Services Logs')
    log_contracts_ids = fields.One2many('fleet.vehicle.log.contract', 'vehicle_id', string='Contracts')
    cost_count = fields.Integer(compute='_compute_count_vehiclecost', string="Costs")
    contract_count = fields.Integer(compute='_compute_count_logcontract', string='Contracts')
    service_count = fields.Integer(compute='_compute_count_logservice', string='Services')
    fuel_logs_count = fields.Integer(compute='_compute_count_logfuel', string='Fuel Logs')
    odometer_count = fields.Integer(compute='_compute_count_odometer', string='Odometer')
    acquisition_date = fields.Date(help='Date when the vehicle has been bought')
    color = fields.Char(help='Color of the vehicle')
    state_id = fields.Many2one('fleet.vehicle.state', string='Stage', track_visibility='onchange',
                               help='Current state of the vehicle', default=_get_default_state)
    location = fields.Char(help='Location of the vehicle (garage, ...)')
    seats = fields.Integer(string='Seats Number', help='Number of seats of the vehicle')
    doors = fields.Integer(string='Doors Number', help='Number of doors of the vehicle', default=5)
    tag_ids = fields.Many2many('fleet.vehicle.tag', 'fleet_vehicle_vehicle_tag_rel', 'vehicle_tag_id', 'tag_id',
                               string='Tags', copy=False)
    odometer = fields.Float(compute='_compute_odometer', inverse='_inverse_odometer', string='Last Odometer',
                            help='Odometer measure of the vehicle at the moment of this log')
    odometer_unit = fields.Selection([('kilometers', 'Kilometers'), ('miles', 'Miles')],
                                     help='Unit of the odometer',
                                     required=True, default='kilometers')
    transmission = fields.Selection([('manual', 'Manual'), ('automatic', 'Automatic')],
                                    help='Transmission Used by the vehicle')
    fuel_type = fields.Selection([('gasoline', 'Gasoline'), ('diesel', 'Diesel'),
                                  ('electric', 'Electric'), ('hybrid', 'Hybrid')],
                                 help='Fuel Used by the vehicle')
    horsepower = fields.Integer()
    horsepower_tax = fields.Float(string='Horsepower Taxation')
    power = fields.Integer(help='Power in kW of the vehicle')
    co2 = fields.Float(string='CO2 Emissions', help='CO2 emissions of the vehicle')
    image = fields.Binary(related='model_id.brand_id.image', string="Logo")
    image_medium = fields.Binary(related='model_id.brand_id.image_medium', string="Logo (medium)")
    image_small = fields.Binary(related='model_id.brand_id.image_small', string="Logo (small)")
    contract_renewal_due_soon = fields.Boolean(compute='_compute_contract_reminder',
                                               search='_search_contract_renewal_due_soon',
                                               string='Has Contracts to renew')
    contract_renewal_overdue = fields.Boolean(compute='_compute_contract_reminder',
                                              search='_search_overdue_contract_reminder',
                                              string='Has Contracts Overdue')
    contract_renewal_name = fields.Text(compute='_compute_contract_reminder', string='Name of contract to renew soon')
    car_value = fields.Float(help='Value of the bought vehicle')

    @api.one
    @api.depends('license_plate')
    def _compute_vehicle_name(self):
        self.name = ('%s' + ' / ' + '%s' + ' / ' + '%s') % (self.model_id.brand_id.name, self.model_id.name, self.license_plate)

    @api.multi
    def _compute_count_odometer(self):
        odometer_count = self.env['fleet.vehicle.odometer'].read_group([('vehicle_id', 'in', self.ids)], fields=['vehicle_id'], groupby=['vehicle_id'])
        vehicle_dict = dict((record['vehicle_id'][0], record['vehicle_id_count']) for record in odometer_count)
        for vehicle in self:
            vehicle.odometer_count = vehicle_dict.get(vehicle.id)

    @api.one
    def _compute_odometer(self):
        vehicle_odometer = self.env['fleet.vehicle.odometer'].search([('vehicle_id', '=', self.id)], limit=1, order='value desc')
        if vehicle_odometer:
            self.odometer = vehicle_odometer.value

    @api.one
    def _inverse_odometer(self):
        if self.odometer:
            self.env['fleet.vehicle.odometer'].create({'value': self.odometer,
                                                       'date': fields.Date.context_today(self),
                                                       'vehicle_id': self.id
                                                       })

    @api.model
    def _search_overdue_contract_reminder(self, operator, value):
        if not (operator in ('=', '!=', '<>') and value in (True, False)):
            raise UserError(_("Operation not supported"))
        if (operator == '=' and value is True) or (operator in ('<>', '!=') and value is False):
            search_operator = 'in'
        else:
            search_operator = 'not in'
        today = fields.Date.context_today(self)
        overdue_contracts = self.env['fleet.vehicle.log.contract'].search([('expiration_date', '<', today), ('state', 'in', ('open', 'toclose'))])
        overdue_contract_vehicle_ids = [contract.vehicle_id.id for contract in overdue_contracts]
        return [('id', search_operator, overdue_contract_vehicle_ids)]

    @api.model
    def _search_contract_renewal_due_soon(self, operator, value):
        if not (operator in ('=', '!=', '<>') and value in (True, False)):
            raise UserError(_("Operation not supported"))
        if (operator == '=' and value is True) or (operator in ('<>', '!=') and value is False):
            search_operator = 'in'
        else:
            search_operator = 'not in'
        today = fields.Date.context_today(self)
        datetime_today = fields.Datetime.from_string(today)
        limit_date = fields.Date.to_string(datetime_today + relativedelta(days=+15))
        renewal_contracts = self.env['fleet.vehicle.log.contract'].search([('expiration_date', '>', today),
                                                                           ('expiration_date', '<', limit_date), ('state', 'in', ('open', 'toclose'))])
        renewal_contract_vehicle = [contract.vehicle_id.id for contract in renewal_contracts]
        return [('id', search_operator, renewal_contract_vehicle)]

    @api.multi
    def _compute_contract_reminder(self):
        current_date = fields.Datetime.from_string(fields.Date.context_today(self))

        for vehicle in self:
            max_due_time = current_date + datetime.timedelta(days=15)
            contract = self.env['fleet.vehicle.log.contract'].search(['&', '&', ('state', 'in', ('open', 'toclose')),
                                                                                ('vehicle_id', '=', vehicle.id),
                                                                                ('expiration_date', '<', fields.Datetime.to_string(max_due_time))],
                                                                     order='expiration_date asc', limit=1)
            if contract:
                due_time_contract = fields.Datetime.from_string(contract.expiration_date)
                vehicle.contract_renewal_name = contract.cost_subtype_id.name
                diff_time = (due_time_contract - current_date).days
                if diff_time < 0:
                    vehicle.contract_renewal_overdue = True
                else:
                    vehicle.contract_renewal_due_soon = True
            else:
                vehicle.contract_renewal_overdue = False
                vehicle.contract_renewal_due_soon = False
                vehicle.contract_renewal_name = ''

    @api.multi
    def _compute_count_logfuel(self):
        fuel_logs_count = self.env['fleet.vehicle.log.fuel'].read_group([('vehicle_id', 'in', self.ids)], fields=['vehicle_id'], groupby=['vehicle_id'])
        vehicle_dict = dict((record['vehicle_id'][0], record['vehicle_id_count']) for record in fuel_logs_count)
        for vehicle in self:
            vehicle.fuel_logs_count = vehicle_dict.get(vehicle.id)

    @api.multi
    def _compute_count_logservice(self):
        service_count = self.env['fleet.vehicle.log.services'].read_group([('vehicle_id', 'in', self.ids)], fields=['vehicle_id'], groupby=['vehicle_id'])
        vehicle_dict = dict((record['vehicle_id'][0], record['vehicle_id_count']) for record in service_count)
        for vehicle in self:
            vehicle.service_count = vehicle_dict.get(vehicle.id)

    @api.multi
    def _compute_count_logcontract(self):
        contract_count = self.env['fleet.vehicle.log.contract'].read_group([('vehicle_id', 'in', self.ids)], fields=['vehicle_id'], groupby=['vehicle_id'])
        vehicle_dict = dict((record['vehicle_id'][0], record['vehicle_id_count']) for record in contract_count)
        for vehicle in self:
            vehicle.contract_count = vehicle_dict.get(vehicle.id)

    @api.multi
    def _compute_count_vehiclecost(self):
        cost_count = self.env['fleet.vehicle.cost'].read_group([('vehicle_id', 'in', self.ids), ('parent_id', '=', False)], fields=['vehicle_id'], groupby=['vehicle_id'])
        vehicle_dict = dict((record['vehicle_id'][0], record['vehicle_id_count']) for record in cost_count)
        for vehicle in self:
            vehicle.cost_count = vehicle_dict.get(vehicle.id)

    @api.multi
    def return_action_to_open(self):
        """ This opens the xml view specified in xml_id for the current vehicle """
        self.ensure_one()
        if self.env.context.get('xml_id'):
            result = self.env.ref('fleet.' + self.env.context['xml_id']).read()[0]
            result['context'] = dict(self.env.context, default_vehicle_id=self.id)
            result['domain'] = [('vehicle_id', '=', self.id)]
            return result
        return False

    @api.multi
    def act_show_log_cost(self):
        """ This opens log view to view and add new log for this vehicle, groupby default to only show effective costs
            @return: the costs log view
        """
        self.ensure_one()
        result = self.env.ref('fleet.fleet_vehicle_costs_act').read()[0]
        result['context'] = dict(self.env.context, default_vehicle_id=self.id, search_default_parent_false=True)
        result['domain'] = [('vehicle_id', '=', self.id)]
        return result

    @api.model
    def create(self, values):
        vehicle = super(FleetVehicle, self).create(values)
        vehicle.message_post(body=_('%s %s has been added to the fleet!') % (vehicle.model_id.name,
                             vehicle.license_plate))
        return vehicle


class FleetVehicleOdometer(models.Model):
    _name = 'fleet.vehicle.odometer'
    _description = 'Odometer log for a vehicle'
    _order = 'date desc'

    name = fields.Char(compute='_compute_vehicle_log_name', store=True)
    date = fields.Date(default=fields.Date.context_today)
    value = fields.Float('Odometer Value', group_operator="max")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', required=True)
    unit = fields.Selection(related='vehicle_id.odometer_unit', readonly=True)

    @api.one
    @api.depends('vehicle_id', 'date')
    def _compute_vehicle_log_name(self):
        name = self.vehicle_id.name
        self.name = name + ' / ' + self.date if self.date else name


class FleetVehicleLogFuel(models.Model):

    _name = 'fleet.vehicle.log.fuel'
    _description = 'Fuel log for vehicles'
    _inherits = {'fleet.vehicle.cost': 'cost_id'}

    @api.model
    def default_get(self, fields):
        res = super(FleetVehicleLogFuel, self).default_get(fields)
        service_type = self.env.ref('fleet.type_service_refueling').id
        res.update({'cost_type': 'fuel', 'cost_subtype_id': service_type})
        return res
    
    liter = fields.Float()
    price_per_liter = fields.Float()
    purchaser_id = fields.Many2one('res.partner', string='Purchaser',
                                   domain="['|', ('customer', '=', True), ('employee', '=', True)]")
    inv_ref = fields.Char(string='Invoice Reference')
    vendor_id = fields.Many2one('res.partner', string='Supplier', domain="[('supplier', '=', True)]")
    notes = fields.Text()
    cost_id = fields.Many2one('fleet.vehicle.cost', string='Cost', required=True, ondelete='cascade')
    cost_amount = fields.Float(related='cost_id.amount', string='Amount', store=True)

    @api.onchange('vehicle_id')
    def _onchange_vehicle(self):
        self.odometer_unit = self.vehicle_id.odometer_unit
        self.purchaser_id = self.vehicle_id.driver_id

    @api.onchange('liter', 'price_per_liter', 'amount')
    def _onchange_liter(self):
        """
        need to cast in float because the value received from web client maybe an integer (Javascript and JSON do not
        make any difference between 3.0 and 3). This cause a problem if you encode, for example, 2 liters at 1.5 per
        liter => total is computed as 3.0, then trigger an onchange that recomputes price_per_liter as 3/2=1 (instead
        of 3.0/2=1.5)
        If there is no change in the result, we return an empty dict to prevent an infinite loop due to the 3 intertwine
        onchange. And in order to verify that there is no change in the result, we have to limit the precision of the
        computation to 2 decimal
        """
        liter = self.liter
        price_per_liter = self.price_per_liter
        amount = self.amount
        if liter > 0 and price_per_liter > 0 and round(liter * price_per_liter, 2) != amount:
            self.amount = round(liter * price_per_liter, 2)
        elif amount > 0 and liter > 0 and round(amount / liter, 2) != price_per_liter:
            self.price_per_liter = round(amount / liter, 2)
        elif amount > 0 and price_per_liter > 0 and round(amount / price_per_liter, 2) != liter:
            self.liter = round(amount / price_per_liter, 2)


class FleetVehicleLogServices(models.Model):

    _inherits = {'fleet.vehicle.cost': 'cost_id'}
    _name = 'fleet.vehicle.log.services'
    _description = 'Services for vehicles'

    @api.model
    def default_get(self, fields):
        res = super(FleetVehicleLogServices, self).default_get(fields)
        service_type_id = self.env.ref('fleet.type_service_service_8').id
        res.update({'cost_type': 'services', 'cost_subtype_id': service_type_id})
        return res

    purchaser_id = fields.Many2one('res.partner', string='Purchaser',
                                   domain="['|', ('customer', '=', True), ('employee', '=', True)]")
    inv_ref = fields.Char()
    vendor_id = fields.Many2one('res.partner', string='Supplier', domain="[('supplier', '=', True)]")
    cost_amount = fields.Float(related='cost_id.amount', string='Amount', store=True)
    notes = fields.Text()
    cost_id = fields.Many2one('fleet.vehicle.cost', string='Cost', required=True, ondelete='cascade')

    @api.onchange('vehicle_id')
    def _onchange_vehicle(self):
        self.odometer_unit = self.vehicle_id.odometer_unit
        self.purchaser_id = self.vehicle_id.driver_id


class FleetServiceType(models.Model):
    _name = 'fleet.service.type'
    _description = 'Type of services available on a vehicle'

    name = fields.Char(required=True, translate=True)
    category = fields.Selection([('contract', 'Contract'), ('service', 'Service'), ('both', 'Both')],
                                required=True,
                                help='Choose whether the service refer to contracts, vehicle services or both')


class FleetVehicleLogContract(models.Model):

    _inherits = {'fleet.vehicle.cost': 'cost_id'}
    _name = 'fleet.vehicle.log.contract'
    _description = 'Contract information on a vehicle'
    _order = 'state desc,expiration_date'

    @api.model
    def default_get(self, fields):
        res = super(FleetVehicleLogContract, self).default_get(fields)
        service_type_id = self.env.ref('fleet.type_contract_leasing').id
        res.update({'cost_type': 'contract', 'cost_subtype_id': service_type_id})
        return res

    name = fields.Text(compute='_compute_vehicle_contract_name_get', store=True)
    start_date = fields.Date(string='Contract Start Date', help='Date when the coverage of the contract begins',
                             default=fields.Date.context_today)
    expiration_date = fields.Date(string='Contract Expiration Date',
                                  default=lambda self: self._compute_next_year_date(fields.Date.context_today(self)),
                                  help='Date when the coverage of the contract expirates '
                                       '(by default, one year after begin date)')
    days_left = fields.Integer(compute='_compute_days_left', string='Warning Date')
    insurer_id = fields.Many2one('res.partner', string='Supplier')
    purchaser_id = fields.Many2one('res.partner', string='Contractor',
                                   help='Person to which the contract is signed for',
                                   default=lambda self: self.env['res.users'].browse(self._uid).partner_id.id or False)
    ins_ref = fields.Char(string='Contract Reference', copy=False)
    state = fields.Selection([('open', 'In Progress'), ('toclose', 'To Close'), ('closed', 'Terminated')],
                             string='Status', readonly=True, help='Choose whether the contract is still valid or not',
                             copy=False, default='open')
    notes = fields.Text(string='Terms and Conditions',
                        help='Write here all supplementary information relative to this contract', copy=False)
    cost_generated = fields.Float(string='Recurring Cost Amount',
                                  help="Costs paid at regular intervals, depending on the cost frequency. "
                                       "If the cost frequency is set to unique, the cost will be logged at "
                                       "the start date")
    cost_frequency = fields.Selection([('no', 'No'), ('daily', 'Daily'), ('weekly', 'Weekly'),
                                       ('monthly', 'Monthly'), ('yearly', 'Yearly')],
                                      string='Recurring Cost Frequency',
                                      help='Frequency of the recurring cost', required=True, default='no')
    generated_cost_ids = fields.One2many('fleet.vehicle.cost', 'contract_id', string='Generated Costs')
    sum_cost = fields.Float(compute='_compute_sum_cost', string='Indicative Costs Total')
    cost_id = fields.Many2one('fleet.vehicle.cost', string='Cost', required=True, ondelete='cascade')
    cost_amount = fields.Float(related='cost_id.amount', string='Amount', store=True)

    @api.one
    @api.depends('cost_subtype_id')
    def _compute_vehicle_contract_name_get(self):
        name = self.vehicle_id.name + ' / ' + self.cost_subtype_id.name
        self.name = self.date and name + ' / ' + self.date or name

    def _compute_next_year_date(self, strdate):
        oneyear = datetime.timedelta(days=365)
        curdate = datetime.datetime.strptime(strdate, tools.DEFAULT_SERVER_DATE_FORMAT)
        return datetime.datetime.strftime(curdate + oneyear, tools.DEFAULT_SERVER_DATE_FORMAT)

    @api.one
    def _compute_sum_cost(self):
        self.sum_cost = sum([cost.amount for cost in self.cost_ids])

    @api.multi
    def _compute_days_left(self):
        """
        if contract is in an open state and is overdue, return 0
        if contract is in a closed state, return -1
        otherwise return the number of days before the contract expires
        """
        today = fields.Datetime.from_string(fields.Date.today())
        for log_contract in self:
            if log_contract.expiration_date and (log_contract.state in ('open', 'toclose')):
                renew_date = fields.Datetime.from_string(log_contract.expiration_date)
                diff_time = (renew_date - today).days
                log_contract.days_left = diff_time > 0 and diff_time or 0
            else:
                log_contract.days_left = -1

    @api.multi
    def act_renew_contract(self):
        self.ensure_one()
        # compute end date
        startdate = fields.Datetime.from_string(self.start_date)
        enddate = fields.Datetime.from_string(self.expiration_date)
        diffdate = (enddate - startdate)
        default = {
            'date': fields.Date.context_today(self),
            'start_date': fields.Datetime.to_string(fields.Datetime.from_string(self.expiration_date) +
                                                    datetime.timedelta(days=1)),
            'expiration_date': fields.Datetime.to_string(enddate + diffdate),
        }
        newid = self.copy(default).id
        return {
            'name': _("Renew Contract"),
            'view_mode': 'form',
            'view_id': self.env.ref('fleet.fleet_vehicle_log_contract_form').id,
            'view_type': 'tree,form',
            'res_model': 'fleet.vehicle.log.contract',
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'domain': '[]',
            'res_id': newid,
            'context': {'active_id': newid},
        }

    @api.model
    def scheduler_manage_auto_costs(self):
        """
        This method is called by a cron task
        It creates costs for contracts having the "recurring cost" field setted, depending on their frequency
        For example, if a contract has a reccuring cost of 200 with a weekly frequency, this method creates a cost of
        200 on the first day of each week, from the date of the last recurring costs in the database to today
        If the contract has not yet any recurring costs in the database, the method generates the recurring costs
        from the start_date to today
        The created costs are associated to a contract thanks to the many2one field contract_id
        If the contract has no start_date, no cost will be created, even if the contract has recurring costs
        """
        VehicleCost = self.env['fleet.vehicle.cost']
        today = fields.Datetime.from_string(fields.Date.context_today(self))
        log_contract = self.env['fleet.vehicle.log.contract'].search([('state', '!=', 'closed'),
                                                                      '|', ('start_date', '=', None),
                                                                      ('cost_frequency', '!=', 'no')])
        deltas = {'yearly': relativedelta(years=+1), 'monthly': relativedelta(months=+1),
                  'weekly': relativedelta(weeks=+1), 'daily': relativedelta(days=+1)}
        for contract in log_contract:
            last_cost_date = contract.start_date
            if contract.generated_cost_ids:
                vehicle_cost = VehicleCost.search(['&', ('contract_id', '=', contract.id),
                                                  ('auto_generated', '=', True)], limit=1, order='date desc')[0]
                if vehicle_cost:
                    last_cost_date = vehicle_cost.date
            last_cost_date = fields.Datetime.from_string(last_cost_date)
            last_cost_date += deltas.get(contract.cost_frequency)
            while (last_cost_date <= today) and (
                    last_cost_date <= fields.Datetime.from_string(contract.expiration_date)):
                data = {
                    'amount': contract.cost_generated,
                    'date': fields.Date.to_string(last_cost_date),
                    'vehicle_id': contract.vehicle_id.id,
                    'cost_subtype_id': contract.cost_subtype_id.id,
                    'contract_id': contract.id,
                    'auto_generated': True
                }
                VehicleCost.create(data)
                last_cost_date += deltas.get(contract.cost_frequency)
        return True

    @api.model
    def scheduler_manage_contract_expiration(self):
        # This method is called by a cron task
        # It manages the state of a contract, possibly by posting a message on the vehicle concerned and
        # updating its status
        today = fields.Datetime.from_string(fields.Date.context_today(self))
        limit_date = fields.Date.to_string(today + relativedelta(days=+15))
        log_contract = self.search(['&', ('state', '=', 'open'), ('expiration_date', '<', limit_date)])
        result = defaultdict(int)
        for contract in log_contract:
            result[contract.vehicle_id.id] += 1

        for vehicle, value in result.items():
            self.env['fleet.vehicle'].browse(vehicle).message_post(body=_('%s contract(s) need(s) to be renewed '
                                                                          'and/or closed!') % (value))
        log_contract.write({'state': 'toclose'})

    @api.model
    def run_scheduler(self):
        self.scheduler_manage_auto_costs()
        self.scheduler_manage_contract_expiration()

    @api.one
    def contract_close(self):
        self.state = 'closed'

    @api.one
    def contract_open(self):
        self.state = 'open'
