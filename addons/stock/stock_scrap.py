# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from openerp import api, fields, models, _


class StockScrap(models.Model):
    _name = 'stock.scrap'

    name = fields.Char(required=True, readonly=True, copy=False, default=lambda self: self.env['ir.sequence'].next_by_code('stock.scrap') or '/', states={'done': [('readonly', True)]}, string="Reference")
    product_id = fields.Many2one('product.product', 'Product', states={'done': [('readonly', True)]}, required=True)
    product_uom_id = fields.Many2one('product.uom', string='Unit of Measure', states={'done': [('readonly', True)]}, required=True)
    lot_id = fields.Many2one('stock.production.lot', 'Lot', states={'done': [('readonly', True)]}, domain="[('product_id', '=', product_id)]")
    picking_id = fields.Many2one('stock.picking', 'Picking', states={'done': [('readonly', True)]})
    location_id = fields.Many2one('stock.location', 'Location', default=lambda self: self.env.ref('stock.warehouse0').lot_stock_id.id or False, states={'done': [('readonly', True)]}, required=True, domain="[('usage', '=', 'internal')]")
    scrap_location_id = fields.Many2one('stock.location', domain="[('scrap_location', '=', True)]", states={'done': [('readonly', True)]}, string="Scrap Location", default=(lambda x: x.env['stock.location'].search([('scrap_location', '=', True)], limit=1)))
    scrap_qty = fields.Float('Qty To Scrap', states={'done': [('readonly', True)]}, required=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default="draft")
    move_id = fields.Many2one('stock.move', 'Stock Move', readonly=True)

    @api.model
    def create(self, vals):
        scrap = super(StockScrap, self).create(vals)
        scrap.do_scrap()
        return scrap

    @api.onchange('product_id')
    def onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id.id

    @api.multi
    def do_scrap(self):
        self.ensure_one()
        StockMove = self.env['stock.move']
        default_val = {
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'product_uom_qty': self.scrap_qty,
            'location_id': self.location_id.id,
            'scrapped': True,
            'location_dest_id': self.scrap_location_id.id,
        }
        move = StockMove.create(default_val)
        new_move = move.action_scrap(self.scrap_qty, self.scrap_location_id.id)
        self.write({'move_id': new_move.id, 'state': 'done'})
        return True

    @api.multi
    def button_stock_picking(self):
        return {
            'name': _('Stock Operations'),
            'view_type': 'form',
            'view_mode': 'tree',
            'res_model': 'stock.picking',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'domain': [('id', '=', self.picking_id.id)],
        }

    @api.multi
    def button_stock_move(self):
        return {
            'name': _('Stock Moves'),
            'view_type': 'form',
            'view_mode': 'tree',
            'res_model': 'stock.move',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'domain': [('id', '=', self.move_id.id)],
        }
