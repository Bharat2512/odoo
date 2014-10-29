from openerp import models, api

class account_move_line_unreconcile_select(models.TransientModel):
    _name = "account.move.line.unreconcile.select"
    _description = "Unreconciliation"

    account_id = fields.Many2one('account.account', string='Account', required=True, domain=[('deprecated', '=', False)])

    @api.multi
    def action_open_window(self):
        data = self.read()[0]
        return {
                'domain': "[('account_id','=',%d),('reconcile_id','<>',False),('state','<>','draft')]" % data['account_id'],
                'name': 'Unreconciliation',
                'view_type': 'form',
                'view_mode': 'tree,form',
                'view_id': False,
                'res_model': 'account.move.line',
                'type': 'ir.actions.act_window'
        }

