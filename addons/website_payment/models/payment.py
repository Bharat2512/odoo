from openerp import fields, models


class PaymentAcquirer(models.Model):
    _name = 'payment.acquirer'
    _inherit = ['payment.acquirer','website.published.mixin']

    is_cod = fields.Boolean()
