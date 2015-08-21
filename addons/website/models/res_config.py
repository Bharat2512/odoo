# -*- coding: ascii -*-
from odoo import api, fields, models

class WebsiteConfigSettings(models.TransientModel):
    _name = 'website.config.settings'
    _inherit = 'res.config.settings'

    website_id = fields.Many2one('website', string="website", required=True, default=lambda self: self.env['website'].search([], limit=1).id)
    website_name = fields.Char(related='website_id.name', string="Website Name")

    language_ids = fields.Many2many(related='website_id.language_ids', relation='res.lang', string='Languages')
    default_lang_id = fields.Many2one(related='website_id.default_lang_id', relation='res.lang', string='Default language')
    default_lang_code = fields.Char(related='website_id.default_lang_code', string="Default language code")
    google_analytics_key = fields.Char(related='website_id.google_analytics_key', string='Google Analytics Key')

    social_twitter = fields.Char(related='website_id.social_twitter', string='Twitter Account')
    social_facebook = fields.Char(related='website_id.social_facebook', string='Facebook Account')
    social_github = fields.Char(related='website_id.social_github', string='GitHub Account')
    social_linkedin = fields.Char(related='website_id.social_linkedin', string='LinkedIn Account')
    social_youtube = fields.Char(related='website_id.social_youtube', string='Youtube Account')
    social_googleplus = fields.Char(related='website_id.social_googleplus', string='Google+ Account')
    compress_html = fields.Boolean(related='website_id.compress_html', string='Compress rendered HTML for a better Google PageSpeed result')
    cdn_activated = fields.Boolean(related='website_id.cdn_activated', string='Use a Content Delivery Network (CDN)')
    cdn_url = fields.Char(related='website_id.cdn_url', string='CDN Base URL')
    cdn_filters = fields.Text(related='website_id.cdn_filters', string='CDN Filters')
    module_website_form_editor = fields.Boolean(string="Website form builder")
    module_website_version = fields.Boolean(string="Website A/B testing and versioning")

    @api.onchange('website_id')
    def on_change_website_id(self):
        if self.website_id:
            website_data = self.website_id.read([])[0]
            self.website_name = website_data['name']
            for fname, v in website_data.items():
                if fname in self._columns:
                    self.fname = v[0] if v and self._columns[fname]._type == 'many2one' else v
