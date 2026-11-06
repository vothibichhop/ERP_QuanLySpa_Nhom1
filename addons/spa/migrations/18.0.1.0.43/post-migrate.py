from odoo import SUPERUSER_ID, api


PRODUCT_UOMS = {
    'SPA-SK-001': 'uom_spa_bottle',
    'SPA-SK-002': 'uom_spa_bottle',
    'SPA-SK-003': 'uom_spa_jar',
    'SPA-SK-004': 'uom_spa_jar',
    'SPA-SK-005': 'uom_spa_jar',
    'SPA-SK-006': 'uom_spa_jar',
    'SPA-SK-007': 'uom_spa_piece',
    'SPA-HR-001': 'uom_spa_bottle',
    'SPA-HR-002': 'uom_spa_bottle',
    'SPA-BC-001': 'uom_spa_jar',
    'SPA-BC-002': 'uom_spa_bottle',
    'SPA-BC-003': 'uom_spa_bottle',
}

PRODUCT_UOM_COLUMNS = (
    ('stock_move', 'product_uom'),
    ('stock_move_line', 'product_uom_id'),
    ('sale_order_line', 'product_uom'),
    ('purchase_order_line', 'product_uom'),
    ('account_move_line', 'product_uom_id'),
    ('stock_scrap', 'product_uom_id'),
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Product = env['product.template'].with_context(active_test=False)

    for code, uom_xmlid in PRODUCT_UOMS.items():
        template = Product.search([('default_code', '=', code)], limit=1)
        if not template:
            raise RuntimeError('Không tìm thấy sản phẩm Spa: %s' % code)

        uom = env.ref('spa.%s' % uom_xmlid)
        previous_uoms = template.uom_id | template.uom_po_id
        if any(
            previous_uom.factor != uom.factor
            for previous_uom in previous_uoms
        ):
            raise RuntimeError(
                'Không thể đổi đơn vị của %s vì đơn vị mới không tương đương.'
                % code
            )

        product = template.product_variant_id
        for table, column in PRODUCT_UOM_COLUMNS:
            cr.execute('SELECT to_regclass(%s)', (table,))
            if cr.fetchone()[0]:
                cr.execute(
                    """
                    UPDATE %s
                       SET %s = %%s
                     WHERE product_id = %%s
                       AND %s = ANY(%%s)
                    """ % (table, column, column),
                    (uom.id, product.id, previous_uoms.ids),
                )

        cr.execute(
            """
            UPDATE product_template
               SET uom_id = %s,
                   uom_po_id = %s
             WHERE id = %s
            """,
            (uom.id, uom.id, template.id),
        )
        template.invalidate_recordset(['uom_id', 'uom_po_id'])
