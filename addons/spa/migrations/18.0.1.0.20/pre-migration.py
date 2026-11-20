def migrate(cr, version):
    cr.execute("SELECT to_regclass('spa_sales_commission')")
    if cr.fetchone()[0]:
        cr.execute(
            'ALTER TABLE spa_sales_commission '
            'DROP CONSTRAINT IF EXISTS '
            'spa_sales_commission_sale_order_unique'
        )
