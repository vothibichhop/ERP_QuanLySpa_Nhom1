from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

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
        return super()._track_subtype(init_values)
