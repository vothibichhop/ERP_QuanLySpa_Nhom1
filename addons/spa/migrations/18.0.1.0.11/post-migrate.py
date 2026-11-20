from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    customers = env['res.partner'].search(
        [
            ('customer_code', '=', False),
            '|',
            ('customer_rank', '>', 0),
            ('is_spa_customer', '=', True),
        ],
        order='id',
    )
    for customer in customers:
        customer.customer_code = customer.spa_customer_code or env[
            'res.partner'
        ]._next_customer_code()
