# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models

from odoo.addons.website.models.website import slug


class Grade(models.Model):

    _name = 'res.partner.grade'
    _inherit = ['res.partner.grade', 'website.published.mixin']

    website_published = fields.Boolean(default=True)

    @api.multi
    def _website_url(self, field_name, arg):
        res = super(Grade, self)._website_url(field_name, arg)
        for grade in self:
            res[grade.id] = "/partners/grade/%s" % slug(grade)
        return res
