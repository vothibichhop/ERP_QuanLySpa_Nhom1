from odoo import _, api, fields, models
from odoo.fields import Command
from odoo.exceptions import UserError


SPA_FIXED_COMBOS = (
    ('relax_body_hair', 'Combo thư giãn - Massage body + Gội đầu thư giãn', 'relaxation', (
        ('Massage body thư giãn', 'product_service_massage_body_relax'),
        ('Gội đầu thư giãn', 'product_service_hair_wash_relax'),
    )),
    ('relax_hot_stone_herbal_bath', 'Combo thư giãn - Massage đá nóng + Tắm thảo dược', 'relaxation', (
        ('Massage đá nóng', 'product_service_massage_hot_stone'),
        ('Tắm thảo dược', 'product_service_herbal_bath'),
    )),
    ('relax_neck_wellness_hair', 'Combo thư giãn - Massage cổ vai gáy + Gội đầu dưỡng sinh', 'relaxation', (
        ('Massage cổ vai gáy', 'product_service_massage_neck_shoulder'),
        ('Gội đầu dưỡng sinh', 'product_service_hair_wash_wellness'),
    )),
    ('relax_oil_scalp', 'Combo thư giãn - Massage tinh dầu + Massage da đầu', 'relaxation', (
        ('Massage tinh dầu', 'product_service_massage_oil'),
        ('Massage da đầu', 'product_service_scalp_massage'),
    )),
    ('facial_basic_mask', 'Combo da mặt - Chăm sóc cơ bản + Đắp mặt nạ', 'facial', (
        ('Chăm sóc da cơ bản', 'product_service_facial_basic'),
        ('Đắp mặt nạ', 'product_service_facial_mask'),
    )),
    ('facial_deep_massage', 'Combo da mặt - Chăm sóc chuyên sâu + Massage mặt', 'facial', (
        ('Chăm sóc da chuyên sâu', 'product_service_facial_deep_care'),
        ('Massage mặt', 'product_service_facial_massage'),
    )),
    ('facial_oily_device', 'Combo da mặt - Chăm sóc da dầu/khô + Thiết bị chuyên dụng', 'facial', (
        ('Chăm sóc da dầu, da khô', 'product_service_facial_oily_dry_skin'),
        ('Chăm sóc da bằng thiết bị chuyên dụng', 'product_service_facial_specialized_device'),
    )),
    ('body_exfoliation_wrap', 'Combo body - Tẩy tế bào chết + Ủ dưỡng thể', 'body', (
        ('Tẩy tế bào chết body', 'product_service_body_exfoliation'),
        ('Ủ dưỡng thể', 'product_service_body_wrap'),
    )),
    ('body_exfoliation_wrap_oil', 'Combo body - Tẩy tế bào chết + Ủ dưỡng thể + Massage tinh dầu', 'body', (
        ('Tẩy tế bào chết body', 'product_service_body_exfoliation'),
        ('Ủ dưỡng thể', 'product_service_body_wrap'),
        ('Massage tinh dầu', 'product_service_massage_oil'),
    )),
    ('body_back_neck', 'Combo body - Chăm sóc da lưng + Massage lưng/cổ vai gáy', 'body', (
        ('Chăm sóc da lưng', 'product_service_back_care'),
        ('Massage cổ vai gáy', 'product_service_massage_neck_shoulder'),
    )),
    ('full_body_facial', 'Combo toàn diện - Massage body + Chăm sóc da cơ bản', 'comprehensive', (
        ('Massage body thư giãn', 'product_service_massage_body_relax'),
        ('Chăm sóc da cơ bản', 'product_service_facial_basic'),
    )),
    ('full_body_wrap_facial', 'Combo toàn diện - Tẩy tế bào chết + Ủ dưỡng thể + Chăm sóc da mặt', 'comprehensive', (
        ('Tẩy tế bào chết body', 'product_service_body_exfoliation'),
        ('Ủ dưỡng thể', 'product_service_body_wrap'),
        ('Chăm sóc da cơ bản', 'product_service_facial_basic'),
    )),
    ('full_body_hair_facial', 'Combo toàn diện - Massage body + Gội đầu dưỡng sinh + Chăm sóc da mặt', 'comprehensive', (
        ('Massage body thư giãn', 'product_service_massage_body_relax'),
        ('Gội đầu dưỡng sinh', 'product_service_hair_wash_wellness'),
        ('Chăm sóc da cơ bản', 'product_service_facial_basic'),
    )),
    ('hair_herbal_scalp', 'Combo tóc - Gội đầu thảo dược + Chăm sóc tóc và da đầu', 'hair', (
        ('Gội đầu thảo dược', 'product_service_hair_wash_herbal'),
        ('Chăm sóc tóc và da đầu', 'product_service_hair_scalp_care'),
    )),
    ('hair_neck_scalp', 'Combo tóc - Gội đầu massage cổ vai gáy + Massage da đầu', 'hair', (
        ('Gội đầu kết hợp massage cổ vai gáy', 'product_service_hair_wash_neck_massage'),
        ('Massage da đầu', 'product_service_scalp_massage'),
    )),
    ('hands_feet_nails', 'Combo tay chân - Chăm sóc tay chân + Chăm sóc móng', 'nail', (
        ('Chăm sóc bàn tay, bàn chân', 'product_service_hand_foot_care'),
        ('Chăm sóc móng tay, móng chân', 'product_service_nail_hand_foot_care'),
    )),
    ('nails_cuticle_gel', 'Combo nail - Cắt da tạo form + Sơn gel', 'nail', (
        ('Cắt da, tạo form móng', 'product_service_nail_cuticle_shape'),
        ('Sơn gel', 'product_service_nail_gel_polish'),
    )),
    ('nails_extensions_art', 'Combo nail - Đắp móng + Vẽ móng', 'nail', (
        ('Đắp móng', 'product_service_nail_extensions'),
        ('Vẽ móng', 'product_service_nail_art'),
    )),
    ('couple', 'Combo cặp đôi - Massage đôi + Gội đầu + Xông hơi thảo dược', 'audience', (
        ('Massage đôi - lượt 1', 'product_service_massage_body_relax'),
        ('Massage đôi - lượt 2', 'product_service_massage_body_relax'),
        ('Gội đầu thư giãn', 'product_service_hair_wash_relax'),
        ('Xông hơi thảo dược', 'product_service_herbal_steam'),
    )),
    ('bridal', 'Combo cô dâu - Body + Da mặt + Chăm sóc tay chân', 'audience', (
        ('Tẩy tế bào chết body', 'product_service_body_exfoliation'),
        ('Ủ dưỡng thể', 'product_service_body_wrap'),
        ('Chăm sóc da cơ bản', 'product_service_facial_basic'),
        ('Chăm sóc bàn tay, bàn chân', 'product_service_hand_foot_care'),
    )),
    ('office', 'Combo văn phòng - Massage cổ vai gáy + Gội đầu massage', 'audience', (
        ('Massage cổ vai gáy', 'product_service_massage_neck_shoulder'),
        ('Gội đầu kết hợp massage cổ vai gáy', 'product_service_hair_wash_neck_massage'),
    )),
    ('men', 'Combo nam - Massage body + Gội đầu + Chăm sóc da cơ bản', 'audience', (
        ('Massage body thư giãn', 'product_service_massage_body_relax'),
        ('Gội đầu thư giãn', 'product_service_hair_wash_relax'),
        ('Chăm sóc da cơ bản', 'product_service_facial_basic'),
    )),
)

