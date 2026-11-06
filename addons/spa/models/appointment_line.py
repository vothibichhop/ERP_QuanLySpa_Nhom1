from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SpaAppointmentLine(models.Model):
    _name = 'spa.appointment.line'
    _description = 'Dịch vụ trong lịch hẹn Spa'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    appointment_id = fields.Many2one(
        'spa.appointment',
        string='Lịch hẹn',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.template',
        string='Dịch vụ hoặc combo',
        required=True,
        domain=[('type', 'in', ('service', 'combo'))],
        ondelete='restrict',
    )
    combo_choice_ids = fields.One2many(
        'spa.appointment.combo.choice',
        'appointment_line_id',
        string='Dịch vụ thành phần đã chọn',
        copy=True,
    )
    duration_minutes = fields.Integer(
        string='Thời lượng (phút)',
        required=True,
        default=0,
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id.type == 'combo':
                line.combo_choice_ids = [
                    fields.Command.create({'combo_id': combo.id})
                    for combo in line.product_id.combo_ids
                ]
                line.duration_minutes = line.product_id.spa_duration_minutes
            else:
                line.combo_choice_ids = [fields.Command.clear()]
                line.duration_minutes = line.product_id.spa_duration_minutes

    @api.onchange('combo_choice_ids')
    def _onchange_combo_choice_ids(self):
        for line in self:
            if (
                line.product_id.type == 'combo'
                and not line.product_id.spa_duration_minutes
            ):
                line.duration_minutes = sum(
                    line.combo_choice_ids.mapped(
                        'combo_item_id.product_id.product_tmpl_id.spa_duration_minutes'
                    )
                )

    @api.constrains('product_id', 'combo_choice_ids', 'duration_minutes')
    def _check_combo_choices(self):
        for line in self:
            if line.product_id.type not in ('service', 'combo'):
                raise ValidationError('Chỉ được chọn dịch vụ Spa hoặc combo Spa.')
            if line.duration_minutes <= 0:
                raise ValidationError('Thời lượng dịch vụ phải lớn hơn 0 phút.')
            if line.product_id.type != 'combo':
                if line.combo_choice_ids:
                    raise ValidationError('Dịch vụ đơn không được có lựa chọn thành phần combo.')
                continue

            expected_combo_ids = set(line.product_id.combo_ids.ids)
            selected_combo_ids = set(line.combo_choice_ids.mapped('combo_id').ids)
            if selected_combo_ids != expected_combo_ids:
                raise ValidationError(
                    'Vui lòng chọn một dịch vụ cho từng mục trong combo.'
                )
            if len(line.combo_choice_ids.mapped('combo_id')) != len(line.combo_choice_ids):
                raise ValidationError('Mỗi mục trong combo chỉ được chọn một dịch vụ.')


class SpaAppointmentComboChoice(models.Model):
    _name = 'spa.appointment.combo.choice'
    _description = 'Lựa chọn dịch vụ thành phần combo'

    appointment_line_id = fields.Many2one(
        'spa.appointment.line',
        string='Dòng dịch vụ',
        required=True,
        ondelete='cascade',
    )
    combo_id = fields.Many2one(
        'product.combo',
        string='Mục combo',
        required=True,
        ondelete='restrict',
    )
    combo_item_id = fields.Many2one(
        'product.combo.item',
        string='Dịch vụ thành phần',
        required=True,
        domain="[('combo_id', '=', combo_id)]",
        ondelete='restrict',
    )

    @api.constrains('appointment_line_id', 'combo_id', 'combo_item_id')
    def _check_combo_item(self):
        for choice in self:
            if choice.combo_id not in choice.appointment_line_id.product_id.combo_ids:
                raise ValidationError('Mục lựa chọn không thuộc combo đã chọn.')
            if choice.combo_item_id.combo_id != choice.combo_id:
                raise ValidationError('Dịch vụ thành phần không thuộc mục combo đã chọn.')
