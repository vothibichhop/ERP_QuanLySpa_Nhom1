from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        UPDATE res_partner
           SET customer_type = CASE customer_type
               WHEN 'new' THEN 'silver'
               WHEN 'regular' THEN 'gold'
               WHEN 'vip' THEN 'diamond'
           END
         WHERE customer_type IN ('new', 'regular', 'vip')
    """)
    for xml_id in (
        'spa.menu_spa_customer',
        'spa.action_spa_customer',
        'spa.view_spa_customer_list',
    ):
        record = env.ref(xml_id, raise_if_not_found=False)
        if record:
            record.unlink()
