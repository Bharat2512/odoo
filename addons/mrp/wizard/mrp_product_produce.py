# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from openerp import api, fields, models
import openerp.addons.decimal_precision as dp

class MrpProductProduce(models.TransientModel):
    _name = "mrp.product.produce"
    _description = "Record Production"

    @api.model
    def default_get(self, fields):
        res = super(MrpProductProduce, self).default_get(fields)
        if self._context and self._context.get('active_id'):
            production = self.env['mrp.production'].browse(self._context['active_id'])
            serial_raw = production.move_raw_ids.filtered(lambda x: x.product_id.tracking == 'serial')
            serial_finished = production.move_finished_ids.filtered(lambda x: x.product_id.tracking == 'serial')
            serial = bool(serial_raw or serial_finished)
            if serial_raw or serial_finished:
                quantity = 1.0
            else:
                quantity = production.product_qty - production.qty_produced

            lines = []
            for move in production.move_raw_ids.filtered(lambda x: x.product_id.tracking <> 'none'):
                qty = quantity / move.bom_line_id.bom_id.product_qty * move.bom_line_id.product_qty
                if move.product_id.tracking=='serial':
                    while qty > 0.000001:
                        lines.append({
                            'move_id': move.id,
                            'quantity': min(1,qty),
                            'product_id': production.product_id.id
                        })
                        qty -= 1
                else:
                    lines.append({
                        'move_id': move.id,
                        'quantity': qty,
                        'product_id': production.product_id.id
                    })

            res['serial'] = serial
            res['production_id'] = production.id
            res['product_qty'] = quantity
            res['product_id'] = production.product_id.id
            res['product_uom_id'] = production.product_uom_id.id
            res['consume_line_ids'] = map(lambda x: (0,0,x), lines)
        return res

    serial = fields.Boolean('Requires Serial')
    production_id = fields.Many2one('mrp.production', 'Production')
    product_id = fields.Many2one('product.product', 'Product')
    product_qty = fields.Float(string='Quantity', digits=dp.get_precision('Product Unit of Measure'), required=True)
    product_uom_id = fields.Many2one('product.uom', 'Unit of Measure')

    lot_id = fields.Many2one('stock.production.lot', string='Lot')
    consume_line_ids = fields.Many2many('stock.move.lots', 'mrp_produce_stock_move_lots', string='Product to Track')

    @api.multi
    def do_produce(self):
        # Nothing to do for lots since values are created using default data (stock.move.lots)
        moves = self.production_id.move_raw_ids + self.production_id.move_finished_ids
        for move in moves.filtered(lambda x: x.product_id.tracking == 'none'):
            quantity = self.product_qty
            if move.bom_line_id:
                quantity = quantity / move.bom_line_id.bom_id.product_qty * move.bom_line_id.product_qty
            move.quantity_done_store += quantity
        return {}

