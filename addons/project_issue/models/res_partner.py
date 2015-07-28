# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    issue_count = fields.Integer(compute='_compute_issue_count', string='# Issues')

    def _compute_issue_count(self):
        issues_data = self.env['project.issue'].read_group([('partner_id', 'in', self.ids)], ['partner_id'], ['partner_id'])
        result = dict((data['partner_id'][0], data['partner_id_count']) for data in issues_data)
        for partner in self:
            partner.issue_count = result.get(partner.id, 0)
