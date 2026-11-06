from odoo import models, fields


class CustomerSkinProfile(models.Model):
    _name = 'customer.skin.profile'
    _description = 'Hồ sơ tình trạng da khách hàng'
    _order = 'date_recorded desc, id desc'

    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True, index=True, ondelete='restrict'
    )
    date_recorded = fields.Date(
        string='Ngày ghi nhận', default=fields.Date.context_today, required=True
    )
    skin_type = fields.Selection([
        ('normal', 'Da thường'),
        ('dry', 'Da khô'),
        ('oily', 'Da dầu'),
        ('combination', 'Da hỗn hợp'),
        ('sensitive', 'Da nhạy cảm'),
        ('unknown', 'Chưa xác định'),
    ], string='Loại da', default='unknown')
    condition_note = fields.Text(string='Tình trạng được ghi nhận')
    product_caution = fields.Text(string='Lưu ý sản phẩm/dịch vụ')
    staff_note = fields.Text(string='Ghi chú nhân viên')
    user_id = fields.Many2one(
        'res.users', string='Người ghi nhận', default=lambda self: self.env.user
    )
