from odoo import api, fields, models
from odoo.exceptions import UserError

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    spa_service_ids = fields.Many2many(
        'product.template',
        'spa_employee_service_rel',
        'employee_id',
        'product_id',
        string='Dịch vụ có thể thực hiện',
    )
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
    shift_ids = fields.Many2many(
        'spa.work.shift',
        'spa_work_shift_employee_rel',
        'employee_id',
        'shift_id',
        string='Lịch ca làm việc',
    )
    leave_ids = fields.One2many(
        'spa.leave.request',
        'employee_id',
        string='Nghỉ phép',
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
    spa_sales_commission_order_count = fields.Integer(
        string='Đơn hàng có hoa hồng',
        compute='_compute_spa_sales_commission_order_count',
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

    def _compute_spa_sales_commission_order_count(self):
        SaleOrderLine = self.env['sale.order.line']
        for employee in self:
            lines = SaleOrderLine.search([
                ('spa_employee_id', '=', employee.id),
                ('display_type', '=', 'product'),
                ('product_id.type', 'in', ('product', 'consu')),
                ('order_id.state', 'in', ('sale', 'done')),
            ])
            employee.spa_sales_commission_order_count = len(
                lines.mapped('order_id')
            )

    def action_spa_view_sales_orders(self):
        self.ensure_one()
        if not (
            self.env.user.has_group(
                'spa.group_customer_management_manager'
            )
            or self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(
                'Chỉ quản lý mới được xem danh sách đơn hàng và hoa hồng.'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đơn hàng bán được - %s' % self.name,
            'res_model': 'sale.order.line',
            'view_mode': 'list',
            'views': [(
                self.env.ref(
                    'spa.view_spa_employee_sales_order_line_list'
                ).id,
                'list',
            )],
            'domain': [
                ('spa_employee_id', '=', self.id),
                ('display_type', '=', 'product'),
                ('product_id.type', 'in', ('product', 'consu')),
                ('order_id.state', 'in', ('sale', 'done')),
            ],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
                'group_by': 'order_id',
            },
        }

    def action_spa_view_sales_commissions(self):
        self.ensure_one()
        action = self.action_spa_view_sales_orders()
        action['name'] = 'Hoa hồng - %s' % self.name
        return action

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


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    spa_service_ids = fields.Many2many(
        'product.template',
        'spa_employee_service_rel',
        'employee_id',
        'product_id',
        string='Dịch vụ có thể thực hiện',
    )
