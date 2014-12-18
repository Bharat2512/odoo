from openerp import models, fields, api


class account_report_general_ledger(models.TransientModel):
    _inherit = "account.common.account.report"
    _name = "account.report.general.ledger"
    _description = "General Ledger Report"

    landscape = fields.Boolean(string='Landscape Mode', default=True)
    initial_balance = fields.Boolean(string='Include Initial Balances', default=False,
        help='''If you selected to filter by date or period, this field allow you to add a 
        row to display the amount of debit/credit/balance that precedes the filter you\'ve set.''')
    amount_currency = fields.Boolean(string='With Currency', default=True,
        help="It adds the currency column on report if the currency differs from the company currency.")
    sortby = fields.Selection([('sort_date', 'Date'), ('sort_journal_partner', 'Journal & Partner')],
        string='Sort by', required=True, default='sort_date')
    journal_ids = fields.Many2many('account.journal', 'account_report_general_ledger_journal_rel', 'account_id', 'journal_id', string='Journals', required=True)

    @api.onchange('fiscalyear_id')
    def onchange_fiscalyear(self):
        if not self.fiscalyear_id:
            self.initial_balance = False

    @api.multi
    def _print_report(self, data):
        context = dict(self._context or {})
        data = self.pre_print_report(data)
        data['form'].update(self.read(['landscape',  'initial_balance', 'amount_currency', 'sortby'])[0])
        if not data['form']['fiscalyear_id']:# GTK client problem onchange does not consider in save record
            data['form'].update({'initial_balance': False})

        if data['form']['landscape'] is False:
            data['form'].pop('landscape')
        else:
            context['landscape'] = data['form']['landscape']

        return self.env['report'].with_context(context).get_action(self.env['account.report.general.ledger'], 'account.report_generalledger', data=data)

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
