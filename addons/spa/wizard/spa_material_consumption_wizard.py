from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SpaMaterialConsumptionWizard(models.TransientModel):
    _name = 'spa.material.consumption.wizard'
    _description = 'Xác nhận nguyên vật liệu sử dụng cho dịch vụ'

    appointment_id = fields.Many2one(
        'spa.appointment',
        string='Lịch hẹn',
        required=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        'spa.material.consumption.wizard.line',
        'wizard_id',
        string='Nguyên vật liệu',
    )

    @api.model
    def create_for_appointment(self, appointment, material_quantities):
        products = self.env['product.product'].browse(
            list(material_quantities)
        )
        wizard = self.create({
            'appointment_id': appointment.id,
            'line_ids': [
                fields.Command.create({
                    'product_id': product.id,
                    'planned_quantity': material_quantities[product.id],
                    'quantity': material_quantities[product.id],
                })
                for product in products
            ],
        })
        return wizard

    def action_open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Xác nhận nguyên vật liệu sử dụng',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[
                self.env.ref(
                    'spa.view_spa_material_consumption_wizard_form'
                ).id,
                'form',
            ]],
            'target': 'new',
        }

    def action_confirm(self):
        self.ensure_one()
        quantity_by_product = {
            line.product_id.id: line.quantity
            for line in self.line_ids
        }
        return self.appointment_id.with_context(
            spa_materials_confirmed=True,
            spa_material_quantities=quantity_by_product,
        ).action_done()


class SpaMaterialConsumptionWizardLine(models.TransientModel):
    _name = 'spa.material.consumption.wizard.line'
    _description = 'Nguyên vật liệu sử dụng cho dịch vụ'

    wizard_id = fields.Many2one(
        'spa.material.consumption.wizard',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Nguyên vật liệu',
        required=True,
        readonly=True,
    )
    planned_quantity = fields.Float(
        string='Định lượng dự kiến',
        required=True,
        digits='Product Unit of Measure',
        readonly=True,
    )
    quantity = fields.Float(
        string='Số lượng thực tế',
        required=True,
        digits='Product Unit of Measure',
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Đơn vị tính',
        related='product_id.uom_id',
        readonly=True,
    )

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity < 0:
                raise ValidationError(
                    'Số lượng nguyên vật liệu thực tế không được âm.'
                )
