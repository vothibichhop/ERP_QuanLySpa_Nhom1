from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    menu = env.ref('spa.menu_customer_loyalty', raise_if_not_found=False)
    if menu:
        menu.unlink()

    cr.execute("""
        UPDATE res_partner
           SET customer_type = CASE
               WHEN COALESCE(loyalty_point, 0) >= 2000 THEN 'diamond'
               WHEN COALESCE(loyalty_point, 0) >= 500 THEN 'gold'
               WHEN COALESCE(loyalty_point, 0) > 100 THEN 'silver'
               ELSE 'new'
           END
    """)
