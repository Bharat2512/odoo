from openerp import models, fields, api

class account_common_account_report(models.TransientModel):
    _name = 'account.common.account.report'
    _description = 'Account Common Account Report'
    _inherit = "account.common.report"

    display_account = fields.Selection([('all','Display all Accounts'), 
        ('movement','Display Accounts with movements'),
        ('not_zero','Display Account where balance is not equal to 0'),
        ],'Display Accounts', required=True, default='movement')

    @api.multi
    def pre_print_report(self, data):
        data['form'].update(self.read(['display_account'])[0])
        return data
