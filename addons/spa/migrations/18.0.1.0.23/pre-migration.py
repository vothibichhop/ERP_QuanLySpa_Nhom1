def migrate(cr, version):
    cr.execute("SELECT to_regclass('spa_sales_commission')")
    if not cr.fetchone()[0]:
        return

    cr.execute(
        'ALTER TABLE spa_sales_commission '
        'DROP CONSTRAINT IF EXISTS '
        'spa_sales_commission_order_employee_unique'
    )
    cr.execute(
        'ALTER TABLE spa_sales_commission '
        'DROP CONSTRAINT IF EXISTS '
        'spa_sales_commission_sale_order_unique'
    )
