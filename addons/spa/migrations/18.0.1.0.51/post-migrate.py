def migrate(cr, version):
    cr.execute(
        """
        UPDATE product_template
           SET type = 'product'
         WHERE is_storable
           AND type = 'consu'
        """
    )
