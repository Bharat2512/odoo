# -*- coding: utf-8 -*-

from openerp import models, fields, api, _

# ---------------------------------------------------------
# Account Financial Report
# ---------------------------------------------------------

class account_financial_report(models.Model):
    _name = "account.financial.report"
    _description = "Account Report"

    @api.multi
    @api.depends('parent_id')
    def _get_level(self):
        for report in self:
            level = 0
            if report.parent_id:
                level = report.parent_id.level + 1
            report.level = level

    @api.multi
    def _get_children_by_order(self):
        '''all its children, computed recursively, and sorted by sequence. Ready for the printing'''
        res = []
        for id in self.ids:
            res.append(id)
            ids2 = self.search([('parent_id', '=', id)], order='sequence ASC')
            res += ids2._get_children_by_order()
        return res

    @api.multi
    def _get_balance(self):
        '''returns a dictionary with key=the ID of a record and value=the balance amount 
           computed for this record. If the record is of type :
               'accounts' : it's the sum of the linked accounts
               'account_type' : it's the sum of leaf accoutns with such an account_type
               'account_report' : it's the amount of the related report
               'sum' : it's the sum of the children of this record (aka a 'view' record)'''
        AccountObj = self.env['account.account']
        balance = credit = debit = 0.0
        res = {}
        for report in self:
            if report.type == 'accounts':
                # it's the sum of the linked accounts
                for a in report.account_ids:
                    balance += a.balance
                    credit += a.credit
                    debit += a.debit
            elif report.type == 'account_type':
                # it's the sum the leaf accounts with such an account type
                report_types = [x.id for x in report.account_type_ids]
                account_ids = AccountObj.search([('user_type', 'in', report_types)])
                for a in account_ids:
                    balance += a.balance
                    credit += a.credit
                    debit += a.debit
            elif report.type == 'account_report' and report.account_report_id:
                # it's the amount of the linked report
                res2 = report.account_report_id
                balance += res2.balance
                credit += res2.credit
                debit += res2.debit
            elif report.type == 'sum':
                # it's the sum of the children of this account.report
                for a in report.children_ids:
                    balance += a.balance
                    credit += a.credit
                    debit += a.debit
            report.balance = balance
            report.credit = credit
            report.debit = debit

    name = fields.Char(string='Report Name', required=True, translate=True)
    parent_id = fields.Many2one('account.financial.report', string='Parent')
    children_ids = fields.One2many('account.financial.report', 'parent_id', string='Account Report')
    sequence = fields.Integer(string='Sequence')
    balance = fields.Float(compute='_get_balance', string='Balance')
    debit = fields.Float(compute='_get_balance', string='Debit')
    credit = fields.Float(compute='_get_balance', string='Credit')
    level = fields.Integer(compute='_get_level', string='Level', store=True)
    type = fields.Selection([
        ('sum','View'),
        ('accounts','Accounts'),
        ('account_type','Account Type'),
        ('account_report','Report Value'),
        ], string='Type', default='sum')
    account_ids = fields.Many2many('account.account', string='Accounts', domain=[('deprecated', '=', False)])
    account_report_id = fields.Many2one('account.financial.report', string='Report Value')
    account_type_ids = fields.Many2many('account.account.type', string='Account Types')
    sign = fields.Selection([(-1, 'Reverse balance sign'), (1, 'Preserve balance sign')],
        string='Sign on Reports', required=True, default=1, 
        help="""For accounts that are typically more debited than credited and that you would 
        like to print as negative amounts in your reports, you should reverse the sign of the balance; 
        e.g.: Expense account. The same applies for accounts that are typically more credited than debited and that 
        you would like to print as positive amounts in your reports; e.g.: Income account.""")
    display_detail = fields.Selection([
        ('no_detail','No detail'),
        ('detail_flat','Display children flat'),
        ('detail_with_hierarchy','Display children with hierarchy')
        ], string='Display details', default='detail_flat')
    style_overwrite = fields.Selection([
        (0, 'Automatic formatting'),
        (1, 'Main Title 1 (bold, underlined)'),
        (2, 'Title 2 (bold)'),
        (3, 'Title 3 (bold, smaller)'),
        (4, 'Normal Text'),
        (5, 'Italic Text (smaller)'),
        (6, 'Smallest Text'),
        ], string='Financial Report Style', default=0,
        help="""You can set up here the format you want this record to be displayed. If you leave the automatic formatting, 
        it will be computed based on the financial reports hierarchy (auto-computed field 'level').""")
