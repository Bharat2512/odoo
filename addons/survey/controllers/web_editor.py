# -*- coding: utf-8 -*-

from openerp import http
from openerp.http import request
from openerp.addons.web_editor.controllers.main import Web_Editor


class Web_Editor(Web_Editor):

    @http.route('/survey/field/survey_template', type='http', auth="user")
    def survey_FieldTextHtmlEmailTemplate(self, model=None, res_id=None, field=None, callback=None, **kwargs):
        kwargs['snippets'] = '/survey/snippets'
        kwargs['template'] = 'survey.FieldTextHtmlInline'
        return self.FieldTextHtmlInline(model, res_id, field, callback, **kwargs)

    @http.route(['/survey/snippets'], type='json', auth="user")
    def survey_snippets(self):
        values = {'company_id': request.env['res.users'].browse(request.uid).company_id}
        return request.env.ref('survey.survey_design_snippets').render(values)
