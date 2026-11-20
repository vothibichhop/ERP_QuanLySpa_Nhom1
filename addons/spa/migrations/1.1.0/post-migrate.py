from collections import Counter

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("SELECT to_regclass('spa_customer_partner_map')")
    if not cr.fetchone()[0]:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT customer_id, partner_id, customer_code, birthday, gender
          FROM spa_customer_partner_map
         ORDER BY customer_id
    """)
    customers = cr.fetchall()
    code_counts = Counter((row[2] or '').strip() for row in customers)
    used_codes = set()

    for customer_id, partner_id, code, birthday, gender in customers:
        code = (code or '').strip() or f'KH-MIG-{customer_id:06d}'
        candidate = f'{code}-{customer_id}' if code_counts[code] > 1 else code
        suffix = 1
        while candidate in used_codes:
            candidate = f'{code}-{customer_id}-{suffix}'
            suffix += 1
        used_codes.add(candidate)

        env['res.partner'].browse(partner_id).write({
            'is_spa_customer': True,
            'spa_customer_code': candidate,
            'spa_birthday': birthday,
            'spa_gender': gender,
        })
    cr.execute("DROP TABLE spa_customer_partner_map")
