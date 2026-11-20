from odoo import models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        invoices_to_ship = self.filtered(
            lambda move: (
                move.move_type == 'out_invoice' and move.state == 'draft'
            )
        )
        result = super().action_post()
        for invoice in invoices_to_ship.filtered(
            lambda move: move.state == 'posted'
        ):
            orders = invoice.invoice_line_ids.sale_line_ids.order_id
            for order in orders:
                order.sudo().with_company(
                    invoice.company_id
                )._spa_auto_deduct_stock_on_invoice(invoice)
        return result

    def _check_spa_return_refund_status(self):
        requests = self.env['spa.return.request'].sudo().search([
            ('credit_note_id', 'in', self.ids),
            ('refund_confirmed', '=', True),
        ])
        if requests:
            raise UserError(
                _(
                    'Không thể sửa hoặc hủy credit note sau khi yêu cầu đã '
                    'được xác nhận hoàn tiền.'
                )
            )

    def button_draft(self):
        self._check_spa_return_refund_status()
        return super().button_draft()

    def button_cancel(self):
        self._check_spa_return_refund_status()
        requests = self.env['spa.return.request'].sudo().search([
            ('credit_note_id', 'in', self.ids),
        ])
        result = super().button_cancel()
        for request in requests:
            request._clear_credit_note(request.credit_note_id)
        return result

    def _track_subtype(self, init_values):
        self.ensure_one()
        if (
            self.move_type == 'out_invoice'
            and init_values.get('payment_state') != 'paid'
            and self.payment_state == 'paid'
        ):
            appointments = self.env['spa.appointment'].sudo().search([
                ('invoice_id', '=', self.id),
            ])
            for appointment in appointments:
                appointment._award_loyalty_points()
            orders = self.invoice_line_ids.sale_line_ids.order_id
            orders.sudo()._create_spa_sales_commission()
        return super()._track_subtype(init_values)
