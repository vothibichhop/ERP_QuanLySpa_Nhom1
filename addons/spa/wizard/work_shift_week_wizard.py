from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_WEEKDAY_NAMES = (
    'Thứ Hai',
    'Thứ Ba',
    'Thứ Tư',
    'Thứ Năm',
    'Thứ Sáu',
    'Thứ Bảy',
    'Chủ nhật',
)


class SpaWorkShiftWeekWizard(models.TransientModel):
    _name = 'spa.work.shift.week.wizard'
    _description = 'Xếp ca làm việc theo tuần'

    start_date = fields.Date(
        string='Ngày bắt đầu',
        required=True,
        default=fields.Date.context_today,
        help='Chọn ngày đầu tiên; lịch sẽ bao gồm 7 ngày liên tiếp.',
    )
    end_date = fields.Date(
        string='Ngày kết thúc',
        compute='_compute_end_date',
    )
    line_ids = fields.One2many(
        'spa.work.shift.week.wizard.line',
        'wizard_id',
        string='Phân công theo ngày',
    )

    @api.depends('start_date')
    def _compute_end_date(self):
        for wizard in self:
            wizard.end_date = (
                wizard.start_date + timedelta(days=6)
                if wizard.start_date
                else False
            )

    @api.model
    def _prepare_week_lines(self, start_date):
        start_date = fields.Date.to_date(start_date)
        end_date = start_date + timedelta(days=6)
        shifts = self.env['spa.work.shift'].search([
            ('work_date', '>=', start_date),
            ('work_date', '<=', end_date),
            ('state', '=', 'scheduled'),
            ('auto_generated', '=', False),
        ])
        employee_ids_by_date = defaultdict(set)
        for shift in shifts:
            employee_ids_by_date[shift.work_date].update(
                shift.employee_ids.ids
            )

        lines = []
        for offset in range(7):
            work_date = start_date + timedelta(days=offset)
            line_values = {
                'day_offset': offset,
                'work_date': work_date,
            }
            employee_ids = sorted(employee_ids_by_date[work_date])
            if employee_ids:
                line_values['employee_ids'] = [
                    fields.Command.set(employee_ids)
                ]
            lines.append(fields.Command.create(line_values))
        return lines

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'line_ids' in fields_list and not values.get('line_ids'):
            start_date = values.get('start_date') or fields.Date.context_today(self)
            values['line_ids'] = self._prepare_week_lines(start_date)
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get('line_ids'):
                start_date = values.get('start_date') or fields.Date.context_today(self)
                values['line_ids'] = self._prepare_week_lines(start_date)
        return super().create(vals_list)

    @api.onchange('start_date')
    def _onchange_start_date(self):
        for wizard in self:
            if wizard.start_date:
                wizard.line_ids = [
                    fields.Command.clear(),
                    *self._prepare_week_lines(wizard.start_date),
                ]
            else:
                wizard.line_ids = [fields.Command.clear()]

    def action_apply(self):
        self.ensure_one()
        start_date = fields.Date.to_date(self.start_date)
        today = fields.Date.context_today(self)
        if not start_date or start_date < today:
            raise UserError(_('Ngày bắt đầu không được nằm trong quá khứ.'))

        lines = self.line_ids.sorted('day_offset')
        if len(lines) != 7 or any(
            line.day_offset != offset
            or line.work_date != start_date + timedelta(days=offset)
            for offset, line in enumerate(lines)
        ):
            raise UserError(
                _('Lịch tuần phải có đủ 7 ngày liên tiếp từ ngày bắt đầu.')
            )
        if not any(lines.mapped('employee_ids')):
            raise UserError(
                _('Hãy chọn nhân viên cho ít nhất một ngày trong tuần.')
            )

        shift_model = self.env['spa.work.shift']
        end_date = start_date + timedelta(days=6)
        completed_shifts = shift_model.search([
            ('work_date', '>=', start_date),
            ('work_date', '<=', end_date),
            ('state', '=', 'completed'),
            ('auto_generated', '=', False),
        ])
        if completed_shifts:
            dates = ', '.join(
                sorted(
                    fields.Date.to_string(work_date)
                    for work_date in set(
                        completed_shifts.mapped('work_date')
                    )
                )
            )
            raise UserError(
                _('Không thể thay đổi lịch tuần vì đã có ca hoàn thành vào: %s')
                % dates
            )

        new_shifts = []
        for line in lines:
            existing_shifts = shift_model.search([
                ('work_date', '=', line.work_date),
                ('state', '=', 'scheduled'),
                ('auto_generated', '=', False),
            ])
            if existing_shifts:
                existing_shifts.write({'state': 'cancelled'})
            if line.employee_ids:
                new_shifts.append({
                    'name': '%s - %s' % (
                        line.weekday_name,
                        line.work_date.strftime('%d/%m/%Y'),
                    ),
                    'work_date': line.work_date,
                    'employee_ids': [
                        fields.Command.set(line.employee_ids.ids)
                    ],
                })
        if new_shifts:
            shift_model.create(new_shifts)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Ca làm việc trong tuần'),
            'res_model': 'spa.work.shift',
            'view_mode': 'calendar,list,form',
            'domain': [
                ('work_date', '>=', start_date),
                ('work_date', '<=', end_date),
                ('state', '=', 'scheduled'),
                ('auto_generated', '=', False),
            ],
            'target': 'current',
        }


class SpaWorkShiftWeekWizardLine(models.TransientModel):
    _name = 'spa.work.shift.week.wizard.line'
    _description = 'Phân công nhân viên theo ngày trong tuần'
    _order = 'day_offset'

    wizard_id = fields.Many2one(
        'spa.work.shift.week.wizard',
        required=True,
        ondelete='cascade',
    )
    day_offset = fields.Integer(required=True, readonly=True)
    work_date = fields.Date(string='Ngày', required=True, readonly=True)
    weekday_name = fields.Char(
        string='Thứ',
        compute='_compute_weekday_name',
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Nhân viên làm ca',
        domain=[('active', '=', True)],
    )

    @api.model_create_multi
    def create(self, vals_list):
        next_offsets = {}
        wizard_model = self.env['spa.work.shift.week.wizard']
        for values in vals_list:
            wizard_id = values.get('wizard_id')
            if not wizard_id:
                continue

            wizard = wizard_model.browse(wizard_id)
            work_date = fields.Date.to_date(values.get('work_date'))
            if values.get('day_offset') is not None:
                day_offset = values['day_offset']
            elif work_date:
                day_offset = (work_date - wizard.start_date).days
            else:
                if wizard_id not in next_offsets:
                    next_offsets[wizard_id] = self.search_count([
                        ('wizard_id', '=', wizard_id),
                    ])
                day_offset = next_offsets[wizard_id]

            if values.get('day_offset') is None:
                values['day_offset'] = day_offset
            if not work_date:
                values['work_date'] = (
                    wizard.start_date + timedelta(days=day_offset)
                )
            next_offsets[wizard_id] = day_offset + 1
        return super().create(vals_list)

    @api.depends('work_date')
    def _compute_weekday_name(self):
        for line in self:
            line.weekday_name = (
                _WEEKDAY_NAMES[line.work_date.weekday()]
                if line.work_date
                else False
            )