SPA_COMBO_CATEGORIES = [
    ('relaxation', 'Combo thư giãn'),
    ('facial', 'Combo chăm sóc da mặt'),
    ('body', 'Combo chăm sóc body'),
    ('comprehensive', 'Combo chăm sóc toàn diện'),
    ('hair', 'Combo tóc và da đầu'),
    ('nail', 'Combo tay, chân và nail'),
    ('audience', 'Combo theo đối tượng'),
    ('duration', 'Combo theo thời lượng'),
]

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    spa_service_code = fields.Char(
        string='Mã dịch vụ', readonly=True, copy=False, index=True
    )
    spa_combo_key = fields.Char(copy=False, index=True, readonly=True)
    spa_combo_category = fields.Selection(
        SPA_COMBO_CATEGORIES, string='Danh mục combo', copy=False
    )
    spa_category = fields.Selection([
        ('massage', 'Massage và chăm sóc cơ thể'),
        ('hair', 'Gội đầu dưỡng sinh'),
        ('facial', 'Chăm sóc da mặt'),
        ('body_care', 'Chăm sóc và làm đẹp cơ thể'),
        ('nail', 'Nail và chăm sóc móng'),
        ('spa_package', 'Dịch vụ công nghệ và liệu trình chuyên sâu'),
    ], string='Category')
    spa_duration_minutes = fields.Integer(string='Completion Time (minutes)')
    description = fields.Text(string='Description')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._assign_missing_spa_service_codes()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._assign_missing_spa_service_codes()
        return result

    def _assign_missing_spa_service_codes(self):
        if not self:
            self = self.search([
                ('type', 'in', ['service', 'combo']),
                ('spa_service_code', '=', False),
            ])
        products = self.filtered(
            lambda product: product.type in ('service', 'combo')
            and not product.spa_service_code
        )
        for product in products:
            code = self.env['ir.sequence'].next_by_code('spa.service')
            if not code:
                raise UserError(_('Không thể tạo mã dịch vụ hoặc combo Spa: chưa cấu hình chuỗi mã.'))
            super(ProductTemplate, product).write({'spa_service_code': code})

    @api.model
    def _create_spa_combo_choice(self, name, products):
        if not products:
            raise UserError(_('Không thể tạo combo Spa "%s": nhóm lựa chọn không có dịch vụ.', name))
        min_price = min(products.mapped('list_price'))
        return self.env['product.combo'].create({
            'name': name,
            'combo_item_ids': [
                Command.create({
                    'product_id': product.product_variant_id.id,
                    'extra_price': product.list_price - min_price,
                })
                for product in products
            ],
        })

    @api.model
    def _create_spa_combo_product(self, key, name, category, choice_specs):
        descriptions = [
            f"{choice_name}: {products.name}"
            if len(products) == 1 else f"{choice_name} (chọn 1 dịch vụ)"
            for choice_name, products in choice_specs
        ]
        description_sale = _('Bao gồm / lựa chọn: %s', '; '.join(descriptions))
        existing = self.search([('spa_combo_key', '=', key)], limit=1)
        if existing:
            if existing.description_sale and existing.description_sale.startswith('Bao gồm / lựa chọn:'):
                existing.write({'description_sale': description_sale})
            return
        choices = self.env['product.combo']
        base_price = 0
        for choice_name, products in choice_specs:
            choice = self._create_spa_combo_choice(choice_name, products)
            choices |= choice
            base_price += min(products.mapped('list_price'))
        self.create({
            'name': name,
            'type': 'combo',
            'sale_ok': True,
            'purchase_ok': False,
            'list_price': self.env.company.currency_id.round(base_price),
            'spa_combo_category': category,
            'spa_combo_key': key,
            'description_sale': description_sale,
            'combo_ids': [Command.set(choices.ids)],
        })

    def _create_spa_combo_products(self):
        for key, name, category, components in SPA_FIXED_COMBOS:
            choice_specs = [
                (choice_name, self.env.ref(f'spa.{xml_id}'))
                for choice_name, xml_id in components
            ]
            self._create_spa_combo_product(key, name, category, choice_specs)

        self.search([
            ('spa_combo_key', 'in', ['duration_60', 'duration_90', 'duration_120']),
        ]).write({'active': False})
