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
    )
    def _compute_spa_return_refund_counts(self):
        for order in self:
            order.spa_returnable_picking_count = len(
                order._get_spa_returnable_pickings()
            )
            order.spa_refundable_invoice_count = len(
                order._get_spa_refundable_invoices()
            )

    def _get_spa_returnable_pickings(self):
        self.ensure_one()
        returnable_pickings = self.env['stock.picking']
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
                returned_quantity = sum(
                    move.returned_move_ids.filtered(
                        lambda record: (
                            record.state == 'done'
                            and record.picking_code == 'incoming'
                        )
                    ).mapped('quantity')
                )
                if float_compare(
                    move.quantity - returned_quantity,
                    0.0,
                    precision_rounding=move.product_uom.rounding,
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
        action = self._get_action_view_picking(pickings)
        action['name'] = 'Phiếu giao hàng có thể trả'
        return action

    def action_spa_create_refund(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(
                'Bạn cần quyền Kế toán hóa đơn để tạo phiếu hoàn tiền.'
            )
        invoices = self._get_spa_refundable_invoices()
        if not invoices:
            raise UserError(
                'Đơn hàng không có hóa đơn đã ghi sổ còn số tiền có thể hoàn.'
            )
        action = invoices[:1].action_reverse()
        action['context'] = dict(
            self.env.context,
            active_model='account.move',
            active_id=invoices[0].id,
            active_ids=invoices.ids,
        )
        return action

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
