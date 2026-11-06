from odoo import api, fields, models
from odoo.exceptions import UserError

SPA_LOYALTY_TIERS = (
    ('diamond', 2000, 20.0),
    ('gold', 1500, 10.0),
    ('silver', 500, 5.0),
)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_spa_customer = fields.Boolean(string='Khách hàng Spa', default=False, copy=False, index=True)
    spa_customer_code = fields.Char(string='Mã khách hàng Spa', copy=False, index=True)
    customer_code = fields.Char(
        string='Mã khách hàng',
        copy=False,
        index=True,
        readonly=True,
    )
    customer_type = fields.Selection([
        ('new', 'Mới'),
        ('silver', 'Bạc'),
        ('gold', 'Vàng'),
        ('diamond', 'Kim cương'),
    ], string='Phân loại khách hàng', default='new', tracking=True)
    spa_birthday = fields.Date(string='Ngày sinh')
    spa_gender = fields.Selection(
        [('male', 'Nam'), ('female', 'Nữ'), ('other', 'Khác')], string='Giới tính'
    )
    spa_skin_type = fields.Selection([
        ('normal', 'Da thường'),
        ('dry', 'Da khô'),
        ('oily', 'Da dầu'),
        ('combination', 'Da hỗn hợp'),
        ('sensitive', 'Da nhạy cảm'),
        ('other', 'Khác'),
    ], string='Loại da')
    skin_condition = fields.Text(string='Tình trạng da')
    customer_need = fields.Text(string='Nhu cầu chăm sóc')
    customer_note = fields.Text(string='Lưu ý khách hàng')
    care_note = fields.Text(string='Lưu ý chăm sóc')
    loyalty_point = fields.Integer(string='Điểm tích lũy', default=0, readonly=True, copy=False)
    spa_appointment_ids = fields.One2many(
        'spa.appointment', 'customer_id', string='Lịch sử liệu trình'
    )
    spa_appointment_count = fields.Integer(
        string='Số lịch hẹn', compute='_compute_spa_appointment_count'
    )
    care_need_ids = fields.One2many('customer.care.need', 'partner_id', string='Nhu cầu chăm sóc')
    skin_profile_ids = fields.One2many('customer.skin.profile', 'partner_id', string='Hồ sơ tình trạng da')
    treatment_ids = fields.One2many('customer.treatment', 'partner_id', string='Liệu trình')
    loyalty_transaction_ids = fields.One2many(
        'customer.loyalty.transaction', 'partner_id', string='Lịch sử điểm'
    )

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        customers = partners.filtered(
            lambda partner: (
                partner.customer_rank > 0 or partner.is_spa_customer
            ) and not partner.customer_code
        )
        for partner in customers:
            partner.customer_code = self._next_customer_code()
        return partners

    @api.model
    def _next_customer_code(self):
        sequence = self.env['ir.sequence']
        while True:
            code = sequence.next_by_code('spa.customer')
            if not code:
                raise UserError('Không tìm thấy sequence tạo mã khách hàng Spa.')
            existing_code = self.with_context(active_test=False).search(
                ['|', ('customer_code', '=', code), ('spa_customer_code', '=', code)],
                limit=1,
            )
            if not existing_code:
                return code

    @api.model
    def _customer_type_for_loyalty_points(self, points):
        for customer_type, minimum_points, _ in SPA_LOYALTY_TIERS:
            if points >= minimum_points:
                return customer_type
        return 'new'

    def _get_spa_tier_discount_percentage(self):
        self.ensure_one()
        for customer_type, minimum_points, discount in SPA_LOYALTY_TIERS:
            if (
                self.customer_type == customer_type
                and self.loyalty_point >= minimum_points
            ):
                return discount
        return 0.0

    @api.depends('spa_appointment_ids')
    def _compute_spa_appointment_count(self):
        grouped_data = self.env['spa.appointment']._read_group(
            [('customer_id', 'in', self.ids)],
            ['customer_id'],
            ['__count'],
        )
        counts = {partner.id: count for partner, count in grouped_data}
        for partner in self:
            partner.spa_appointment_count = counts.get(partner.id, 0)

    def action_view_spa_appointments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lịch hẹn',
            'res_model': 'spa.appointment',
            'view_mode': 'list,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id},
        }
