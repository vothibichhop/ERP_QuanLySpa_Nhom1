from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    spa_customer_type = fields.Selection(
        related='partner_id.customer_type',
        string='Hạng khách hàng',
        readonly=True,
    )
    spa_customer_loyalty_point = fields.Integer(
        related='partner_id.loyalty_point',
        string='Điểm tích lũy',
        readonly=True,
    )
    spa_tier_discount = fields.Float(
        string='Giảm giá theo hạng (%)',
        readonly=True,
        copy=False,
        default=0.0,
    )
    spa_appointment_id = fields.Many2one(
        'spa.appointment',
        string='Lịch hẹn Spa',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    spa_return_request_ids = fields.One2many(
        'spa.return.request',
        'order_id',
        string='Yêu cầu trả hàng',
    )
    spa_returnable_picking_count = fields.Integer(
        string='Phiếu giao hàng có thể trả',
        compute='_compute_spa_return_refund_counts',
    )
    spa_refundable_invoice_count = fields.Integer(
        string='Hóa đơn có thể hoàn',
        compute='_compute_spa_return_refund_counts',
    )

    @api.depends(
        'picking_ids.state',
        'picking_ids.picking_type_code',
        'picking_ids.move_ids.state',
        'picking_ids.move_ids.quantity',
        'picking_ids.move_ids.product_id.is_storable',
        'picking_ids.move_ids.product_uom.rounding',
        'picking_ids.move_ids.returned_move_ids.state',
        'picking_ids.move_ids.returned_move_ids.picking_code',
        'picking_ids.move_ids.returned_move_ids.quantity',
        'invoice_ids.state',
        'invoice_ids.move_type',
        'invoice_ids.amount_total',
        'invoice_ids.reversal_move_ids.state',
        'invoice_ids.reversal_move_ids.move_type',
        'invoice_ids.reversal_move_ids.amount_total',
        'spa_return_request_ids.state',
        'spa_return_request_ids.return_received',
        'spa_return_request_ids.credit_note_id',
    )
    def _compute_spa_return_refund_counts(self):
        for order in self:
            order.spa_returnable_picking_count = len(
                order._get_spa_returnable_pickings()
            )
            order.spa_refundable_invoice_count = len(
                order._get_spa_refundable_requests()
            )

    def _get_spa_returnable_pickings(self):
        self.ensure_one()
        returnable_pickings = self.env['stock.picking']
        request_model = self.env['spa.return.request']
        for picking in self.picking_ids.filtered(
            lambda record: (
                record.state == 'done'
                and record.picking_type_code == 'outgoing'
            )
        ):
            for move in picking.move_ids.filtered(
                lambda record: (
                    record.state == 'done' and record.product_id.is_storable
                )
            ):
                if float_compare(
                    request_model._available_return_quantity(move),
                    0.0,
                    precision_rounding=move.product_id.uom_id.rounding,
                ) > 0:
                    returnable_pickings |= picking
                    break
        return returnable_pickings

    def _get_spa_refundable_invoices(self):
        self.ensure_one()
        invoices = self.invoice_ids.filtered(
            lambda move: (
                move.move_type == 'out_invoice' and move.state == 'posted'
            )
        )
        refundable_invoices = self.env['account.move']
        for invoice in invoices:
            refunds = invoice.reversal_move_ids.filtered(
                lambda move: (
                    move.move_type == 'out_refund' and move.state != 'cancel'
                )
            )
            if refunds.filtered(lambda move: move.state == 'draft'):
                continue
            refunded_total = sum(
                refunds.filtered(lambda move: move.state == 'posted').mapped(
                    'amount_total'
                )
            )
            if invoice.currency_id.compare_amounts(
                invoice.amount_total - refunded_total,
                0.0,
            ) > 0:
                refundable_invoices |= invoice
        return refundable_invoices

    def _get_spa_refundable_requests(self):
        self.ensure_one()
        requests = self.env['spa.return.request'].search([
            ('order_id', '=', self.id),
            ('state', '=', 'approved'),
            ('return_picking_id', '!=', False),
            ('credit_note_id', '=', False),
        ])
        return requests.filtered('return_received')

    def action_spa_return_delivered_products(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(
                'Bạn cần quyền Quản lý kho để xử lý hàng trả lại.'
            )
        pickings = self._get_spa_returnable_pickings()
        if not pickings:
            raise UserError(
                'Đơn hàng này không có phiếu giao hàng sản phẩm nào còn số lượng '
                'có thể trả.'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yêu cầu trả hàng',
            'res_model': 'spa.return.request',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

    def action_spa_create_refund(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(
                'Bạn cần quyền Kế toán hóa đơn để tạo phiếu hoàn tiền.'
            )
        requests = self._get_spa_refundable_requests()
        if not requests:
            raise UserError(
                'Cần có yêu cầu trả hàng được duyệt và hàng đã được kho nhận '
                'trước khi tạo credit note.'
            )
        if len(requests) == 1:
            return requests.action_create_refund()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yêu cầu chờ hoàn tiền',
            'res_model': 'spa.return.request',
            'view_mode': 'list,form',
            'domain': [('id', 'in', requests.ids)],
        }

    def _get_spa_base_pricelist(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        pricelist_model = self.env['product.pricelist']
        base_domain = [
            ('active', '=', True),
            ('currency_id', '=', company.currency_id.id),
            ('item_ids', '=', False),
        ]
        pricelist = pricelist_model.search(
            base_domain + [('company_id', '=', company.id)],
            order='sequence, id',
            limit=1,
        )
        if not pricelist:
            pricelist = pricelist_model.search(
                base_domain + [('company_id', '=', False)],
                order='sequence, id',
                limit=1,
            )
        if not pricelist:
            pricelist = pricelist_model.sudo().create({
                'name': 'Giá cơ sở',
                'currency_id': company.currency_id.id,
                'company_id': company.id,
            })
        return pricelist

    @api.depends('partner_id', 'company_id')
    def _compute_pricelist_id(self):
        super()._compute_pricelist_id()
        for order in self:
            if (
                order.state == 'draft'
                and order.partner_id
                and order.partner_id.customer_type == 'new'
            ):
                order.pricelist_id = order._get_spa_base_pricelist()

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._update_spa_tier_discount()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if 'partner_id' in vals:
            self._update_spa_tier_discount()
        return result

    def action_confirm(self):
        employee_model = self.env['hr.employee'].sudo()
        for order in self:
            if not order.user_id:
                continue
            employees = employee_model.search(
                [
                    ('user_id', '=', order.user_id.id),
                    ('active', '=', True),
                ],
                limit=2,
            )
            if len(employees) != 1:
                continue
            order.order_line.filtered(
                lambda line: (
                    not line.display_type
                    and line.product_id.type in ('product', 'consu')
                    and not line.spa_employee_id
                )
            ).write({'spa_employee_id': employees.id})

        missing_employee_lines = self.order_line.filtered(
            lambda line: (
                not line.display_type
                and line.product_id.type in ('product', 'consu')
                and not line.spa_employee_id
            )
        )
        if missing_employee_lines:
            products = ', '.join(
                missing_employee_lines.mapped('product_id.display_name')
            )
            raise UserError(
                'Vui lòng chọn Nhân viên bán sản phẩm cho từng sản phẩm bán lẻ '
                'trước khi xác nhận đơn hàng. Sản phẩm chưa được gán: %s'
                % products
            )
        result = super().action_confirm()
        self._create_spa_customer_packages()
        self._create_spa_sales_commissions_on_confirmation()
        return result

    def _create_spa_customer_packages(self):
        customer_package_model = self.env['spa.customer.package']
        for order in self:
            for line in order.order_line.filtered(
                lambda item: (
                    not item.display_type
                    and item.product_id.product_tmpl_id.spa_treatment_package_id
                )
            ):
                quantity = line.product_uom_qty
                package_model = (
                    line.product_id.product_tmpl_id.spa_treatment_package_id
                )
                if float_compare(
                    quantity,
                    round(quantity),
                    precision_digits=6,
                ):
                    raise UserError(
                        'Số lượng gói liệu trình phải là số nguyên: %s'
                        % line.product_id.display_name
                    )
                existing_count = customer_package_model.search_count([
                    ('sale_order_line_id', '=', line.id),
                ])
                for _index in range(existing_count, int(quantity)):
                    customer_package_model.sudo().create({
                        'partner_id': order.partner_id.id,
                        'package_id': package_model.id,
                        'sale_order_id': order.id,
                        'sale_order_line_id': line.id,
                        'user_id': order.user_id.id,
                    })

    def action_cancel(self):
        result = super().action_cancel()
        commissions = self.env['spa.sales.commission'].sudo().search([
            ('sale_order_line_id', 'in', self.order_line.ids),
            ('state', '=', 'draft'),
        ])
        if commissions:
            commissions.with_context(
                spa_commission_transition=True
            ).write({'state': 'cancelled'})
        return result

    @api.onchange('partner_id')
    def _onchange_partner_id_spa_tier_discount(self):
        self._update_spa_tier_discount()

    def _update_spa_tier_discount(self):
        for order in self.filtered(lambda record: record.state in ('draft', 'sent')):
            order.spa_tier_discount = (
                order.partner_id._get_spa_tier_discount_percentage()
                if order.partner_id
                else 0.0
            )

    def _spa_auto_deduct_stock_on_invoice(self, invoice):
        self.ensure_one()
        if not invoice or invoice.move_type != 'out_invoice':
            return

        stock_lines = invoice.invoice_line_ids.filtered(
            lambda line: (
                line.display_type == 'product'
                and line.product_id
                and line.product_id.type in ('product', 'consu')
                and line.product_id.is_storable
                and line.quantity > 0
                and self in line.sale_line_ids.order_id
            )
        )
        if not stock_lines:
            return

        sale_lines = stock_lines.sale_line_ids.filtered(
            lambda line: line.order_id == self
        )
        existing_pickings = self.picking_ids.filtered(
            lambda picking: (
                picking.picking_type_code == 'outgoing'
                and picking.state not in ('cancel', 'done')
                and bool(
                    picking.move_ids_without_package.filtered(
                        lambda move: move.sale_line_id in sale_lines
                    )
                )
            )
        )
        if existing_pickings:
            for picking in existing_pickings:
                moves = picking.move_ids_without_package.filtered(
                    lambda move: move.sale_line_id in sale_lines
                )
                picking.action_assign()
                unavailable = moves.filtered(
                    lambda move: (
                        move.product_uom_qty > move.reserved_availability
                    )
                )
                if unavailable:
                    names = ', '.join(
                        unavailable.mapped('product_id.display_name')
                    )
                    raise UserError(
                        'Không đủ tồn kho cho sản phẩm: %s' % names
                    )
                moves.quantity = moves.product_uom_qty
                moves.picked = True
                picking.with_context(skip_sms=True).button_validate()
            return

        if self.picking_ids.filtered(
            lambda picking: (
                picking.picking_type_code == 'outgoing'
                and picking.state == 'done'
                and bool(
                    picking.move_ids_without_package.filtered(
                        lambda move: move.sale_line_id in sale_lines
                    )
                )
            )
        ):
            return

        warehouse = self.env['stock.warehouse'].sudo().search([
            ('company_id', '=', invoice.company_id.id),
        ], limit=1)
        if not warehouse or not warehouse.out_type_id:
            raise UserError(
                'Hãy cấu hình kho xuất và loại xuất kho cho công ty trước khi '
                'xác nhận thanh toán.'
            )

        stock_picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': warehouse.out_type_id.id,
            'location_id': warehouse.out_type_id.default_location_src_id.id,
            'location_dest_id': warehouse.out_type_id.default_location_dest_id.id,
            'origin': invoice.name,
            'partner_id': invoice.partner_id.id,
            'company_id': invoice.company_id.id,
            'move_ids_without_package': [
                (0, 0, {
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.product_uom_id.id,
                    'location_id': warehouse.out_type_id.default_location_src_id.id,
                    'location_dest_id': warehouse.out_type_id.default_location_dest_id.id,
                    'company_id': invoice.company_id.id,
                    'origin': invoice.name,
                })
                for line in stock_lines
            ],
        })

        stock_picking.action_confirm()
        stock_picking.action_assign()
        if stock_picking.state not in ('assigned', 'done'):
            unavailable = stock_picking.move_ids_without_package.filtered(
                lambda move: move.product_uom_qty > move.reserved_availability
            )
            if unavailable:
                names = ', '.join(
                    unavailable.mapped('product_id.display_name')
                )
                raise UserError(
                    'Không đủ tồn kho cho sản phẩm: %s' % names
                )

        stock_picking.with_context(skip_sms=True).button_validate()

    def action_spa_confirm_payment(self):
        self.ensure_one()
        if not self.env.user.has_group('spa.group_spa_billing_user'):
            raise AccessError(
                'Bạn cần quyền Spa Billing User để xác nhận thanh toán.'
            )
        if not self.spa_appointment_id:
            raise UserError('Đơn hàng này không liên kết với lịch hẹn Spa.')

        if self.state in ('draft', 'sent'):
            self.action_confirm()
        elif self.state != 'sale':
            raise UserError(
                'Chỉ có thể xác nhận thanh toán cho đơn hàng ở trạng thái báo giá '
                'hoặc đã xác nhận.'
            )

        invoice = self.invoice_ids.filtered(
            lambda move: move.move_type == 'out_invoice' and move.state != 'cancel'
        )[:1]
        if not invoice:
            invoice = self._create_invoices()
        if not invoice:
            raise UserError('Không thể tạo hóa đơn từ đơn hàng này.')
        if invoice.state == 'draft':
            invoice.action_post()
        self.spa_appointment_id.invoice_id = invoice[:1]
        self.spa_appointment_id._award_loyalty_points()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hóa đơn thanh toán',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice[:1].id,
            'target': 'current',
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    spa_employee_id = fields.Many2one(
        'hr.employee.public',
        string='Nhân viên bán sản phẩm',
        copy=False,
        ondelete='restrict',
    )
    spa_sales_commission_ids = fields.One2many(
        'spa.sales.commission',
        'sale_order_line_id',
        string='Hoa hồng',
    )
    spa_commission_amount = fields.Monetary(
        string='Hoa hồng dự kiến',
        currency_field='currency_id',
        compute='_compute_spa_commission_amount',
        compute_sudo=True,
    )
    spa_commission_rate = fields.Float(
        string='Tỷ lệ hoa hồng (%)',
        compute='_compute_spa_commission_amount',
        digits=(16, 2),
        compute_sudo=True,
    )
    spa_commission_calculated = fields.Boolean(
        string='Đã tính hoa hồng',
        compute='_compute_spa_commission_calculated',
        compute_sudo=True,
    )
    spa_commission_status = fields.Selection(
        [
            ('unassigned', 'Chưa chọn nhân viên'),
            ('pending', 'Chưa áp dụng'),
            ('applied', 'Đã áp dụng'),
        ],
        string='Trạng thái hoa hồng',
        compute='_compute_spa_commission_calculated',
        compute_sudo=True,
    )
    spa_order_date = fields.Datetime(
        string='Ngày bán',
        related='order_id.date_order',
        readonly=True,
    )

    @api.depends(
        'price_subtotal',
        'product_id.type',
        'spa_employee_id',
        'spa_sales_commission_ids.rate',
        'spa_sales_commission_ids.commission_amount',
    )
    def _compute_spa_commission_amount(self):
        default_rate = self.env.ref(
            'spa.sales_commission_rule_default'
        ).sudo().rate
        for line in self:
            commission = line.spa_sales_commission_ids[:1]
            rate = commission.rate if commission else default_rate
            line.spa_commission_rate = (
                rate if line.product_id.type in ('product', 'consu') else 0.0
            )
            amount = commission.commission_amount if commission else (
                line.price_subtotal * rate / 100
                if line.product_id.type in ('product', 'consu')
                and line.spa_employee_id
                else 0.0
            )
            line.spa_commission_amount = line.currency_id.round(amount)

    @api.depends(
        'spa_employee_id',
        'spa_sales_commission_ids',
        'spa_sales_commission_ids.employee_id',
        'spa_sales_commission_ids.state',
        'invoice_lines.move_id.move_type',
        'invoice_lines.spa_sales_commission_ids',
        'invoice_lines.spa_sales_commission_ids.employee_id',
    )
    def _compute_spa_commission_calculated(self):
        for line in self:
            invoice_lines = line.invoice_lines.filtered(
                lambda invoice_line: (
                    invoice_line.display_type == 'product'
                    and invoice_line.product_id.type in ('product', 'consu')
                    and invoice_line.move_id.move_type == 'out_invoice'
                    and invoice_line.move_id.state != 'cancel'
                )
            )
            recorded_commission = line.spa_sales_commission_ids.filtered(
                lambda commission: (
                    commission.employee_id == line.spa_employee_id
                    and commission.state != 'cancelled'
                )
            )
            applied = bool(
                line.spa_employee_id
                and (
                    recorded_commission
                    or (
                        invoice_lines
                        and all(
                            invoice_line.spa_sales_commission_ids.filtered(
                                lambda commission: (
                                    commission.employee_id
                                    == line.spa_employee_id
                                )
                            )
                            for invoice_line in invoice_lines
                        )
                    )
                )
            )
            line.spa_commission_calculated = applied
            line.spa_commission_status = (
                'unassigned' if not line.spa_employee_id
                else 'applied' if applied
                else 'pending'
            )

    def write(self, vals):
        if 'spa_employee_id' not in vals:
            return super().write(vals)

        employee_id = vals['spa_employee_id'] or False
        changed_lines = self.filtered(
            lambda line: line.spa_employee_id.id != employee_id
        )
        if changed_lines.sudo().spa_sales_commission_ids.filtered(
            lambda commission: commission.state != 'cancelled'
        ):
            raise UserError(
                'Không thể đổi nhân viên vì hoa hồng cho dòng sản phẩm này '
                'đã được ghi nhận.'
            )
        invoice_lines = changed_lines.invoice_lines.filtered(
            lambda invoice_line: (
                invoice_line.move_id.move_type == 'out_invoice'
                and invoice_line.move_id.state != 'cancel'
            )
        )
        if invoice_lines.sudo().spa_sales_commission_ids:
            raise UserError(
                'Không thể đổi nhân viên vì hoa hồng cho dòng hóa đơn này '
                'đã được ghi nhận.'
            )

        for invoice_line in invoice_lines:
            assigned_employee_ids = {
                employee_id
                if sale_line in changed_lines
                else sale_line.spa_employee_id.id
                for sale_line in invoice_line.sale_line_ids
            }
            if len(assigned_employee_ids) > 1:
                raise UserError(
                    'Không thể đổi nhân viên vì dòng hóa đơn này gộp nhiều '
                    'nhân viên khác nhau.'
                )

        result = super().write(vals)
        for line in changed_lines:
            related_invoice_lines = line.invoice_lines.filtered(
                lambda invoice_line: (
                    invoice_line.move_id.move_type == 'out_invoice'
                    and invoice_line.move_id.state != 'cancel'
                )
            )
            related_invoice_lines.sudo().write({
                'spa_employee_id': employee_id,
            })
            paid_invoices = related_invoice_lines.move_id.filtered(
                lambda invoice: (
                    invoice.state == 'posted'
                    and invoice.payment_state == 'paid'
                )
            )
            paid_invoices._create_spa_sales_commissions()
        return result

    def _prepare_invoice_line(self, **optional_values):
        values = super()._prepare_invoice_line(**optional_values)
        values['spa_employee_id'] = self.spa_employee_id.id
        return values

    @api.depends(
        'product_id',
        'product_uom',
        'product_uom_qty',
        'order_id.spa_tier_discount',
    )
    def _compute_discount(self):
        super()._compute_discount()
        for line in self:
            if line.display_type or not line.product_id or line.reward_id:
                continue

            tier_discount = line.order_id.spa_tier_discount
            if tier_discount:
                line.discount = 100 - (
                    (100 - line.discount) * (100 - tier_discount) / 100
                )
