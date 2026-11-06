from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("""
        UPDATE res_partner
           SET customer_type = CASE
               WHEN COALESCE(loyalty_point, 0) >= 2000 THEN 'diamond'
               WHEN COALESCE(loyalty_point, 0) >= 1500 THEN 'gold'
               WHEN COALESCE(loyalty_point, 0) >= 500 THEN 'silver'
               ELSE 'new'
           END
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['sale.order'].search([
        ('state', 'in', ('draft', 'sent')),
    ])._update_spa_tier_discount()
