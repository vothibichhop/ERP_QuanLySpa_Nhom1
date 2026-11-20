from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command


class SpaTreatmentPackage(models.Model):
    _name = 'spa.treatment.package'
    _description = 'Gói liệu trình Spa'
    _order = 'name, id'

    name = fields.Char(string='Tên gói liệu trình', required=True)
    active = fields.Boolean(string='Đang kinh doanh', default=True)
    state = fields.Selection(
        [
            ('active', 'Đang hoạt động'),
            ('inactive', 'Ngừng kinh doanh'),
        ],
        string='Trạng thái',
        compute='_compute_state',
        inverse='_inverse_state',
        store=True,
    )
    price = fields.Monetary(
        string='Giá gói',
        required=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    product_id = fields.Many2one(
        'product.template',
        string='Sản phẩm bán hàng',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    validity_days = fields.Integer(
        string='Thời hạn (ngày)',
        help='Để 0 nếu gói không có ngày hết hạn.',
    )
    description = fields.Text(string='Mô tả')
    line_ids = fields.One2many(
        'spa.treatment.package.line',
        'package_id',
        string='Dịch vụ trong gói',
        help='Thêm một dòng cho từng dịch vụ khác nhau trong gói.',
        copy=True,
    )

    @api.depends('active')
    def _compute_state(self):
        for package in self:
            package.state = 'active' if package.active else 'inactive'

    def _inverse_state(self):
        for package in self:
            package.active = package.state == 'active'

    @api.constrains('validity_days', 'price', 'line_ids')
    def _check_package_configuration(self):
        for package in self:
            if package.validity_days < 0:
                raise ValidationError('Thời hạn gói không được là số âm.')
            if package.price < 0:
                raise ValidationError('Giá gói không được là số âm.')
            if not package.line_ids:
                raise ValidationError(
                    'Gói liệu trình phải có ít nhất một dịch vụ.'
                )

    def _get_product_sales_description(self):
        self.ensure_one()
        services = '\n'.join(
            '- %s: %s buổi' % (line.product_id.display_name, line.session_count)
            for line in self.line_ids
        )
        included_services = 'Dịch vụ trong gói:\n%s' % services
        return '\n\n'.join(
            value for value in (self.description, included_services) if value
        )

    def _sync_product_sales_description(self):
        for package in self.filtered('product_id'):
            package.product_id.write({
                'description_sale': package._get_product_sales_description(),
            })

    @api.model_create_multi
    def create(self, vals_list):
        packages = super().create(vals_list)
        for package in packages:
            if not package.product_id:
                product = self.env['product.template'].create({
                    'name': package.name,
                    'type': 'service',
                    'sale_ok': True,
                    'purchase_ok': False,
                    'list_price': package.price,
                    'description_sale': package._get_product_sales_description(),
                    'spa_treatment_package_id': package.id,
                })
                package.product_id = product
        packages._sync_product_sales_description()
        return packages

    def write(self, vals):
        result = super().write(vals)
        product_values = {}
        if 'name' in vals:
            product_values['name'] = vals['name']
        if 'price' in vals:
            product_values['list_price'] = vals['price']
        if 'active' in vals:
            product_values['active'] = vals['active']
        if product_values:
            self.mapped('product_id').write(product_values)
        self._sync_product_sales_description()
        return result


class SpaTreatmentPackageLine(models.Model):
    _name = 'spa.treatment.package.line'
    _description = 'Dịch vụ trong gói liệu trình'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    package_id = fields.Many2one(
        'spa.treatment.package',
        string='Gói liệu trình',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.template',
        string='Dịch vụ hoặc combo',
        required=True,
        domain=[
            ('type', 'in', ('service', 'combo')),
            ('spa_treatment_package_id', '=', False),
        ],
        ondelete='restrict',
    )
    session_count = fields.Integer(
        string='Số buổi',
        required=True,
        default=1,
    )

    _sql_constraints = [
        (
            'package_product_unique',
            'unique(package_id, product_id)',
            'Mỗi dịch vụ chỉ được thêm một lần vào một gói.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.mapped('package_id')._sync_product_sales_description()
        return lines

    def write(self, vals):
        packages = self.mapped('package_id')
        result = super().write(vals)
        (packages | self.mapped('package_id'))._sync_product_sales_description()
        return result

    def unlink(self):
        packages = self.mapped('package_id')
        result = super().unlink()
        packages._sync_product_sales_description()
        return result

    @api.constrains('session_count', 'product_id')
    def _check_session_count(self):
        for line in self:
            if line.session_count < 1:
                raise ValidationError(
                    'Số buổi của mỗi dịch vụ phải ít nhất là 1.'
                )
            if line.product_id.type not in ('service', 'combo'):
                raise ValidationError(
                    'Gói liệu trình chỉ bao gồm dịch vụ hoặc combo Spa.'
                )
            if line.product_id.spa_treatment_package_id:
                raise ValidationError(
                    'Không thể thêm một gói liệu trình khác làm dịch vụ con.'
                )


class SpaCustomerPackage(models.Model):
    _name = 'spa.customer.package'
    _description = 'Gói liệu trình của khách hàng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'purchase_date desc, id desc'

    name = fields.Char(
        string='Mã gói khách hàng',
        required=True,
        readonly=True,
        copy=False,
        default='Mới',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Khách hàng',
        required=True,
        index=True,
        ondelete='restrict',
        tracking=True,
    )
    package_id = fields.Many2one(
        'spa.treatment.package',
        string='Gói liệu trình',
        required=True,
        domain=[('active', '=', True)],
        ondelete='restrict',
        tracking=True,
    )
    purchase_date = fields.Date(
        string='Ngày mua',
        required=True,
        default=fields.Date.context_today,
    )
    start_date = fields.Date(
        string='Ngày bắt đầu',
        required=True,
        default=fields.Date.context_today,
    )
    price = fields.Monetary(
        string='Giá bán gói',
        currency_field='currency_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Tiền tệ',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    validity_days = fields.Integer(
        string='Thời hạn (ngày)',
        readonly=True,
    )
    expiration_date = fields.Date(
        string='Ngày hết hạn',
        compute='_compute_expiration_date',
        store=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Đơn bán hàng',
        ondelete='restrict',
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Dòng đơn bán hàng',
        ondelete='restrict',
        copy=False,
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Nhân viên phụ trách',
        default=lambda self: self.env.user,
    )
    line_ids = fields.One2many(
        'spa.customer.package.line',
        'customer_package_id',
        string='Số buổi trong gói',
        copy=False,
    )
    session_count = fields.Integer(
        string='Tổng số buổi',
        compute='_compute_session_totals',
    )
    used_session_count = fields.Integer(
        string='Đã sử dụng',
        compute='_compute_session_totals',
    )
    remaining_session_count = fields.Integer(
        string='Còn lại',
        compute='_compute_session_totals',
    )
    cancelled = fields.Boolean(default=False, copy=False)
    state = fields.Selection(
        [
            ('active', 'Đang sử dụng'),
            ('completed', 'Đã sử dụng hết'),
            ('expired', 'Hết hạn'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        compute='_compute_state',
    )
    note = fields.Text(string='Ghi chú')

    @api.depends('start_date', 'validity_days')
    def _compute_expiration_date(self):
        for record in self:
            record.expiration_date = (
                record.start_date + timedelta(days=record.validity_days - 1)
                if record.start_date and record.validity_days
                else False
            )

    @api.depends(
        'line_ids.session_count',
        'line_ids.used_session_count',
    )
    def _compute_session_totals(self):
        for record in self:
            record.session_count = sum(record.line_ids.mapped('session_count'))
            record.used_session_count = sum(
                record.line_ids.mapped('used_session_count')
            )
            record.remaining_session_count = (
                record.session_count - record.used_session_count
            )

    @api.depends(
        'cancelled',
        'expiration_date',
        'start_date',
        'remaining_session_count',
    )
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.cancelled:
                record.state = 'cancelled'
            elif (
                record.expiration_date
                and record.expiration_date < today
            ):
                record.state = 'expired'
            elif record.remaining_session_count == 0:
                record.state = 'completed'
            else:
                record.state = 'active'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            package = self.env['spa.treatment.package'].browse(
                vals.get('package_id')
            )
            if package and not package.active:
                raise ValidationError(
                    'Không thể tạo gói khách hàng từ gói đã ngừng kinh doanh.'
                )
            if package and 'validity_days' not in vals:
                vals['validity_days'] = package.validity_days
            if package and 'price' not in vals:
                vals['price'] = package.price
            if package and 'currency_id' not in vals:
                vals['currency_id'] = package.currency_id.id
            if package and not vals.get('line_ids'):
                vals['line_ids'] = [
                    Command.create({
                        'source_line_id': line.id,
                        'product_id': line.product_id.id,
                        'session_count': line.session_count,
                    })
                    for line in package.line_ids
                ]
        records = super().create(vals_list)
        for record in records:
            if record.name == 'Mới':
                record.name = self.env['ir.sequence'].next_by_code(
                    'spa.customer.package'
                ) or 'Mới'
        return records

    @api.constrains(
        'purchase_date',
        'start_date',
        'validity_days',
        'package_id',
        'line_ids',
        'sale_order_id',
    )
    def _check_package_dates_and_lines(self):
        for record in self:
            if record.start_date < record.purchase_date:
                raise ValidationError(
                    'Ngày bắt đầu không được trước ngày mua gói.'
                )
            if record.validity_days < 0:
                raise ValidationError('Thời hạn gói không được là số âm.')
            if not record.line_ids:
                raise ValidationError(
                    'Gói khách hàng phải có ít nhất một dịch vụ.'
                )
            if (
                record.sale_order_id
                and record.sale_order_id.partner_id.commercial_partner_id
                != record.partner_id.commercial_partner_id
            ):
                raise ValidationError(
                    'Đơn bán hàng phải thuộc khách hàng sở hữu gói.'
                )

    def action_cancel(self):
        self.write({'cancelled': True})


class SpaCustomerPackageLine(models.Model):
    _name = 'spa.customer.package.line'
    _description = 'Số buổi dịch vụ trong gói khách hàng'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    customer_package_id = fields.Many2one(
        'spa.customer.package',
        string='Gói khách hàng',
        required=True,
        ondelete='cascade',
    )
    source_line_id = fields.Many2one(
        'spa.treatment.package.line',
        string='Dịch vụ trong danh mục gói',
        ondelete='set null',
    )
    product_id = fields.Many2one(
        'product.template',
        string='Dịch vụ hoặc combo',
        required=True,
        ondelete='restrict',
    )
    session_count = fields.Integer(string='Số buổi', required=True)
    used_session_count = fields.Integer(
        string='Đã sử dụng',
        compute='_compute_usage',
    )
    remaining_session_count = fields.Integer(
        string='Còn lại',
        compute='_compute_usage',
    )
    session_ids = fields.One2many(
        'spa.customer.package.session',
        'package_line_id',
        string='Lịch sử sử dụng',
    )

    @api.depends('session_ids.state')
    def _compute_usage(self):
        for line in self:
            line.used_session_count = len(
                line.session_ids.filtered(
                    lambda session: session.state == 'done'
                )
            )
            line.remaining_session_count = (
                line.session_count - line.used_session_count
            )

    @api.constrains('session_count', 'product_id')
    def _check_package_line(self):
        for line in self:
            if line.session_count < 1:
                raise ValidationError('Số buổi phải ít nhất là 1.')
            if line.product_id.type not in ('service', 'combo'):
                raise ValidationError(
                    'Gói liệu trình chỉ bao gồm dịch vụ hoặc combo Spa.'
                )
            if line.product_id.spa_treatment_package_id:
                raise ValidationError(
                    'Không thể thêm một gói liệu trình khác làm dịch vụ con.'
                )
            completed_count = self.env[
                'spa.customer.package.session'
            ].search_count([
                ('package_line_id', '=', line.id),
                ('state', '=', 'done'),
            ])
            if completed_count > line.session_count:
                raise ValidationError(
                    'Số buổi không được ít hơn số buổi đã sử dụng.'
                )


class SpaCustomerPackageSession(models.Model):
    _name = 'spa.customer.package.session'
    _description = 'Lịch sử sử dụng gói liệu trình'
    _order = 'session_date desc, id desc'

    package_line_id = fields.Many2one(
        'spa.customer.package.line',
        string='Dịch vụ trong gói',
        required=True,
        ondelete='cascade',
    )
    customer_package_id = fields.Many2one(
        'spa.customer.package',
        string='Gói khách hàng',
        related='package_line_id.customer_package_id',
        store=True,
        index=True,
    )
    product_id = fields.Many2one(
        related='package_line_id.product_id',
        string='Dịch vụ hoặc combo',
        store=True,
        readonly=True,
    )
    session_date = fields.Date(
        string='Ngày sử dụng',
        required=True,
        default=fields.Date.context_today,
    )
    appointment_id = fields.Many2one(
        'spa.appointment',
        string='Lịch hẹn',
        ondelete='restrict',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Nhân viên thực hiện',
        ondelete='restrict',
    )
    state = fields.Selection(
        [('done', 'Đã sử dụng'), ('cancelled', 'Đã hủy')],
        string='Trạng thái',
        required=True,
        default='done',
    )
    note = fields.Char(string='Ghi chú')

    @api.constrains(
        'package_line_id',
        'session_date',
        'appointment_id',
        'state',
    )
    def _check_session(self):
        for session in self.filtered(lambda item: item.state == 'done'):
            package = session.customer_package_id
            if not package or package.cancelled:
                raise ValidationError(
                    'Không thể sử dụng buổi của gói đã hủy.'
                )
            if session.session_date < package.start_date:
                raise ValidationError(
                    'Ngày sử dụng không được trước ngày bắt đầu gói.'
                )
            if (
                package.expiration_date
                and session.session_date > package.expiration_date
            ):
                raise ValidationError(
                    'Gói đã hết hạn tại ngày sử dụng buổi này.'
                )
            if (
                session.appointment_id
                and session.appointment_id.customer_id != package.partner_id
            ):
                raise ValidationError(
                    'Lịch hẹn không thuộc khách hàng sở hữu gói.'
                )
            completed_sessions = self.search_count([
                ('id', '!=', session.id),
                ('package_line_id', '=', session.package_line_id.id),
                ('state', '=', 'done'),
            ])
            if completed_sessions >= session.package_line_id.session_count:
                raise ValidationError(
                    'Dịch vụ này đã sử dụng hết số buổi trong gói.'
                )
