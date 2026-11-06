from datetime import datetime, time

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SpaWorkShift(models.Model):
    _name = 'spa.work.shift'
    _description = 'Ca làm việc'
    _order = 'start_datetime'

    name = fields.Char(string='Tên ca', required=True)
    work_date = fields.Date(
        string='Ngày làm việc',
        compute='_compute_work_date',
        inverse='_inverse_work_date',
        store=True,
        required=True,
        index=True,
    )
    shift_type = fields.Selection(
        [('full_day', 'Cả ngày')],
        string='Loại ca',
        required=True,
        default='full_day',
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        'spa_work_shift_employee_rel',
        'shift_id',
        'employee_id',
        string='Nhân viên',
        required=True,
    )
    start_datetime = fields.Datetime(
        string='Bắt đầu',
        required=True,
        index=True,
        default=lambda self: self._shift_datetime(
            fields.Date.context_today(self), time(7),
        ),
    )
    end_datetime = fields.Datetime(
        string='Kết thúc',
        required=True,
        index=True,
        default=lambda self: self._shift_datetime(
            fields.Date.context_today(self), time(19),
        ),
    )
    state = fields.Selection(
        [
            ('scheduled', 'Đã xếp lịch'),
            ('completed', 'Đã hoàn thành'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        required=True,
        default='scheduled',
        index=True,
    )
    auto_generated = fields.Boolean(default=False, copy=False)
    notes = fields.Text(string='Ghi chú')

    def _shift_datetime(self, work_date, shift_time):
        timezone = pytz.timezone(
            self.env.context.get('tz') or self.env.user.tz or 'UTC'
        )
        local_datetime = timezone.localize(
            datetime.combine(fields.Date.to_date(work_date), shift_time)
        )
        return local_datetime.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.depends('start_datetime')
    def _compute_work_date(self):
        for shift in self:
            shift.work_date = (
                fields.Datetime.to_datetime(shift.start_datetime).date()
                if shift.start_datetime else False
            )

    def _inverse_work_date(self):
        for shift in self:
            if shift.work_date:
                shift.start_datetime = self._shift_datetime(
                    shift.work_date, time(7)
                )
                shift.end_datetime = self._shift_datetime(
                    shift.work_date, time(19)
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('work_date'):
                work_date = fields.Date.to_date(vals['work_date'])
                vals.setdefault(
                    'start_datetime', self._shift_datetime(work_date, time(7))
                )
                vals.setdefault(
                    'end_datetime', self._shift_datetime(work_date, time(19))
                )
        return super().create(vals_list)

    @api.constrains('start_datetime', 'end_datetime', 'shift_type')
    def _check_datetime_order(self):
        for shift in self:
            if not shift.start_datetime or not shift.end_datetime:
                continue
            start = fields.Datetime.context_timestamp(
                shift, shift.start_datetime
            )
            end = fields.Datetime.context_timestamp(
                shift, shift.end_datetime
            )
            if (
                shift.shift_type != 'full_day'
                or start.date() != end.date()
                or start.time().replace(tzinfo=None) != time(7)
                or end.time().replace(tzinfo=None) != time(19)
            ):
                raise ValidationError(
                    'Ca làm việc phải là ca cả ngày từ 07:00 đến 19:00.'
                )

    @api.constrains(
        'employee_ids',
        'start_datetime',
        'end_datetime',
        'work_date',
        'state',
    )
    def _check_employee_overlap(self):
        for shift in self:
            if shift.state == 'cancelled':
                continue
            if not shift.employee_ids:
                raise ValidationError('Ca làm việc phải có ít nhất một nhân viên.')

            for employee in shift.employee_ids:
                leave_request = self.env['spa.leave.request'].search(
                    [
                        ('employee_id', '=', employee.id),
                        ('state', 'in', ('submitted', 'approved')),
                        ('start_date', '<=', shift.work_date),
                        ('end_date', '>=', shift.work_date),
                    ],
                    limit=1,
                )
                if leave_request:
                    raise ValidationError(
                        f'Nhân viên {employee.name} đang nghỉ phép từ '
                        f'{leave_request.start_date} đến {leave_request.end_date}. '
                        'Không thể xếp ca làm việc trong khoảng thời gian này.'
                    )

                overlapping_shift = self.search(
                    [
                        ('id', '!=', shift.id),
                        ('employee_ids', '=', employee.id),
                        ('state', '!=', 'cancelled'),
                        ('start_datetime', '<', shift.end_datetime),
                        ('end_datetime', '>', shift.start_datetime),
                    ],
                    limit=1,
                )
                if overlapping_shift:
                    raise ValidationError(
                        f'Nhân viên {employee.name} đã có ca làm việc trùng thời gian này.'
                    )

    @api.model
    def _cron_create_daily_guard_shift(self):
        work_date = fields.Date.context_today(self)
        if self.search_count([
            ('work_date', '=', work_date),
            ('auto_generated', '=', True),
        ]):
            return

        guards = self.env['hr.employee'].search([
            ('active', '=', True),
            '|',
            ('job_title', 'ilike', 'bảo vệ'),
            ('job_id.name', 'ilike', 'bảo vệ'),
        ])
        if not guards:
            return

        self.create({
            'name': f'Ca bảo vệ {work_date.strftime("%d/%m/%Y")}',
            'work_date': work_date,
            'employee_ids': [(6, 0, guards.ids)],
            'auto_generated': True,
        })
