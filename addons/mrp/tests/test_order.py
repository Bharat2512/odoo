# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.addons.mrp.tests.common import TestMrpCommon


class TestMrpOrder(TestMrpCommon):

    def test_access_rights_manager(self):
        production = self.production_1.sudo(self.user_mrp_manager)
        # production.action_compute()
        # production.signal_workflow('button_confirm')
        production.action_cancel()
        self.assertEqual(production.state, 'cancel')
        production.unlink()

    def test_access_rights_user(self):
        production = self.production_1.sudo(self.user_mrp_user)
        # production.action_compute()
        # production.signal_workflow('button_confirm')
        production.action_cancel()
        self.assertEqual(production.state, 'cancel')
        production.unlink()

    def test_flow(self):
        production = self.production_1.sudo(self.user_mrp_user)
        # production.action_compute()

    def test_production_avialability(self):
        """
            Test availability of production order.
        """
        self.bom_2.write({'routing_id': False, 'type': 'normal'})

        production_2 = self.env['mrp.production'].create({
            'name': 'MO-Test001',
            'product_id': self.product_3.id,
            'product_qty': 20,
            'bom_id': self.bom_2.id,
            'product_uom_id': self.product_1.uom_id.id,
        })
        production_2.action_assign()

        # check sub product availability state is waiting
        self.assertEqual(production_2.availability, 'waiting', 'Production order should be availability for waiting state')

        # Update Inventory
        inventory_wizard = self.env['stock.change.product.qty'].create({
            'product_id': self.product_4.id,
            'new_quantity': 10.0,
        })
        inventory_wizard.change_product_qty()

        production_2.action_assign()

        # check sub product availability state is partially available
        self.assertEqual(production_2.availability, 'partially_available', 'Production order should be availability for partially available state')

        # Update Inventory
        inventory_wizard = self.env['stock.change.product.qty'].create({
            'product_id': self.product_4.id,
            'new_quantity': 30.0,
        })
        inventory_wizard.change_product_qty()

        production_2.action_assign()

        # check sub product availability state is assigned
        self.assertEqual(production_2.availability, 'assigned', 'Production order should be availability for assigned state')
