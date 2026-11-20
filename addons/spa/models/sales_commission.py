from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class SpaSalesCommissionRule(models.Model):
    _name = 'spa.sales.commission.rule'
    _description = 'Thiết lập hoa hồng bán hàng Spa'

    name = fields.Char(
        string='Thiết lập',
        required=True,
        readonly=True,
        default='Hoa hồng bán sản phẩm',
    )
    rate = fields.Float(
        string='Tỷ lệ hoa hồng (%)',
        required=True,
        default=3.0,
        digits=(16, 2),
    )

    @api.constrains('rate')
    def _check_rate(self):
        for rule in self:
            if not 0 <= rule.rate <= 100:
                raise ValidationError(
                    'Tỷ lệ hoa hồng phải nằm trong khoảng từ 0 đến 100%.'
                )

    def write(self, vals):
        if set(vals) - {'name', 'rate'}:
            raise UserError(
                'Thiết lập hoa hồng chỉ gồm tên và tỷ lệ.'
            )
        return super().write(vals)

    def unlink(self):
        raise UserError('Không thể xóa thiết lập hoa hồng mặc định.')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    spa_sales_commission_id = fields.Many2one(
        'spa.sales.commission',
        string='Hoa hồng bán hàng',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )

    def _create_spa_sales_commissions_on_confirmation(self):
        commission_model = self.env['spa.sales.commission'].sudo()
        rate = self.env.ref(
            'spa.sales_commission_rule_default'
        ).sudo().rate
        if rate <= 0:
            return

        for order in self:
            sale_lines = order.order_line.filtered(
                lambda line: (
                    not line.display_type
                    and line.product_id.type in ('product', 'consu')
                    and line.spa_employee_id
                )
            )
            for line in sale_lines:
                if commission_model.search_count([
                    ('sale_order_line_id', '=', line.id),
                    ('state', '!=', 'cancelled'),
                ]):
                    continue
                commission_model.create({
                    'sale_order_id': order.id,
                    'sale_order_line_id': line.id,
                    'salesperson_id': order.user_id.id,
                    'employee_id': line.spa_employee_id.id,
                    'base_amount': line.price_subtotal,
                    'rate': rate,
                })

    def _get_spa_product_revenue_by_employee(self, invoices):
        self.ensure_one()
        revenue_by_employee = {}
        commissions = self.env['spa.sales.commission'].sudo().search([
            ('sale_order_id', '=', self.id),
            ('employee_id', '!=', False),
            '|',
            ('invoice_id', 'in', invoices.ids),
            ('invoice_ids', 'in', invoices.ids),
        ])
        for commission in commissions:
            employee_id = commission.employee_id.id
            revenue_by_employee[employee_id] = (
                revenue_by_employee.get(employee_id, 0.0)
                + commission.base_amount
            )
        commissioned_line_ids = commissions.invoice_line_id.ids
        commissioned_sale_line_ids = commissions.sale_order_line_id.ids
        for line in invoices.invoice_line_ids.filtered(
            lambda invoice_line: (
                invoice_line.display_type == 'product'
                and invoice_line.product_id.type in ('product', 'consu')
                and invoice_line.spa_employee_id
                and invoice_line.id not in commissioned_line_ids
                and not invoice_line.sale_line_ids.filtered(
                    lambda sale_line: (
                        sale_line.id in commissioned_sale_line_ids
                    )
                )
                and self in invoice_line.sale_line_ids.order_id
            )
        ):
            employee_id = line.spa_employee_id.id
            revenue_by_employee[employee_id] = (
                revenue_by_employee.get(employee_id, 0.0)
                + line.price_subtotal
            )
        return revenue_by_employee

    def _create_spa_sales_commission(self):
        commission_model = self.env['spa.sales.commission'].sudo()
        rate = self.env.ref(
            'spa.sales_commission_rule_default'
        ).sudo().rate

        for order in self:
            invoices = order.invoice_ids.filtered(
                lambda invoice: (
                    invoice.move_type == 'out_invoice'
                    and invoice.state != 'cancel'
                )
            )
            if not invoices or any(
                invoice.state != 'posted'
                or invoice.payment_state != 'paid'
                for invoice in invoices
            ):
                continue
            if order.invoice_status != 'invoiced':
                continue

            commissions = commission_model.search([
                ('sale_order_line_id', 'in', order.order_line.ids),
                ('state', '!=', 'cancelled'),
            ])
            for commission in commissions:
                sale_line = commission.sale_order_line_id
                linked_invoices = invoices.filtered(
                    lambda invoice: bool(
                        invoice.invoice_line_ids.sale_line_ids & sale_line
                    )
                )
                if linked_invoices:
                    commission.with_context(
                        spa_commission_invoice_sync=True
                    ).write({
                        'invoice_id': linked_invoices[:1].id,
                        'invoice_ids': [(6, 0, linked_invoices.ids)],
                    })

            invoice_lines = invoices.invoice_line_ids.filtered(
                lambda line: (
                    line.display_type == 'product'
                    and line.product_id.type in ('product', 'consu')
                    and line.spa_employee_id
                    and order in line.sale_line_ids.order_id
                )
            )
            for line in invoice_lines:
                if commission_model.search_count([
                    ('invoice_line_id', '=', line.id),
                ]):
                    continue
                if commission_model.search_count([
                    (
                        'sale_order_line_id',
                        'in',
                        line.sale_line_ids.ids,
                    ),
                    ('state', '!=', 'cancelled'),
                ]):
                    continue
                if rate <= 0:
                    continue
                commission_model.create({
                    'invoice_id': line.move_id.id,
                    'invoice_line_id': line.id,
                    'employee_id': line.spa_employee_id.id,
                    'sale_order_id': order.id,
                    'invoice_ids': [(6, 0, invoices.ids)],
                    'base_amount': line.price_subtotal,
                    'rate': rate,
                })


