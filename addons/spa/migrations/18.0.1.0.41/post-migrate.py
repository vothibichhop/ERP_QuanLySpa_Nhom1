import logging
import math
from collections import defaultdict

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)

MONTHLY_SERVICE_VISITS = 40
SAFETY_FACTOR = 1.5
PIECE_STOCK_STEP = 10
PIECE_MINIMUM_STOCK = 20
MEASURED_STOCK_STEP = 100


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
            'Không tìm thấy kho nội bộ để cập nhật tồn ước tính cho nguyên vật liệu Spa.'
        )

    services = env['product.template'].search([
        ('active', '=', True),
        ('type', '=', 'service'),
        ('spa_category', '!=', False),
    ])
    if not services:
        raise RuntimeError(
            'Không tìm thấy dịch vụ Spa để tính tồn nguyên vật liệu ước tính.'
        )

    service_materials = env['spa.service.material'].search([
        ('service_id', 'in', services.ids),
    ])
    usage_by_product = defaultdict(float)
    for line in service_materials:
        usage_by_product[line.product_id.id] += line.quantity

    piece_uom = env.ref('spa.uom_spa_piece')
    gram_uom = env.ref('uom.product_uom_gram')
    millilitre_uom = env.ref('spa.uom_spa_millilitre')
    materials = env['product.template'].search([
        ('active', '=', True),
        ('is_storable', '=', True),
        ('spa_inventory_type', '=', 'service_material'),
    ])

    quant_model = env['stock.quant'].with_company(company).with_context(
        inventory_mode=True,
    )
    quants = quant_model.browse()
    for material in materials:
        product = material.product_variant_id
        total_service_usage = usage_by_product.get(product.id, 0)
        if not total_service_usage:
            _logger.info(
                'Giữ nguyên tồn %s vì chưa được định lượng trong dịch vụ.',
                material.default_code,
            )
            continue

        if material.uom_id == piece_uom:
            stock_step = PIECE_STOCK_STEP
        elif material.uom_id in (gram_uom, millilitre_uom):
            stock_step = MEASURED_STOCK_STEP
        else:
            raise RuntimeError(
                'Đơn vị tính của %s chưa được hỗ trợ để ước tính tồn kho: %s'
                % (material.default_code, material.uom_id.display_name)
            )

        estimated_monthly_usage = (
            total_service_usage
            * MONTHLY_SERVICE_VISITS
            / len(services)
        )
        target_quantity = max(
            PIECE_MINIMUM_STOCK if material.uom_id == piece_uom else stock_step,
            math.ceil(
                estimated_monthly_usage * SAFETY_FACTOR / stock_step
            ) * stock_step,
        )

        quant = quant_model.search([
            ('product_id', '=', product.id),
            ('location_id', '=', warehouse.lot_stock_id.id),
            ('company_id', '=', company.id),
            ('lot_id', '=', False),
            ('package_id', '=', False),
            ('owner_id', '=', False),
        ], limit=1)
        if quant:
            quant.inventory_quantity = target_quantity
        else:
            quant = quant_model.create({
                'product_id': product.id,
                'location_id': warehouse.lot_stock_id.id,
                'inventory_quantity': target_quantity,
            })
        quants |= quant
        _logger.info(
            'Tồn khởi điểm ước tính %s: %s %s '
            '(40 lượt/tháng, dự phòng 50%%, phân bổ đều trên %s dịch vụ).',
            material.default_code,
            target_quantity,
            material.uom_id.display_name,
            len(services),
        )

    quants.action_apply_inventory()
