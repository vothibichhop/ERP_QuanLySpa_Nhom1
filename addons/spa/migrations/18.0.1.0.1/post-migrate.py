from odoo import SUPERUSER_ID, api


SERVICE_PRICES = {
    'product_service_massage_body_relax': 300000,
    'product_service_massage_hot_stone': 400000,
    'product_service_massage_oil': 350000,
    'product_service_massage_foot': 150000,
    'product_service_massage_neck_shoulder': 120000,
    'product_service_body_exfoliation': 250000,
    'product_service_body_wrap': 300000,
    'product_service_hair_wash_relax': 120000,
    'product_service_hair_wash_herbal': 180000,
    'product_service_hair_wash_wellness': 250000,
    'product_service_scalp_massage': 100000,
    'product_service_hair_scalp_care': 220000,
    'product_service_hair_wash_neck_massage': 300000,
    'product_service_facial_basic': 250000,
    'product_service_facial_deep_care': 500000,
    'product_service_facial_mask': 80000,
    'product_service_facial_massage': 150000,
    'product_service_facial_oily_dry_skin': 300000,
    'product_service_facial_exfoliation': 120000,
    'product_service_facial_specialized_device': 700000,
    'product_service_hand_foot_care': 70000,
    'product_service_back_care': 200000,
    'product_service_body_treatment_plan': 450000,
    'product_service_nail_cuticle_shape': 40000,
    'product_service_nail_gel_polish': 150000,
    'product_service_nail_extensions': 250000,
    'product_service_nail_art': 80000,
    'product_service_nail_hand_foot_care': 150000,
    'product_service_facial_machine_care': 600000,
    'product_service_skin_recovery': 600000,
    'product_service_body_care_plan': 500000,
    'product_service_herbal_steam': 150000,
    'product_service_salt_stone_steam': 180000,
    'product_service_herbal_bath': 200000,
    'product_service_milk_bath': 220000,
    'product_service_flower_bath': 250000,
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xml_id, price in SERVICE_PRICES.items():
        service = env.ref(f'spa.{xml_id}', raise_if_not_found=False)
        if service:
            service.write({'list_price': price})