class SpaSalesCommission(models.Model):
    _name = 'spa.sales.commission'
    _description = 'Hoa hồng bán hàng Spa'
    _order = 'create_date desc, id desc'

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Đơn bán hàng',
        readonly=True,
        ondelete='set null',
        index=True,
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Dòng đơn bán hàng',
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Hóa đơn',
        readonly=True,
        ondelete='set null',
        index=True,
    )
    invoice_line_id = fields.Many2one(
        'account.move.line',
        string='Dòng sản phẩm',
        ondelete='restrict',
        index=True,
        domain="[('move_id', '=', invoice_id), ('display_type', '=', 'product'), ('product_id.type', 'in', ('product', 'consu'))]",
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'spa_sales_commission_invoice_rel',
        'commission_id',
        'invoice_id',
        string='Hóa đơn đã thanh toán',
        readonly=True,
    )
    salesperson_id = fields.Many2one(
        'res.users',
        string='Nhân viên kinh doanh',
        readonly=True,
        ondelete='set null',
    )
    employee_id = fields.Many2one(
        'hr.employee.public',
        string='Nhân viên được hưởng hoa hồng',
        ondelete='set null',
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        store=True,
        readonly=True,
    )
    base_amount = fields.Monetary(
        string='Doanh thu sản phẩm',
        currency_field='currency_id',
        required=True,
        readonly=True,
    )
    rate = fields.Float(
        string='Tỷ lệ (%)',
        required=True,
        readonly=True,
        digits=(16, 2),
    )
    commission_amount = fields.Monetary(
        string='Tiền hoa hồng',
        currency_field='currency_id',
        compute='_compute_commission_amount',
        store=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Chờ duyệt'),
            ('approved', 'Đã duyệt'),
            ('paid', 'Đã thanh toán'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        default='draft',
        required=True,
        readonly=True,
        index=True,
    )
    paid_date = fields.Date(
        string='Ngày thanh toán hoa hồng',
        readonly=True,
        copy=False,
    )

    _sql_constraints = [
        (
            'invoice_line_unique',
            'unique(invoice_line_id)',
            'Mỗi dòng sản phẩm chỉ được ghi nhận hoa hồng một lần.',
        ),
    ]

    @api.depends('invoice_id.currency_id', 'sale_order_id.currency_id')
    def _compute_currency_id(self):
        for commission in self:
            commission.currency_id = (
                commission.invoice_id.currency_id
                or commission.sale_order_id.currency_id
            )

    @api.model_create_multi
    def create(self, vals_list):
        rate = self.env.ref(
            'spa.sales_commission_rule_default'
        ).sudo().rate
        for vals in vals_list:
            sale_order_line = self.env['sale.order.line'].browse(
                vals.get('sale_order_line_id')
            )
            invoice_line = self.env['account.move.line'].browse(
                vals.get('invoice_line_id')
            )
            invoice = self.env['account.move'].browse(
                vals.get('invoice_id')
            ) or invoice_line.move_id
            if invoice_line:
                if invoice_line.move_id != invoice:
                    raise ValidationError(
                        'Dòng sản phẩm phải thuộc đúng hóa đơn.'
                    )
                if (
                    invoice_line.display_type != 'product'
                    or invoice_line.product_id.type not in ('product', 'consu')
                ):
                    raise ValidationError(
                        'Chỉ tính hoa hồng cho dòng sản phẩm bán lẻ.'
                    )
                if not vals.get('employee_id'):
                    raise ValidationError(
                        'Hãy chọn nhân viên cho dòng sản phẩm tính hoa hồng.'
                    )
                orders = invoice_line.sale_line_ids.order_id
                if len(orders) == 1:
                    vals.setdefault('sale_order_id', orders.id)
                vals.setdefault('base_amount', invoice_line.price_subtotal)
                vals.setdefault('invoice_ids', [(6, 0, [invoice.id])])
            if sale_order_line:
                if (
                    sale_order_line.display_type
                    or sale_order_line.product_id.type not in ('product', 'consu')
                ):
                    raise ValidationError(
                        'Chỉ tính hoa hồng cho dòng sản phẩm bán lẻ.'
                    )
                if not vals.get('employee_id'):
                    raise ValidationError(
                        'Hãy chọn nhân viên cho dòng sản phẩm tính hoa hồng.'
                    )
                vals.setdefault('sale_order_id', sale_order_line.order_id.id)
                vals.setdefault(
                    'salesperson_id',
                    sale_order_line.order_id.user_id.id,
                )
                vals.setdefault('base_amount', sale_order_line.price_subtotal)
            if invoice:
                vals.setdefault('invoice_id', invoice.id)
            vals.setdefault('rate', rate)
        commissions = super().create(vals_list)
        return commissions

    @api.constrains('base_amount', 'rate')
    def _check_amounts(self):
        for commission in self:
            if commission.base_amount < 0:
                raise ValidationError(
                    'Doanh thu tính hoa hồng không được âm.'
                )
            if not 0 <= commission.rate <= 100:
                raise ValidationError(
                    'Tỷ lệ hoa hồng phải nằm trong khoảng từ 0 đến 100%.'
                )

    @api.depends('base_amount', 'rate', 'currency_id')
    def _compute_commission_amount(self):
        for commission in self:
            amount = commission.base_amount * commission.rate / 100
            commission.commission_amount = (
                commission.currency_id.round(amount)
                if commission.currency_id
                else amount
            )

    def write(self, vals):
        if 'state' in vals and not self.env.context.get(
            'spa_commission_transition'
        ):
            raise UserError(
                'Hãy dùng các nút trạng thái để cập nhật hoa hồng.'
            )
        if set(vals) - {
            'state', 'paid_date', 'employee_id', 'invoice_line_id',
            'invoice_id', 'invoice_ids',
        }:
            raise UserError(
                'Thông tin hoa hồng đã được chốt và không thể chỉnh sửa.'
            )
        if set(vals) & {'invoice_id', 'invoice_ids'} and not self.env.context.get(
            'spa_commission_invoice_sync'
        ):
            raise UserError(
                'Thông tin hóa đơn hoa hồng chỉ được cập nhật tự động.'
            )
        if set(vals) & {'employee_id', 'invoice_line_id'} and any(
            commission.state != 'draft' for commission in self
        ):
            raise UserError(
                'Chỉ có thể sửa phân công khi hoa hồng đang chờ duyệt.'
            )
        if 'invoice_line_id' in vals:
            line = self.env['account.move.line'].browse(
                vals['invoice_line_id']
            )
            for commission in self:
                if line.move_id != commission.invoice_id:
                    raise ValidationError(
                        'Dòng sản phẩm phải thuộc đúng hóa đơn.'
                    )
                if (
                    line.display_type != 'product'
                    or line.product_id.type not in ('product', 'consu')
                ):
                    raise ValidationError(
                        'Chỉ tính hoa hồng cho dòng sản phẩm bán lẻ.'
                    )
            vals = dict(
                vals,
                base_amount=line.price_subtotal,
                sale_order_id=(
                    line.sale_line_ids.order_id[:1].id or False
                ),
            )
        return super().write(vals)

    def unlink(self):
        raise UserError('Không thể xóa khoản hoa hồng đã được ghi nhận.')

    def _check_manager(self):
        if not self.env.user.has_group(
            'spa.group_customer_management_manager'
        ):
            raise AccessError(
                'Chỉ quản lý mới được cập nhật trạng thái hoa hồng.'
            )

    def action_approve(self):
        self._check_manager()
        if any(commission.state != 'draft' for commission in self):
            raise UserError(
                'Chỉ có thể duyệt khoản hoa hồng đang chờ duyệt.'
            )
        if any(
            (
                commission.sale_order_line_id
                and not commission.invoice_ids
            )
            or any(
                invoice.state != 'posted' or invoice.payment_state != 'paid'
                for invoice in (commission.invoice_ids | commission.invoice_id)
            )
            for commission in self
        ):
            raise UserError(
                'Chỉ có thể duyệt hoa hồng của hóa đơn đã thanh toán.'
            )
        self.with_context(spa_commission_transition=True).write({
            'state': 'approved',
        })

    def action_mark_paid(self):
        self._check_manager()
        if any(commission.state != 'approved' for commission in self):
            raise UserError(
                'Chỉ có thể thanh toán khoản hoa hồng đã được duyệt.'
            )
        self.with_context(spa_commission_transition=True).write({
            'state': 'paid',
            'paid_date': fields.Date.context_today(self),
        })

    def action_cancel(self):
        self._check_manager()
        if any(
            commission.state not in ('draft', 'approved')
            for commission in self
        ):
            raise UserError(
                'Chỉ có thể hủy khoản hoa hồng đang chờ duyệt hoặc đã duyệt.'
            )
        self.with_context(spa_commission_transition=True).write({
            'state': 'cancelled',
        })


class AccountMove(models.Model):
    _inherit = 'account.move'

    spa_sales_commission_ids = fields.One2many(
        'spa.sales.commission',
        'invoice_id',
        string='Nhân viên tính hoa hồng',
    )

    def _create_spa_sales_commissions(self):
        orders = self.invoice_line_ids.sale_line_ids.order_id
        orders.sudo()._create_spa_sales_commission()
