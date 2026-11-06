from odoo import SUPERUSER_ID, api


SERVICE_RECIPES = {
    'DV000001': {'NVL-015': 1, 'NVL-009': 2, 'NVL-011': 2},
    'DV000002': {'NVL-006': 5, 'NVL-009': 2, 'NVL-011': 2},
    'DV000003': {'NVL-007': 15, 'NVL-006': 10, 'NVL-016': 1},
    'DV000004': {
        'NVL-003': 5, 'NVL-004': 3, 'NVL-005': 2,
        'NVL-009': 2, 'NVL-014': 5,
    },
    'DV000005': {
        'NVL-003': 5, 'NVL-004': 3, 'NVL-005': 2,
        'NVL-009': 2, 'NVL-014': 5,
    },
    'DV000006': {
        'NVL-003': 5, 'NVL-004': 3, 'NVL-005': 3,
        'NVL-008': 1, 'NVL-009': 2,
    },
    'DV000007': {
        'NVL-003': 5, 'NVL-004': 3, 'NVL-005': 2, 'NVL-009': 2,
    },
    'DV000008': {
        'NVL-006': 8, 'NVL-007': 10, 'NVL-016': 1,
    },
    'DV000009': {'NVL-015': 1, 'NVL-009': 2, 'NVL-011': 2},
    'DV000010': {
        'NVL-017': 8, 'NVL-018': 3, 'NVL-013': 1, 'NVL-006': 3,
    },
    'DV000011': {'NVL-003': 3, 'NVL-008': 1, 'NVL-009': 2},
    'DV000012': {
        'NVL-023': 3, 'NVL-015': 1, 'NVL-009': 2, 'NVL-011': 2,
    },
    'DV000015': {
        'NVL-017': 12, 'NVL-018': 4, 'NVL-013': 1, 'NVL-006': 3,
    },
    'DV000016': {
        'NVL-017': 10, 'NVL-018': 3, 'NVL-013': 1,
        'NVL-006': 5, 'NVL-016': 1,
    },
    'DV000017': {
        'NVL-017': 10, 'NVL-018': 3, 'NVL-013': 1,
    },
    'DV000018': {
        'NVL-017': 8, 'NVL-018': 3, 'NVL-013': 1,
    },
    'DV000019': {
        'NVL-003': 5, 'NVL-004': 3, 'NVL-005': 2,
        'NVL-008': 1, 'NVL-009': 3, 'NVL-010': 2,
    },
    'DV000020': {
        'NVL-007': 12, 'NVL-006': 10, 'NVL-001': 8, 'NVL-016': 1,
    },
    'DV000021': {
        'NVL-003': 5, 'NVL-004': 3, 'NVL-005': 4,
        'NVL-008': 1, 'NVL-009': 2,
    },
    'DV000022': {'NVL-001': 15, 'NVL-002': 2, 'NVL-016': 1},
    'DV000023': {'NVL-006': 10, 'NVL-016': 1, 'NVL-010': 2},
    'DV000024': {'NVL-006': 8, 'NVL-001': 5, 'NVL-016': 1},
    'DV000025': {'NVL-017': 5, 'NVL-018': 2, 'NVL-013': 1},
    'DV000026': {'NVL-006': 10, 'NVL-001': 5, 'NVL-016': 1},
    'DV000027': {'NVL-005': 2, 'NVL-006': 5, 'NVL-009': 2},
    'DV000028': {'NVL-001': 15, 'NVL-002': 2, 'NVL-016': 1},
    'DV000029': {'NVL-021': 10, 'NVL-016': 1},
    'DV000030': {'NVL-020': 15, 'NVL-016': 1},
    'DV000031': {
        'NVL-022': 2, 'NVL-015': 1, 'NVL-009': 2, 'NVL-011': 2,
    },
    'DV000032': {'NVL-019': 15, 'NVL-016': 1},
    'DV000033': {'NVL-003': 3, 'NVL-007': 5, 'NVL-009': 2},
    'DV000034': {'NVL-007': 15, 'NVL-016': 1, 'NVL-011': 2},
    'DV000036': {'NVL-006': 10, 'NVL-016': 1},
    'DV000037': {'NVL-022': 1, 'NVL-009': 1, 'NVL-011': 2},
    'DV000039': {'NVL-025': 10, 'NVL-016': 1},
    'DV000040': {'NVL-019': 10, 'NVL-016': 1},
    'DV000041': {'NVL-024': 15, 'NVL-011': 2, 'NVL-016': 1},
    'DV000042': {'NVL-019': 15, 'NVL-016': 1},
    'DV000068': {'NVL-024': 15, 'NVL-011': 2, 'NVL-016': 1},
    'DV000069': {'NVL-003': 3, 'NVL-009': 2, 'NVL-010': 2},
    'DV000070': {'NVL-019': 5, 'NVL-016': 1},
}

MATERIAL_CODES = {
    code
    for recipe in SERVICE_RECIPES.values()
    for code in recipe
}
NEW_MATERIAL_CODES = {
    'NVL-017',
    'NVL-018',
    'NVL-019',
    'NVL-020',
    'NVL-021',
    'NVL-022',
    'NVL-023',
    'NVL-024',
    'NVL-025',
}


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
            'Không tìm thấy kho nội bộ để nhập nguyên vật liệu Spa.'
        )

    materials = env['product.template'].search([
        ('default_code', 'in', list(MATERIAL_CODES)),
        ('is_storable', '=', True),
        ('spa_inventory_type', '=', 'service_material'),
        ('active', '=', True),
    ])
    materials_by_code = {
        material.default_code: material
        for material in materials
    }
    missing_materials = MATERIAL_CODES - set(materials_by_code)
    if missing_materials:
        raise RuntimeError(
            'Không tìm thấy nguyên vật liệu: %s'
            % ', '.join(sorted(missing_materials))
        )

    service_codes = list(SERVICE_RECIPES)
    services = env['product.template'].search([
        ('type', '=', 'service'),
        ('active', '=', True),
        ('spa_service_code', 'in', service_codes),
    ])
    services_by_code = {}
    for service in services:
        if service.spa_service_code in services_by_code:
            raise RuntimeError(
                'Mã dịch vụ %s bị trùng.'
                % service.spa_service_code
            )
        services_by_code[service.spa_service_code] = service
    missing_services = set(service_codes) - set(services_by_code)
    if missing_services:
        raise RuntimeError(
            'Không tìm thấy dịch vụ: %s'
            % ', '.join(sorted(missing_services))
        )

    recipe_model = env['spa.service.material']
    for service_code, recipe in SERVICE_RECIPES.items():
        service = services_by_code[service_code]
        for material_code, quantity in recipe.items():
            product = materials_by_code[material_code].product_variant_id
            line = recipe_model.search([
                ('service_id', '=', service.id),
                ('product_id', '=', product.id),
            ], limit=1)
            if line:
                line.quantity = quantity
            else:
                recipe_model.create({
                    'service_id': service.id,
                    'product_id': product.id,
                    'quantity': quantity,
                })

    quant_model = env['stock.quant'].with_company(company).with_context(
        inventory_mode=True,
    )
    quants = quant_model.browse()
    for material in materials.filtered(
        lambda item: item.default_code in NEW_MATERIAL_CODES
    ):
        product = material.with_company(company).product_variant_id
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
