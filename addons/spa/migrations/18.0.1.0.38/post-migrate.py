from odoo import SUPERUSER_ID, api


INVENTORY_COSTS = {
    'TB-001': 8_000_000,
    'TB-002': 10_000_000,
    'TB-003': 1_500_000,
    'TB-004': 2_000_000,
    'TB-005': 25_000_000,
    'TB-006': 5_000_000,
    'TB-007': 1_800_000,
    'TB-008': 2_500_000,
    'TB-009': 1_200_000,
    'TB-010': 4_000_000,
    'SPA-SK-001': 90_000,
    'SPA-SK-002': 110_000,
    'SPA-SK-003': 220_000,
    'SPA-SK-004': 250_000,
    'SPA-SK-005': 190_000,
    'SPA-SK-006': 170_000,
    'SPA-SK-007': 25_000,
    'SPA-HR-001': 120_000,
    'SPA-HR-002': 130_000,
    'SPA-BC-001': 150_000,
    'SPA-BC-002': 155_000,
    'SPA-BC-003': 130_000,
    'NVL-001': 150,
    'NVL-002': 300,
    'NVL-003': 80,
    'NVL-004': 120,
    'NVL-005': 500,
    'NVL-006': 180,
    'NVL-007': 250,
    'NVL-008': 15_000,
    'NVL-009': 300,
    'NVL-010': 150,
    'NVL-011': 700,
    'NVL-012': 300,
    'NVL-013': 250,
    'NVL-014': 80,
    'NVL-015': 50,
    'NVL-016': 1_500,
}

MILLILITRE_CODES = {
    'NVL-001',
    'NVL-002',
    'NVL-003',
    'NVL-004',
    'NVL-005',
    'NVL-006',
    'NVL-014',
    'NVL-015',
}
GRAM_CODES = {'NVL-007'}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.company
    warehouse = env['stock.warehouse'].search(
        [('company_id', '=', company.id)],
        order='id',
        limit=1,
    )
    if not warehouse or not warehouse.lot_stock_id:
        raise RuntimeError(
            'Không tìm thấy kho nội bộ để nhập số lượng tồn đầu kỳ cho danh mục Spa.'
        )

    templates = env['product.template'].search([
        ('default_code', 'in', list(INVENTORY_COSTS)),
        ('is_storable', '=', True),
        ('active', '=', True),
    ])
    templates_by_code = {template.default_code: template for template in templates}
    missing_codes = set(INVENTORY_COSTS) - set(templates_by_code)
    if missing_codes:
        raise RuntimeError(
            'Không tìm thấy sản phẩm kho Spa: %s'
            % ', '.join(sorted(missing_codes))
        )

    piece_uom = env.ref('spa.uom_spa_piece')
    millilitre_uom = env.ref('spa.uom_spa_millilitre')
    gram_uom = env.ref('uom.product_uom_gram')
    products = templates.mapped('product_variant_id')
    products_with_moves = set(
        env['stock.move'].sudo().search([
            ('product_id', 'in', products.ids),
        ]).mapped('product_id').ids
    )
    for code, template in templates_by_code.items():
        if code in MILLILITRE_CODES:
            uom = millilitre_uom
        elif code in GRAM_CODES:
            uom = gram_uom
        else:
            uom = piece_uom
        if template.product_variant_id.id in products_with_moves:
            previous_uoms = template.uom_id | template.uom_po_id
            if any(
                previous_uom.category_id != uom.category_id
                or previous_uom.factor != uom.factor
                for previous_uom in previous_uoms
            ):
                raise RuntimeError(
                    'Không thể đổi đơn vị của %s vì sản phẩm đã có giao dịch '
                    'và đơn vị mới không tương đương.'
                    % template.default_code
                )
            # Odoo blocks UoM changes after stock moves, even when only the
            # display label changes and the unit conversion ratio stays equal.
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
        else:
            template.write({
                'uom_id': uom.id,
                'uom_po_id': uom.id,
            })
        template.with_company(company).standard_price = INVENTORY_COSTS[code]

    quant_model = env['stock.quant'].with_company(company).with_context(
        inventory_mode=True,
    )
    quants = quant_model.browse()
    for template in templates:
        product = template.with_company(company).product_variant_id
        quant = quant_model.search([
            ('product_id', '=', product.id),
            ('location_id', '=', warehouse.lot_stock_id.id),
            ('company_id', '=', company.id),
            ('lot_id', '=', False),
            ('package_id', '=', False),
            ('owner_id', '=', False),
        ], limit=1)
        if quant:
            quant.inventory_quantity = 20
        else:
            quant = quant_model.create({
                'product_id': product.id,
                'location_id': warehouse.lot_stock_id.id,
                'inventory_quantity': 20,
            })
        quants |= quant
    quants.action_apply_inventory()
