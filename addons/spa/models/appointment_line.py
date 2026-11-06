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
    employee_id = fields.Many2one(
        'hr.employee.public',
        string='Nhân viên thực hiện',
        domain="[('id', 'in', available_employee_ids)]",
        ondelete='restrict',
    )
    available_employee_ids = fields.Many2many(
        'hr.employee.public',
        compute='_compute_available_employee_ids',
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

    @api.depends(
        'appointment_id.appointment_date',
        'appointment_id.start_time',
        'appointment_id.status',
        'appointment_id.appointment_line_ids.sequence',
        'appointment_id.appointment_line_ids.duration_minutes',
        'sequence',
        'duration_minutes',
        'product_id.spa_employee_ids',
        'combo_choice_ids.combo_item_id.product_id.product_tmpl_id.spa_employee_ids',
    )
    def _compute_available_employee_ids(self):
        employee_model = self.env['hr.employee.public']
        shift_model = self.env['spa.work.shift']
        leave_model = self.env['spa.leave.request']
        appointment_model = self.env['spa.appointment']

        for line in self:
            appointment = line.appointment_id
            if not appointment or not appointment.appointment_date:
                line.available_employee_ids = [(5, 0, 0)]
                continue

            active_employee_ids = set(
                employee_model.search([('active', '=', True)]).ids
            )
            shifts = shift_model.search([
                ('work_date', '=', appointment.appointment_date),
                ('state', '=', 'scheduled'),
            ])
            eligible_employee_ids = active_employee_ids.intersection(
                shifts.mapped('employee_ids').ids
            )
            leaves = leave_model.search([
                ('employee_id', 'in', list(eligible_employee_ids)),
                ('state', 'in', ('submitted', 'approved')),
                ('start_date', '<=', appointment.appointment_date),
                ('end_date', '>=', appointment.appointment_date),
            ])
            eligible_employee_ids.difference_update(
                leaves.mapped('employee_id').ids
            )

            for product in line._get_service_products():
                assigned_ids = set(product.spa_employee_ids.ids)
                if assigned_ids:
                    eligible_employee_ids.intersection_update(assigned_ids)

            if (
                appointment.start_time is not False
                and line.duration_minutes > 0
                and eligible_employee_ids
            ):
                ordered_lines = appointment.appointment_line_ids.sorted(
                    key=lambda item: (item.sequence, item.id or 0)
                )
                offset_minutes = 0
                for preceding_line in ordered_lines:
                    if preceding_line == line:
                        break
                    offset_minutes += preceding_line.duration_minutes
                start_time = (
                    appointment.start_time * 60 + offset_minutes
                ) / 60
                end_time = (
                    appointment.start_time * 60
                    + offset_minutes
                    + line.duration_minutes
                ) / 60
                if end_time <= 24:
                    overlapping_domain = [
                        ('appointment_date', '=', appointment.appointment_date),
                        ('status', 'not in', ('cancelled', 'done')),
                        ('start_time', '<', end_time),
                        ('end_time', '>', start_time),
                    ]
                    if appointment._origin.id:
                        overlapping_domain.append(
                            ('id', '!=', appointment._origin.id)
                        )
                    overlapping_domain.extend([
                        '|',
                        ('employee_id', 'in', list(eligible_employee_ids)),
                        ('appointment_line_ids.employee_id', 'in',
                         list(eligible_employee_ids)),
                    ])
                    overlapping_appointments = appointment_model.search(
                        overlapping_domain
                    )
                    busy_employee_ids = set(
                        overlapping_appointments.mapped('employee_id').ids
                    )
                    busy_employee_ids.update(
                        overlapping_appointments.mapped(
                            'appointment_line_ids.employee_id'
                        ).ids
                    )
                    eligible_employee_ids.difference_update(
                        busy_employee_ids
                    )

            line.available_employee_ids = [
                (6, 0, list(eligible_employee_ids))
            ]

    def _get_service_products(self):
        self.ensure_one()
        if self.product_id.type == 'service':
            return self.product_id
        if self.product_id.type == 'combo':
            return self.combo_choice_ids.mapped(
                'combo_item_id.product_id.product_tmpl_id'
            ).filtered(lambda product: product.type == 'service')
        return self.env['product.template']

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

    @api.constrains(
        'product_id',
        'combo_choice_ids',
        'duration_minutes',
        'employee_id',
    )
    def _check_combo_choices(self):
        for line in self:
            if (
                line.employee_id
                and line.employee_id not in line.available_employee_ids
            ):
                raise ValidationError(
                    f'Nhân viên {line.employee_id.name} không có ca, đang nghỉ, '
                    'bận lịch hoặc không được phân công cho dịch vụ này.'
                )
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
