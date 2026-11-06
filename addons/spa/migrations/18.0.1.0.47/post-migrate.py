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

PACKAGING_UOMS = {'uom_spa_bottle', 'uom_spa_jar'}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    unit_category = env.ref('uom.product_uom_categ_unit')
    Product = env['product.template'].with_context(active_test=False)

    for code, uom_xmlid in PRODUCT_UOMS.items():
        template = Product.search([('default_code', '=', code)], limit=1)
        if not template:
            raise RuntimeError('Không tìm thấy sản phẩm Spa: %s' % code)

        uom = env.ref('spa.%s' % uom_xmlid)
        if uom_xmlid in PACKAGING_UOMS:
            cr.execute(
                """
                UPDATE uom_uom
                   SET category_id = %s,
                       uom_type = 'bigger',
                       factor = 1,
                       rounding = 1
                 WHERE id = %s
                """,
                (unit_category.id, uom.id),
            )
            uom.invalidate_recordset([
                'category_id',
                'uom_type',
                'factor',
                'rounding',
            ])

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
        template.product_variant_id.invalidate_recordset(['uom_id', 'uom_po_id'])
