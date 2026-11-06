def migrate(cr, version):
    cr.execute(
        """
        UPDATE product_template
           SET spa_inventory_type = 'retail'
         WHERE is_storable
           AND sale_ok
           AND spa_inventory_type IS NULL
        """
    )
