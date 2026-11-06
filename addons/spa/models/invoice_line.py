from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    spa_discounted_price = fields.Monetary(
        string='Giá sau giảm',
        currency_field='currency_id',
        compute='_compute_spa_discounted_price',
    )

    @api.depends(
        'price_unit',
        'discount',
        'display_type',
        'sale_line_ids',
        'sale_line_ids.reward_id',
        'sale_line_ids.reward_id.reward_type',
        'sale_line_ids.product_id',
        'sale_line_ids.company_id.sale_discount_product_id',
    )
    def _compute_spa_discounted_price(self):
        for line in self:
            if line.display_type != 'product':
                line.spa_discounted_price = 0.0
            elif any(sale_line._is_discount_line() for sale_line in line.sale_line_ids):
                line.spa_discounted_price = line.price_unit
            else:
                line.spa_discounted_price = line.price_unit * (
                    1 - (line.discount or 0.0) / 100.0
                )
