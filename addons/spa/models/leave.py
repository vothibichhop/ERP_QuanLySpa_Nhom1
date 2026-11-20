from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class SpaLeaveRequest(models.Model):
    _name = 'spa.leave.request'
    _description = 'Nghỉ phép nhân viên Spa'
    _order = 'start_date desc, employee_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Nhân viên',
        required=True,
        ondelete='restrict',
        index=True,
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Vị trí công việc',
        related='employee_id.job_id',
        store=True,
        readonly=True,
    )
    leave_type = fields.Selection(
        [
            ('annual', 'Nghỉ phép năm'),
            ('sick', 'Nghỉ ốm'),
            ('personal', 'Nghỉ cá nhân'),
            ('other', 'Nghỉ khác'),
        ],
        string='Loại nghỉ',
        required=True,
        default='annual',
        index=True,
    )
    start_date = fields.Date(
        string='Ngày bắt đầu',
        required=True,
        index=True,
    )
    end_date = fields.Date(
        string='Ngày kết thúc',
        required=True,
        index=True,
    )
    start_session = fields.Selection(
        [
            ('morning', 'Buổi sáng'),
            ('afternoon', 'Buổi chiều'),
        ],
        string='Buổi bắt đầu',
        required=True,
        default='morning',
    )
    end_session = fields.Selection(
        [
            ('morning', 'Buổi sáng'),
            ('afternoon', 'Buổi chiều'),
        ],
        string='Buổi kết thúc',
        required=True,
        default='afternoon',
    )
    reason = fields.Text(string='Lý do nghỉ')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'spa_leave_request_attachment_rel',
        'leave_id',
        'attachment_id',
        string='Tệp đính kèm',
    )
    approver_id = fields.Many2one(
        'res.users',
        string='Người duyệt',
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('submitted', 'Chờ duyệt'),
            ('approved', 'Đã duyệt'),
            ('refused', 'Từ chối'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        required=True,
        default='draft',
        copy=False,
        index=True,
    )
    duration_days = fields.Integer(
        string='Số ngày',
        compute='_compute_duration_days',
        store=True,
    )
    total_sessions = fields.Integer(
        string='Tổng số buổi nghỉ',
        compute='_compute_total_sessions',
        store=True,
    )

    _STATE_TRANSITIONS = {
        'draft': {'submitted', 'cancelled'},
        'submitted': {'approved', 'refused', 'cancelled'},
        'approved': {'cancelled'},
        'refused': set(),
        'cancelled': set(),
    }
    _REQUEST_FIELDS = {
        'employee_id',
        'leave_type',
        'start_date',
        'end_date',
        'start_session',
        'end_session',
        'reason',
        'attachment_ids',
    }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            initial_state = vals.get(
                'state',
                self.env.context.get('default_state', 'draft'),
            )
            if initial_state != 'draft':
                raise UserError(
                    'Đơn nghỉ phép mới phải bắt đầu ở trạng thái nháp.'
                )
        return super().create(vals_list)

    @api.depends('start_date', 'end_date')
    def _compute_duration_days(self):
        for leave in self:
            if leave.start_date and leave.end_date:
                leave.duration_days = (leave.end_date - leave.start_date).days + 1
            else:
                leave.duration_days = 0

    @api.depends(
        'start_date',
        'end_date',
        'start_session',
        'end_session',
    )
    def _compute_total_sessions(self):
        for leave in self:
            if not leave.start_date or not leave.end_date:
                leave.total_sessions = 0
                continue
            sessions = ((leave.end_date - leave.start_date).days + 1) * 2
            if leave.start_session == 'afternoon':
                sessions -= 1
            if leave.end_session == 'morning':
                sessions -= 1
            leave.total_sessions = sessions

    @api.constrains(
        'start_date',
        'end_date',
        'start_session',
        'end_session',
    )
    def _check_leave_dates_and_sessions(self):
        for leave in self:
            if leave.start_date and leave.end_date and leave.start_date > leave.end_date:
                raise ValidationError('Ngày kết thúc phải sau hoặc bằng ngày bắt đầu.')
            if (
                leave.start_date
                and leave.start_date == leave.end_date
                and leave.start_session == 'afternoon'
                and leave.end_session == 'morning'
            ):
                raise ValidationError(
                    'Buổi kết thúc phải bằng hoặc sau buổi bắt đầu.'
                )

    @api.constrains(
        'employee_id',
        'start_date',
        'end_date',
        'start_session',
        'end_session',
        'state',
    )
    def _check_employee_leave_overlap(self):
        for leave in self:
            if leave.state in ('draft', 'refused', 'cancelled'):
                continue
            overlapping_leaves = self.search(
                [
                    ('id', '!=', leave.id),
                    ('employee_id', '=', leave.employee_id.id),
                    ('state', 'in', ('submitted', 'approved')),
                    ('start_date', '<=', leave.end_date),
                    ('end_date', '>=', leave.start_date),
                ]
            )
            overlapping_leave = overlapping_leaves.filtered(
                lambda other: (
                    self._session_slot(other.start_date, other.start_session)
                    <= self._session_slot(leave.end_date, leave.end_session)
                    and self._session_slot(other.end_date, other.end_session)
                    >= self._session_slot(leave.start_date, leave.start_session)
                )
            )[:1]
            if overlapping_leave:
                raise ValidationError(
                    'Nhân viên đã có đơn nghỉ phép trùng thời gian.'
                )

    @staticmethod
    def _session_slot(date, session):
        return date.toordinal() * 2 + int(session == 'afternoon')

    def write(self, vals):
        target_state = vals.get('state')
        vals = dict(vals)
        if target_state in ('approved', 'refused') and any(
            leave.state != target_state for leave in self
        ):
            vals['approver_id'] = self.env.user.id
        if 'approver_id' in vals and (
            target_state not in ('approved', 'refused')
            or any(leave.state != 'submitted' for leave in self)
            or vals['approver_id'] != self.env.user.id
        ):
            raise UserError(
                'Người duyệt chỉ được ghi nhận khi duyệt hoặc từ chối đơn.'
            )
        if self._REQUEST_FIELDS.intersection(vals):
            if any(
                leave.state != 'draft'
                or (target_state and target_state != 'draft')
                for leave in self
            ):
                raise UserError(
                    'Không thể sửa nội dung đơn nghỉ phép sau khi gửi duyệt.'
                )
        if target_state:
            for leave in self:
                if target_state == leave.state:
                    continue
                if target_state not in self._STATE_TRANSITIONS[leave.state]:
                    raise UserError(
                        'Không thể chuyển đơn nghỉ phép từ trạng thái '
                        f'{leave.state} sang {target_state}.'
                    )
                if target_state in ('approved', 'refused') or (
                    leave.state == 'approved' and target_state == 'cancelled'
                ):
                    if not self._is_leave_manager():
                        raise AccessError(
                            'Chỉ quản lý mới được duyệt, từ chối hoặc hủy '
                            'đơn nghỉ phép đã duyệt.'
                        )
        return super().write(vals)

    def _is_leave_manager(self):
        return (
            self.env.user.has_group(
                'spa.group_customer_management_manager'
            )
            or self.env.user.has_group('hr.group_hr_manager')
        )

    def action_submit(self):
        self._transition_state('draft', 'submitted')

    def action_approve(self):
        self._transition_state('submitted', 'approved')

    def action_refuse(self):
        self._transition_state('submitted', 'refused')

    def action_cancel(self):
        for leave in self:
            if leave.state not in ('draft', 'submitted', 'approved'):
                raise UserError(
                    'Chỉ có thể hủy đơn nghỉ phép đang nháp, đã gửi hoặc '
                    'đã duyệt.'
                )
        self.write({'state': 'cancelled'})

    def _transition_state(self, expected_state, target_state):
        for leave in self:
            if leave.state != expected_state:
                raise UserError(
                    f'Chỉ có thể chuyển đơn nghỉ phép từ trạng thái '
                    f'{expected_state}.'
                )
        self.write({'state': target_state})
