# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProcurementOrder(models.Model):
    _inherit = 'procurement.order'

    task_id = fields.Many2one('project.task', string='Task', copy=False)

    @api.multi
    def _is_procurement_task(self):
        self.ensure_one()
        return self.product_id.type == 'service' and self.product_id.track_service == 'task' or False

    @api.multi
    def _assign(self):
        self.ensure_one()
        res = super(ProcurementOrder, self)._assign()
        if not res:
            #if there isn't any specific procurement.rule defined for the product, we may want to create a task
            return self._is_procurement_task()
        return res

    @api.multi
    def _run(self):
        self.ensure_one()
        if self._is_procurement_task() and not self.task_id:
            #create a task for the procurement
            return self._create_service_task()
        return super(ProcurementOrder, self)._run()

    def _convert_qty_company_hours(self):
        product_uom = self.env['product.uom']
        company_time_uom_id = self.env.user.company_id.project_time_mode_id
        if self.product_uom.id != company_time_uom_id.id and self.product_uom.category_id.id == company_time_uom_id.category_id.id:
            planned_hours = product_uom._compute_qty(self.product_uom.id, self.product_qty, company_time_uom_id.id)
        else:
            planned_hours = self.product_qty
        return planned_hours

    def _get_project(self):
        Project = self.env['project.project']
        project = self.product_id.project_id
        if not project and self.sale_line_id:
            # find the project corresponding to the analytic account of the sales order
            account = self.sale_line_id.order_id.project_id
            if not account:
                self.sale_line_id.order_id._create_analytic_account()
                account = self.sale_line_id.order_id.project_id
            projects = Project.search([('analytic_account_id', '=', account.id)])
            project = projects and projects[0]
            if not project:
                project_id = account.project_create({'name': account.name, 'use_tasks': True})
                project = Project.browse(project_id)
        return project

    def _create_service_task(self):
        project = self._get_project()
        planned_hours = self._convert_qty_company_hours()
        task = self.env['project.task'].create({
            'name': '%s:%s' % (self.origin or '', self.product_id.name),
            'date_deadline': self.date_planned,
            'planned_hours': planned_hours,
            'remaining_hours': planned_hours,
            'partner_id': self.sale_line_id and self.sale_line_id.order_id.partner_id.id or self.partner_dest_id.id,
            'user_id': self.product_id.product_manager.id,
            'procurement_id': self.id,
            'description': self.name + '\n',
            'project_id': project and project.id or False,
            'company_id': self.company_id.id,
        })
        self.write({'task_id': task.id})
        self.project_task_create_note()
        return task

    @api.multi
    def project_task_create_note(self):
        self.ensure_one()
        for procurement in self:
            body = _("Task created")
            self.message_post(body=body)
            if procurement.sale_line_id and procurement.sale_line_id.order_id:
                procurement.sale_line_id.order_id.message_post(body=body)


class ProjectTask(models.Model):
    _inherit = "project.task"

    procurement_id = fields.Many2one('procurement.order', string='Procurement', ondelete='set null')
    sale_line_id = fields.Many2one(related='procurement_id.sale_line_id', store=True, string='Sales Order Line')

    @api.multi
    def unlink(self):
        for task in self:
            if task.sale_line_id:
                raise ValidationError(_('You cannot delete a task related to a Sale Order. You can only archive this task.'))
        res = super(ProjectTask, self).unlink()
        return res

    @api.multi
    def action_view_so(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "views": [[False, "form"]],
            "res_id": self.sale_line_id.order_id.id,
            "context": {"create": False, "show_sale": True},
        }

    @api.onchange('parent_id')
    def onchange_parent_id(self):
        if not self.parent_id:
            return {'value': {'procurement_id': False, 'sale_line_id': False}}
        parent_task = self.parent_id
        return {
            'value': {
                'procurement_id': parent_task.procurement_id.id,
                'sale_line_id': parent_task.sale_line_id.id,
            }
        }


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.multi
    def _need_procurement(self):
        for product in self:
            if product.type == 'service' and product.track_service == 'task':
                return True
        return super(ProductProduct, self)._need_procurement()
