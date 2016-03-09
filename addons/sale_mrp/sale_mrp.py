# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from openerp import api, fields, models
from openerp.tools import float_compare


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    sale_name = fields.Char(compute='_compute_sale_name_sale_ref', string='Sale Name', help='Indicate the name of sales order.')
    sale_ref = fields.Char(compute='_compute_sale_name_sale_ref', string='Sale Reference', help='Indicate the Customer Reference from sales order.')

    @api.multi
    def _compute_sale_name_sale_ref(self):
        def get_parent_move(move):
            if move.move_dest_id:
                return get_parent_move(move.move_dest_id)
            return move
        for production in self:
            if production.move_prod_id:
                move = get_parent_move(production.move_prod_id)
                production.sale_name = move.procurement_id and move.procurement_id.sale_line_id and move.procurement_id.sale_line_id.order_id.name or False
                production.sale_ref = move.procurement_id and move.procurement_id.sale_line_id and move.procurement_id.sale_line_id.order_id.client_order_ref or False


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.multi
    def _get_delivered_qty(self):
        self.ensure_one()
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')

        # In the case of a kit, we need to check if all components are shipped. We use a all or
        # nothing policy. A product can have several BoMs, we don't know which one was used when the
        # delivery was created.
        bom_delivered = {}
        for bom in self.product_id.product_tmpl_id.bom_ids:
            if bom.type != 'phantom':
                continue
            bom_delivered[bom.id] = False
            bom_exploded = self.env['mrp.bom']._bom_explode(bom, self.product_id, self.product_uom_qty)[0]
            for bom_line in bom_exploded:
                qty = 0.0
                for move in self.procurement_ids.mapped('move_ids'):
                    if move.state == 'done' and move.product_id.id == bom_line.get('product_id', False):
                        qty += self.env['product.uom']._compute_qty_obj(move.product_uom, move.product_uom_qty, self.product_uom)
                if float_compare(qty, bom_line['product_uom_qty'], precision_digits=precision) < 0:
                    bom_delivered[bom.id] = False
                    break
                else:
                    bom_delivered[bom.id] = True
        if bom_delivered and any(bom_delivered.values()):
            return self.product_uom_qty
        elif bom_delivered:
            return 0.0
        return super(SaleOrderLine, self)._get_delivered_qty()