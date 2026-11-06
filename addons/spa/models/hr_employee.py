from odoo import api, fields, models
from odoo.exceptions import UserError

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    employee_code = fields.Char(
        string='Mã nhân viên',
        readonly=True,
        copy=False,
        index=True,
    )
    start_work_date = fields.Date(
        string='Ngày bắt đầu làm',
        default=fields.Date.context_today,
    )
    employment_status = fields.Selection(
        [
            ('working', 'Đang làm'),
            ('resigned', 'Đã nghỉ'),
        ],
        string='Trạng thái nhân viên',
        compute='_compute_employment_status',
        inverse='_inverse_employment_status',
        store=True,
    )

    _sql_constraints = [
        (
            'employee_code_unique',
            'unique(employee_code)',
            'Mã nhân viên không được trùng.',
        ),
    ]

    @api.depends('active')
    def _compute_employment_status(self):
        for employee in self:
            employee.employment_status = (
                'working' if employee.active else 'resigned'
            )

    def _inverse_employment_status(self):
        for employee in self:
            employee.active = employee.employment_status == 'working'

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('employee_code'):
                code = sequence.next_by_code('spa.employee')
                if not code:
                    raise UserError(
                        'Không tìm thấy sequence tạo mã nhân viên Spa.'
                    )
                vals['employee_code'] = code
        return super().create(vals_list)
